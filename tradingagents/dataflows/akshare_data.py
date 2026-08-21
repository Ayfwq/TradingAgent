"""akshare-based data vendor for the domestic (China) network environment.

Data sources behind akshare (all reachable from mainland China without
Yahoo Finance):
  - Sina Finance: A-share / US / HK daily OHLCV, financial indicators
  - Eastmoney:    per-ticker news (search-api domain, not the blocked
                  push2his kline domain), spot quotes
  - JinShi (金十): macro series (CPI, GDP, LPR, M2, ...)

Design rules (kept consistent with the yfinance vendor):
  - Functions return either a formatted string or raise the typed
    ``NoMarketDataError`` so the router emits one clear unavailable
    signal; they never raise generic exceptions that crash the graph.
  - OHLCV is returned with the same capitalized columns
    (``Date/Open/High/Low/Close/Volume``) the rest of the framework
    expects (stockstats indicators, market-data validator, reports).
  - Symbol handling: A-share ``600519.SS`` -> ``sh600519``,
    ``000001.SZ`` -> ``sz000001``, US ``NVDA`` stays, HK ``0700.HK`` ->
    ``00700``. Unsupported instruments raise ``NoMarketDataError``.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

import pandas as pd

from .config import get_config
from .errors import NoMarketDataError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thread-safety
#
# The Sina daily endpoints (stock_zh_a_daily / stock_zh_index_daily /
# stock_us_daily / stock_hk_daily) decrypt their payloads with py_mini_racer,
# a V8 engine that is NOT thread-safe: two concurrent calls crash the whole
# process (FATAL: partition_address_space.cc) with no catchable exception.
# The analyst fan-out runs tools concurrently, so every akshare call is
# serialized through one re-entrant lock. LLM calls (the dominant cost) stay
# parallel; only the fast data fetches serialize.
# ---------------------------------------------------------------------------
_AK_LOCK = threading.RLock()

# ---------------------------------------------------------------------------
# Symbol mapping
# ---------------------------------------------------------------------------


def _to_akshare_symbol(ticker: str) -> tuple[str, str]:
    """Map a framework ticker to (market, akshare symbol).

    markets: ``ashare`` | ``us`` | ``hk`` | None (unsupported)
    """
    if not isinstance(ticker, str) or not ticker.strip():
        return None, ""
    raw = ticker.strip().upper()

    # A-share: exchange-suffixed (600519.SS / 000001.SZ / 430047.BJ) or bare 6-digit.
    for suffix, prefix in ((".SS", "sh"), (".SH", "sh"), (".SZ", "sz"), (".BJ", "bj")):
        if raw.endswith(suffix):
            digits = raw[: -len(suffix)]
            if digits.isdigit():
                return "ashare", prefix + digits
    if raw.isdigit() and len(raw) == 6:
        first = raw[0]
        if first in ("6", "5", "9"):
            return "ashare", "sh" + raw
        if first in ("0", "1", "2", "3"):
            return "ashare", "sz" + raw
        if first in ("4", "8"):
            return "ashare", "bj" + raw

    # HK: 0700.HK -> 00700 (5-digit zero-padded)
    if raw.endswith(".HK") and raw[: -3].isdigit():
        digits = raw[: -3]
        return "hk", digits.zfill(5)

    # US / plain tickers pass through (NVDA, AAPL, BRK.B, ^GSPC...)
    if _is_plain_us_symbol(raw):
        return "us", raw

    return None, raw


def _is_plain_us_symbol(raw: str) -> bool:
    """Accept letters/digits/dots/caret/equals — anything that is not an
    obviously exchange-suffixed or numeric Chinese instrument."""
    if not raw or raw[0].isdigit():
        return False
    if any(raw.endswith(s) for s in (".SS", ".SH", ".SZ", ".BJ", ".HK", ".T", ".L", ".TO", ".AX", ".NS", ".BO")):
        return False
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-^=: ")
    return all(c in allowed for c in raw)


# ---------------------------------------------------------------------------
# OHLCV helpers
# ---------------------------------------------------------------------------


def _download_daily(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Download daily OHLCV via akshare (Sina) for the given ticker.

    Returns a DataFrame with lowercase sina columns
    (date/open/high/low/close/volume), rows sorted by date, already
    clipped to [start_date, end_date] where the source supports it.

    Raises NoMarketDataError when the symbol is unsupported or empty.
    """
    import akshare as ak

    market, symbol = _to_akshare_symbol(ticker)
    if market is None:
        logger.warning("unsupported market for akshare vendor: %s", ticker)
        raise NoMarketDataError(ticker, ticker, "unsupported market for akshare vendor")
    try:
        if market == "us":
            # Sina US daily returns the full history; filter client-side.
            df = _ak_retry(lambda: ak.stock_us_daily(symbol=symbol, adjust="qfq"))
        elif market == "hk":
            df = _ak_retry(lambda: ak.stock_hk_daily(symbol=symbol))
        else:  # ashare
            df = _ak_retry(
                lambda: ak.stock_zh_a_daily(
                    symbol=symbol,
                    start_date=start_date.replace("-", ""),
                    end_date=end_date.replace("-", ""),
                    adjust="qfq",
                )
            )
    except NoMarketDataError:
        raise
    except Exception as exc:
        # Contract: the vendor surfaces ONE typed signal (NoMarketDataError)
        # so the router can emit a clear "unavailable" instead of a raw
        # generic exception leaking into the graph.
        logger.warning("akshare download failed for %s (%s): %s", ticker, symbol, exc)
        raise NoMarketDataError(ticker, symbol, f"akshare download failed: {exc}") from exc

    if df is None or df.empty:
        logger.warning("akshare returned no rows for %s (%s)", ticker, symbol)
        raise NoMarketDataError(ticker, symbol, "no rows returned by akshare")

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")

    if market in ("us", "hk"):
        start_dt = pd.Timestamp(start_date)
        end_dt = pd.Timestamp(end_date)
        df = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)]

    if df.empty:
        logger.warning("akshare returned no rows for %s between %s and %s", ticker, start_date, end_date)
        raise NoMarketDataError(ticker, symbol, f"no rows between {start_date} and {end_date}")
    logger.debug("akshare returned %d rows for %s (%s)", len(df), ticker, symbol)
    return df


def _ak_retry(func, max_retries=2, base_delay=1.0):
    """Small retry wrapper for akshare calls (network blips are common).

    Serialized through ``_AK_LOCK``: akshare's Sina endpoints use the
    py_mini_racer V8 engine, which crashes the process on concurrent use.
    """
    with _AK_LOCK:
        last = None
        for attempt in range(max_retries + 1):
            try:
                return func()
            except Exception as exc:  # noqa: BLE001 — akshare raises many ad-hoc types
                last = exc
                if attempt < max_retries:
                    logger.debug("akshare call attempt %d failed, retrying: %s", attempt + 1, exc)
                    time.sleep(base_delay * (attempt + 1))
        raise last


def _to_capitalized_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Convert akshare's lowercase daily frame to the framework's shape.

    Output columns: ``Date`` (datetime), ``Open/High/Low/Close/Volume``.
    """
    out = pd.DataFrame(
        {
            "Date": pd.to_datetime(df["date"], errors="coerce"),
            "Open": pd.to_numeric(df["open"], errors="coerce"),
            "High": pd.to_numeric(df["high"], errors="coerce"),
            "Low": pd.to_numeric(df["low"], errors="coerce"),
            "Close": pd.to_numeric(df["close"], errors="coerce"),
            "Volume": pd.to_numeric(df["volume"], errors="coerce"),
        }
    )
    return out.dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)


def load_ohlcv_akshare(symbol: str, curr_date: str) -> pd.DataFrame:
    """Fetch 5-year OHLCV window (to today) via akshare, like
    ``stockstats_utils.load_ohlcv`` does with yfinance, so indicators and
    the market-data validator can run on the same cache contract.

    Returns a DataFrame with ``Date/Open/High/Low/Close/Volume`` (capitalized)
    filtered to rows on or before ``curr_date``. Raises NoMarketDataError if
    nothing usable is returned.
    """
    today = pd.Timestamp.today()
    start_str = (today - pd.DateOffset(years=5)).strftime("%Y-%m-%d")
    end_str = (today + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    logger.debug("load_ohlcv_akshare called for %s curr_date=%s", symbol, curr_date)
    df = _download_daily(symbol, start_str, end_str)
    out = _to_capitalized_ohlcv(df)
    if out.empty:
        logger.warning("akshare returned no OHLCV rows for %s", symbol)
        raise NoMarketDataError(symbol, symbol, "no OHLCV rows from akshare")

    cutoff = pd.Timestamp(curr_date)
    out = out[out["Date"] <= cutoff].sort_values("Date")
    if out.empty:
        logger.warning("akshare returned no rows on or before %s for %s", curr_date, symbol)
        raise NoMarketDataError(
            symbol, symbol, f"no rows on or before {curr_date}"
        )
    logger.debug("akshare OHLCV returned %d rows for %s", len(out), symbol)
    return out.reset_index(drop=True)


def get_stock_data_akshare(
    symbol: str,
    start_date: str,
    end_date: str,
) -> str:
    """Return OHLCV as a CSV string (header + rows), same shape as the
    yfinance vendor so agent prompts and downstream parsing are unchanged."""
    logger.debug("get_stock_data_akshare called for %s (%s to %s)", symbol, start_date, end_date)
    try:
        df = _download_daily(symbol, start_date, end_date)
        market, canonical = _to_akshare_symbol(symbol)
        csv_string = _to_capitalized_ohlcv(df).to_csv(index=False)
        label = canonical if canonical != symbol.upper() else symbol.upper()
        header = f"# Stock data for {label} (akshare/{market}) from {start_date} to {end_date}\n"
        header += f"# Total records: {len(df)}\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        logger.debug("akshare returned %d rows for %s", len(df), symbol)
        return header + csv_string
    except NoMarketDataError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("akshare get_stock_data failed for %s: %s", symbol, exc)
        raise NoMarketDataError(symbol, symbol, f"akshare error: {exc}") from exc


# ---------------------------------------------------------------------------
# Fundamentals (Sina)
# ---------------------------------------------------------------------------


def _strip_ashare_suffix(ticker: str) -> str:
    """600519.SS -> 600519; returns None for non-A-share symbols."""
    market, symbol = _to_akshare_symbol(ticker)
    if market != "ashare":
        return None
    return symbol[2:] if symbol[:2] in ("sh", "sz", "bj") else symbol


def get_fundamentals_akshare(ticker: str, curr_date: str = None) -> str:
    """Company fundamentals overview from Sina's financial indicator table."""
    logger.debug("get_fundamentals_akshare called for %s curr_date=%s", ticker, curr_date)
    code = _strip_ashare_suffix(ticker)
    if code is None:
        return (
            f"Fundamentals unavailable for '{ticker}' via akshare (A-share only). "
            "Proceed without it."
        )
    try:
        import akshare as ak

        start_year = str(max(2020, int(pd.Timestamp(curr_date or datetime.now()).year) - 3))
        df = _ak_retry(lambda: ak.stock_financial_analysis_indicator(symbol=code, start_year=start_year))
        if df is None or df.empty:
            logger.warning("akshare returned no fundamentals for %s (%s)", ticker, code)
            raise NoMarketDataError(ticker, code, "no fundamentals returned")

        # Keep the most recent up to 8 reporting periods (columns are rows here;
        # each row is a 报告期). Rendering everything is token-expensive.
        recent = df.head(8)
        header = f"# Company Fundamentals for {code} (akshare/Sina, A-share)\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        logger.debug("akshare fundamentals returned %d rows for %s", len(recent), ticker)
        return header + recent.to_csv(index=False)
    except NoMarketDataError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("akshare fundamentals fetch failed for %s: %s", ticker, exc)
        return f"Error retrieving fundamentals for {ticker} via akshare: {exc}"


def _financial_abstract_report(ticker: str, curr_date: str | None, section: str) -> str:
    """Render the Sina financial abstract (指标表) as a report.

    ``section`` only labels the report; the abstract covers the balance
    sheet / income / cash-flow key indicators in one table.
    """
    logger.debug("_financial_abstract_report called for %s section=%s curr_date=%s", ticker, section, curr_date)
    code = _strip_ashare_suffix(ticker)
    if code is None:
        return (
            f"{section} unavailable for '{ticker}' via akshare (A-share only). "
            "Proceed without it."
        )
    try:
        import akshare as ak

        df = _ak_retry(lambda: ak.stock_financial_abstract(symbol=code))
        if df is None or df.empty:
            logger.warning("akshare returned no %s for %s (%s)", section, ticker, code)
            raise NoMarketDataError(ticker, code, "no financial abstract returned")

        # Columns are reporting periods (e.g. 20251231); keep those up to
        # curr_date to avoid look-ahead, newest first.
        period_cols = [c for c in df.columns if str(c).isdigit()]
        if curr_date:
            cutoff = pd.Timestamp(curr_date)
            period_cols = [c for c in period_cols if pd.Timestamp(str(c)) <= cutoff]
        period_cols = sorted(period_cols, reverse=True)[:4]

        keep = [c for c in df.columns if c not in period_cols] + period_cols
        table = df[keep].head(60)  # cap rows to keep token use bounded

        header = f"# {section} data for {code} (akshare/Sina, A-share)\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        logger.debug("akshare %s returned %d rows for %s", section, len(table), ticker)
        return header + table.to_csv(index=False)
    except NoMarketDataError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("akshare %s fetch failed for %s: %s", section, ticker, exc)
        return f"Error retrieving {section} for {ticker} via akshare: {exc}"


def get_balance_sheet_akshare(ticker: str, freq: str = "quarterly", curr_date: str = None) -> str:
    return _financial_abstract_report(ticker, curr_date, "Balance Sheet")


def get_cashflow_akshare(ticker: str, freq: str = "quarterly", curr_date: str = None) -> str:
    return _financial_abstract_report(ticker, curr_date, "Cash Flow")


def get_income_statement_akshare(ticker: str, freq: str = "quarterly", curr_date: str = None) -> str:
    return _financial_abstract_report(ticker, curr_date, "Income Statement")


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------


def get_news_akshare(ticker: str, start_date: str, end_date: str) -> str:
    """Per-ticker news via Eastmoney's search API (reachable from CN)."""
    logger.debug("get_news_akshare called for %s (%s to %s)", ticker, start_date, end_date)
    code = _strip_ashare_suffix(ticker)
    if code is None:
        return (
            f"No news found for {ticker} via akshare (per-ticker news is "
            "A-share only)."
        )
    try:
        import akshare as ak

        limit = get_config()["news_article_limit"]
        df = _ak_retry(lambda: ak.stock_news_em(symbol=code))
        if df is None or df.empty:
            logger.warning("akshare returned no news for %s (%s)", ticker, code)
            return f"No news found for {ticker}"

        start_dt = pd.Timestamp(start_date)
        end_dt = pd.Timestamp(end_date) + pd.Timedelta(days=1)

        news_str = ""
        kept = 0
        for _, row in df.iterrows():
            try:
                pub = pd.to_datetime(row.get("发布时间"), errors="coerce")
            except Exception:  # noqa: BLE001
                pub = pd.NaT
            if pd.isna(pub) or not (start_dt <= pub < end_dt):
                continue
            title = str(row.get("新闻标题", "")).strip()
            content = str(row.get("新闻内容", "")).strip()
            source = str(row.get("文章来源", "")).strip()
            link = str(row.get("新闻链接", "")).strip()
            if not title:
                continue
            news_str += f"### {title} (source: {source or 'Unknown'})\n"
            if content:
                news_str += f"{content[:400]}\n"
            if link:
                news_str += f"Link: {link}\n"
            news_str += "\n"
            kept += 1
            if kept >= limit:
                break

        if kept == 0:
            logger.warning("no akshare news for %s within %s..%s", ticker, start_date, end_date)
            return f"No news found for {ticker} between {start_date} and {end_date}"
        logger.debug("akshare returned %d news articles for %s", kept, ticker)
        return f"## {ticker} News, from {start_date} to {end_date}:\n\n{news_str}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("akshare news fetch failed for %s: %s", ticker, exc)
        return f"Error fetching news for {ticker} via akshare: {exc}"


def get_global_news_akshare(
    curr_date: str,
    look_back_days: int | None = None,
    limit: int | None = None,
) -> str:
    """Global macro news via Sina's 7x24 flash feed (stable in CN)."""
    logger.debug("get_global_news_akshare called for %s look_back_days=%s limit=%s", curr_date, look_back_days, limit)
    config = get_config()
    if look_back_days is None:
        look_back_days = config["global_news_lookback_days"]
    if limit is None:
        limit = config["global_news_article_limit"]
    try:
        import akshare as ak

        df = _ak_retry(lambda: ak.stock_info_global_sina())
        if df is None or df.empty:
            logger.warning("akshare returned no global news for %s", curr_date)
            return f"No global news found for {curr_date}"

        start_dt = pd.Timestamp(curr_date) - pd.Timedelta(days=int(look_back_days))
        end_dt = pd.Timestamp(curr_date) + pd.Timedelta(days=1)

        news_str = ""
        kept = 0
        for _, row in df.iterrows():
            try:
                pub = pd.to_datetime(row.get("时间"), errors="coerce")
            except Exception:  # noqa: BLE001
                pub = pd.NaT
            if pd.isna(pub) or not (start_dt <= pub < end_dt):
                continue
            content = str(row.get("内容", "")).strip()
            if not content:
                continue
            news_str += f"### {content[:500]}\n\n"
            kept += 1
            if kept >= limit:
                break

        if kept == 0:
            logger.warning("no akshare global news within %s..%s", start_dt, curr_date)
            return f"No global news found between {start_dt:%Y-%m-%d} and {curr_date}"
        logger.debug("akshare returned %d global news articles for %s", kept, curr_date)
        return f"## Global Market News, from {start_dt:%Y-%m-%d} to {curr_date}:\n\n{news_str}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("akshare global news fetch failed for %s: %s", curr_date, exc)
        return f"Error fetching global news via akshare: {exc}"


def get_insider_transactions_akshare(ticker: str) -> str:
    """Insider (董监高) transactions for A-shares via Xueqiu's insider-trade feed.

    The feed covers the whole market; we filter to the requested ticker and
    the most recent 90 days. Symbols like ``600519.SS`` / ``000001.SZ`` map to
    Xueqiu's ``SH600519`` / ``SZ000001`` codes.
    """
    logger.debug("get_insider_transactions_akshare called for %s", ticker)
    code = _strip_ashare_suffix(ticker)
    if code is None:
        return (
            f"No insider transactions data available for '{ticker}' via the "
            "akshare vendor (A-share only). Proceed without it."
        )
    try:
        import akshare as ak

        # Xueqiu code format: SH600519 / SZ000001 / BJ...
        if code.startswith(("60", "68", "90")):
            xq_code = "SH" + code
        elif code.startswith(("00", "30", "20")):
            xq_code = "SZ" + code
        else:
            xq_code = "BJ" + code

        df = _ak_retry(lambda: ak.stock_inner_trade_xq())
        if df is None or df.empty:
            return f"No insider transactions reported for symbol '{ticker}'"

        df = df.copy()
        df["变动日期"] = pd.to_datetime(df["变动日期"], errors="coerce")
        df = df.dropna(subset=["变动日期"])

        match = df[df["股票代码"] == xq_code]
        if match.empty:
            return f"No insider transactions reported for symbol '{ticker}'"

        # Most recent 90 days, newest first.
        cutoff = pd.Timestamp.today() - pd.Timedelta(days=90)
        match = match[match["变动日期"] >= cutoff].sort_values("变动日期", ascending=False)

        header = f"# Insider Transactions data for {ticker} (akshare/Xueqiu, A-share)\n"
        header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        if match.empty:
            logger.debug("no akshare insider transactions in the last 90 days for %s", ticker)
            return header + f"No insider transactions in the last 90 days for '{ticker}'"
        logger.debug("akshare returned %d insider transaction rows for %s", len(match), ticker)
        return header + match.head(30).to_csv(index=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("akshare insider transactions fetch failed for %s: %s", ticker, exc)
        return f"Error retrieving insider transactions for {ticker} via akshare: {exc}"


# ---------------------------------------------------------------------------
# Macro (JinShi / akshare macro series)
# ---------------------------------------------------------------------------

# Friendly alias -> (akshare function name, display label)
_MACRO_SERIES = {
    "cpi": ("macro_china_cpi_yearly", "China CPI (yearly, %)"),
    "gdp": ("macro_china_gdp_yearly", "China GDP (yearly, %)"),
    "real_gdp": ("macro_china_gdp_yearly", "China GDP (yearly, %)"),
    "m2": ("macro_china_m2_yearly", "China M2 money supply (yearly)"),
    "pmi": ("macro_china_pmi_yearly", "China PMI (yearly)"),
    "lpr": ("macro_china_lpr", "China LPR loan prime rates"),
    "loan_rate": ("macro_china_lpr", "China LPR loan prime rates"),
    "unemployment": ("macro_china_urban_unemployment", "China surveyed urban unemployment"),
}


def get_macro_indicators_akshare(
    indicator: str,
    curr_date: str,
    look_back_days: int | None = None,
) -> str:
    """China macro series (金十/国家统计局 via akshare)."""
    key = (indicator or "").strip().lower()
    if key not in _MACRO_SERIES:
        return (
            f"DATA_UNAVAILABLE: macro indicator '{indicator}' is not supported by "
            f"the akshare vendor. Supported: {sorted(_MACRO_SERIES)}."
        )
    func_name, label = _MACRO_SERIES[key]
    logger.debug("get_macro_indicators_akshare called for %s curr_date=%s", indicator, curr_date)
    try:
        import akshare as ak

        func = getattr(ak, func_name)
        df = _ak_retry(func)
        if df is None or df.empty:
            logger.warning("akshare returned no %s data", label)
            return f"DATA_UNAVAILABLE: no {label} data returned."

        # Render the most recent observations, newest first.
        df = df.copy()
        date_col = next((c for c in ("日期", "TRADE_DATE") if c in df.columns), None)
        if date_col is not None:
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            df = df.dropna(subset=[date_col]).sort_values(date_col, ascending=False)
        head = df.head(12).to_csv(index=False)
        logger.debug("akshare returned %d %s rows", len(head.splitlines()) - 1, label)
        return f"## {label} (akshare)\n\n{head}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("akshare macro fetch failed for %s: %s", indicator, exc)
        return f"DATA_UNAVAILABLE: akshare macro fetch failed ({exc})."


# ---------------------------------------------------------------------------
# A-share special-context tools (龙虎榜 / 北向资金 / 涨停池 / 行业板块 / 业绩预告)
#
# These enrich the core analysts with A-share-specific signals that have no
# US-market equivalent. Every function degrades to a short string (never a
# crash): a missing record for the ticker is a real answer ("not on the
# limit-up board today"), and a network failure returns DATA_UNAVAILABLE so
# the agent can proceed without the flavour data.
# ---------------------------------------------------------------------------


def _ashare_code(ticker: str) -> str | None:
    """6-digit A-share code (600519) or None for non-A-share tickers."""
    market, symbol = _to_akshare_symbol(ticker)
    if market != "ashare":
        return None
    return symbol[2:] if symbol[:2] in ("sh", "sz", "bj") else symbol


def get_lhb_context(ticker: str, curr_date: str = None, look_back_days: int = 10) -> str:
    """Dragon-Tiger list (龙虎榜) appearances for the ticker.

    Shows abnormal-move institutional/seat activity: net buy, reason for
    being listed, and the 1/2/5-day post-listing returns — a direct
    A-share sentiment/flow signal.
    """
    logger.debug("get_lhb_context called for %s curr_date=%s look_back_days=%s", ticker, curr_date, look_back_days)
    code = _ashare_code(ticker)
    if code is None:
        return f"LHB context unavailable for '{ticker}' via akshare (A-share only)."
    try:
        import akshare as ak

        end_dt = pd.Timestamp(curr_date or datetime.now())
        start_dt = end_dt - pd.Timedelta(days=int(look_back_days))
        df = _ak_retry(
            lambda: ak.stock_lhb_detail_em(
                start_date=start_dt.strftime("%Y%m%d"),
                end_date=end_dt.strftime("%Y%m%d"),
            )
        )
        if df is None or df.empty:
            return f"No LHB (龙虎榜) appearances in the last {look_back_days} days for '{ticker}'"
        rows = df[df["代码"].astype(str) == code]
        if rows.empty:
            return (
                f"No LHB (龙虎榜) appearances in the last {look_back_days} days for '{ticker}'. "
                "Absence from the list is normal for most stocks."
            )
        keep = [c for c in rows.columns if c in (
            "名称", "上榜日", "涨跌幅", "龙虎榜净买额", "龙虎榜买入额",
            "龙虎榜卖出额", "上榜原因", "上榜后1日", "上榜后2日", "上榜后5日",
        )]
        logger.debug("akshare returned %d LHB rows for %s", len(rows), ticker)
        return (
            f"# LHB (龙虎榜) appearances for {ticker} "
            f"(last {look_back_days} days, akshare/Eastmoney)\n"
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            + rows[keep].head(10).to_csv(index=False)
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("akshare LHB fetch failed for %s: %s", ticker, exc)
        return f"DATA_UNAVAILABLE: LHB fetch failed ({exc}). Proceed without it."


def get_northbound_flow(curr_date: str = None, look_back_days: int = 10) -> str:
    """Northbound (北向资金) flow: HK->A net buying, the closest A-share
    analogue to institutional money flow. Recent history + latest day summary."""
    logger.debug("get_northbound_flow called for curr_date=%s look_back_days=%s", curr_date, look_back_days)
    try:
        import akshare as ak

        hist = _ak_retry(lambda: ak.stock_hsgt_hist_em(symbol="北向资金"))
        if hist is None or hist.empty:
            return "DATA_UNAVAILABLE: no northbound history returned."
        end_dt = pd.Timestamp(curr_date or datetime.now())
        start_dt = end_dt - pd.Timedelta(days=int(look_back_days))
        hist = hist.copy()
        hist["日期"] = pd.to_datetime(hist["日期"], errors="coerce")
        recent = hist[(hist["日期"] >= start_dt) & (hist["日期"] <= end_dt)].sort_values("日期")

        summary = _ak_retry(lambda: ak.stock_hsgt_fund_flow_summary_em())
        summary_block = ""
        if summary is not None and not summary.empty:
            keep = [c for c in summary.columns if c in (
                "板块", "资金方向", "成交净买额", "资金净流入", "相关指数", "指数涨跌幅",
            )]
            summary_block = (
                "## Latest day summary (Northbound):\n" + summary[keep].to_csv(index=False) + "\n"
            )

        return (
            f"## Northbound (北向资金) flow, {start_dt:%Y-%m-%d} to {end_dt:%Y-%m-%d} (akshare/Eastmoney)\n"
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            + summary_block
            + "## Recent net buying (成交净买额, 亿元):\n"
            + recent.tail(10).to_csv(index=False)
        )
    except Exception as exc:  # noqa: BLE001
        return f"DATA_UNAVAILABLE: northbound flow fetch failed ({exc}). Proceed without it."


def get_limit_up_context(ticker: str, curr_date: str = None) -> str:
    """Limit-up board (涨停池) context: is the ticker limit-up today, and
    what does the breadth of the limit-up board say about market sentiment."""
    logger.debug("get_limit_up_context called for %s curr_date=%s", ticker, curr_date)
    code = _ashare_code(ticker)
    if code is None:
        logger.warning("limit-up context requested for non-A-share ticker %s", ticker)
        return f"Limit-up context unavailable for '{ticker}' via akshare (A-share only)."
    try:
        import akshare as ak

        date_str = (pd.Timestamp(curr_date or datetime.now())).strftime("%Y%m%d")
        df = _ak_retry(lambda: ak.stock_zt_pool_em(date=date_str))
        if df is None or df.empty:
            logger.warning("akshare limit-up board empty for %s on %s", ticker, date_str)
            return f"No limit-up board data for {date_str} (weekend/holiday or no data)."

        row = df[df["代码"].astype(str) == code]
        out = [
            f"# Limit-up board (涨停池) context for {ticker} on {date_str} (akshare/Eastmoney)",
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            f"Total limit-up stocks today: {len(df)}",
        ]
        if not row.empty:
            r = row.iloc[0]
            out.append(
                f"THIS TICKER IS LIMIT-UP: 名称={r.get('名称')}, 涨跌幅={r.get('涨跌幅'):.2f}%, "
                f"连板数={r.get('连板数')}, 封板资金={r.get('封板资金'):,.0f}, "
                f"所属行业={r.get('所属行业')}, 换手率={r.get('换手率'):.2f}%"
            )
        else:
            out.append(f"'{ticker}' is NOT on today's limit-up board.")

        # Breadth signal: sector distribution of limit-ups + top streak.
        if "所属行业" in df.columns:
            dist = df["所属行业"].value_counts().head(5)
            out.append("\nTop sectors on the limit-up board:\n" + dist.to_string())
        if "连板数" in df.columns and len(df):
            top = df.sort_values("连板数", ascending=False).head(3)
            out.append("\nHighest streak today:\n" + top[["代码", "名称", "连板数", "所属行业"]].to_csv(index=False))
        logger.debug("limit-up board returned %d rows for %s on %s", len(df), ticker, date_str)
        return "\n".join(out)
    except Exception as exc:  # noqa: BLE001
        logger.warning("akshare limit-up board fetch failed for %s on %s: %s", ticker, date_str, exc)
        return f"DATA_UNAVAILABLE: limit-up board fetch failed ({exc}). Proceed without it."


def get_sector_context(ticker: str, curr_date: str = None) -> str:
    """Sector/industry breadth: today's best/worst Sina industry sectors and
    their leader stocks — market context for a single-stock decision."""
    logger.debug("get_sector_context called for %s curr_date=%s", ticker, curr_date)
    try:
        import akshare as ak

        df = _ak_retry(lambda: ak.stock_sector_spot(indicator="新浪行业"))
        if df is None or df.empty:
            logger.warning("akshare sector spot returned no data for %s", ticker)
            return "DATA_UNAVAILABLE: no sector spot data returned."
        df = df.copy()
        df["涨跌幅"] = pd.to_numeric(df["涨跌幅"], errors="coerce")
        df = df.dropna(subset=["涨跌幅"]).sort_values("涨跌幅", ascending=False)

        leader_cols = ["板块", "涨跌幅", "股票名称", "股票代码", "个股-涨跌幅", "个股-当前价"]
        top = df.head(5)[leader_cols].to_csv(index=False)
        bottom = df.tail(5)[leader_cols].to_csv(index=False)

        # Is the ticker a sector leader today?
        market, symbol = _to_akshare_symbol(ticker)
        leader_hit = ""
        if market == "ashare" and "股票代码" in df.columns:
            row = df[df["股票代码"].astype(str) == symbol]
            if not row.empty:
                r = row.iloc[0]
                leader_hit = (
                    f"\n{ticker} IS the leader stock of sector '{r['板块']}' "
                    f"(sector {r['涨跌幅']:+.2f}%, stock {r['个股-涨跌幅']:+.2f}%).\n"
                )

        stamp = (pd.Timestamp(curr_date) if curr_date else pd.Timestamp.now()).strftime("%Y-%m-%d")
        logger.debug("sector spot returned %d sectors for %s", len(df), ticker)
        return (
            f"## Sector breadth (Sina industry sectors) on {stamp} "
            f"(akshare)\n# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"### Top 5 sectors today:\n{top}\n### Bottom 5 sectors today:\n{bottom}"
            + leader_hit
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("akshare sector context fetch failed for %s: %s", ticker, exc)
        return f"DATA_UNAVAILABLE: sector context fetch failed ({exc}). Proceed without it."


def _recent_report_periods(curr_date: str) -> list[str]:
    """Two most recent quarterly report-period ends (YYYYMMDD) at/before curr_date."""
    dt = pd.Timestamp(curr_date)
    periods = [
        pd.Timestamp(y, m, d)
        for y in range(dt.year - 1, dt.year + 1)
        for m, d in ((3, 31), (6, 30), (9, 30), (12, 31))
    ]
    recent = sorted([p for p in periods if p <= dt], reverse=True)[:2]
    return [p.strftime("%Y%m%d") for p in recent]


def get_earnings_forecast(ticker: str, curr_date: str = None) -> str:
    """Earnings forecasts (业绩预告): the company's own guidance for the
    most recent reporting window — a leading signal that hits before the
    actual financial statements."""
    logger.debug("get_earnings_forecast called for %s curr_date=%s", ticker, curr_date)
    code = _ashare_code(ticker)
    if code is None:
        logger.warning("earnings forecast requested for non-A-share ticker %s", ticker)
        return f"Earnings forecast unavailable for '{ticker}' via akshare (A-share only)."
    try:
        import akshare as ak

        periods = _recent_report_periods(curr_date or datetime.now().strftime("%Y-%m-%d"))
        hits = []
        for period in periods:
            df = _ak_retry(lambda p=period: ak.stock_yjyg_em(date=p))
            if df is None or df.empty:
                continue
            rows = df[df["股票代码"].astype(str) == code]
            if rows.empty:
                continue
            keep = [c for c in rows.columns if c in (
                "股票简称", "预测指标", "业绩变动", "预测数值", "业绩变动幅度",
                "预告类型", "上年同期值", "公告日期",
            )]
            hits.append(f"## Forecast window {period}:\n" + rows[keep].to_csv(index=False))

        if not hits:
            logger.debug("no earnings forecast rows for %s in periods %s", ticker, periods)
            return (
                f"No earnings forecast (业绩预告) for '{ticker}' in the most recent "
                "reporting windows. Guidance is optional in A-shares; absence is normal."
            )
        logger.debug("earnings forecast returned %d windows for %s", len(hits), ticker)
        return (
            f"# Earnings forecasts for {ticker} (akshare/Eastmoney)\n"
            f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            + "\n".join(hits)
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("akshare earnings forecast fetch failed for %s: %s", ticker, exc)
        return f"DATA_UNAVAILABLE: earnings forecast fetch failed ({exc}). Proceed without it."


# ---------------------------------------------------------------------------
# Realized-return lookup for decision tracking / backtesting
#
# The graph resolves pending decisions into actual returns (raw + alpha vs a
# benchmark) so every decision is eventually scored. Yahoo is unreachable from
# this network, so the lookup uses akshare: stocks via Sina daily, and the
# framework's benchmark tickers (000001.SS / 399001.SZ / SPY ...) via the
# matching index/US series.
# ---------------------------------------------------------------------------

# Framework benchmark ticker -> akshare series.
# A-share: indices (000001.SS is the SSE Composite index, NOT the stock).
# US: ETF/index pass through to the US daily series.
_BENCHMARK_TO_AKSHARE: dict[str, str] = {
    "000001.SS": "sh000001",    # SSE Composite
    "399001.SZ": "sz399001",    # SZSE Component
    "399006.SZ": "sz399006",    # ChiNext
    "000300.SS": "sh000300",    # CSI 300
    "000905.SS": "sh000905",    # CSI 500
    "SPY": "SPY",
    "QQQ": "QQQ",
    "^GSPC": "SPX",
}
_INDEX_SYMBOLS = {"sh000001", "sz399001", "sz399006", "sh000300", "sh000905"}


def _download_index_daily(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Sina index daily (sh000001 / sz399001 ...), clipped to the window."""
    logger.debug("_download_index_daily called for %s %s..%s", symbol, start_date, end_date)
    import akshare as ak

    df = _ak_retry(lambda: ak.stock_zh_index_daily(symbol=symbol))
    if df is None or df.empty:
        logger.warning("akshare index %s returned no rows", symbol)
        raise NoMarketDataError(symbol, symbol, "index returned no rows")
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")
    start_dt = pd.Timestamp(start_date)
    end_dt = pd.Timestamp(end_date)
    df = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)]
    if df.empty:
        logger.warning("akshare index %s has no rows in %s..%s", symbol, start_date, end_date)
        raise NoMarketDataError(symbol, symbol, f"index has no rows in {start_date}..{end_date}")
    logger.debug("index daily returned %d rows for %s", len(df), symbol)
    return df


def get_market_returns(
    ticker: str,
    trade_date: str,
    holding_days: int = 5,
    benchmark: str = "SPY",
) -> tuple[float | None, float | None, int | None]:
    """Realized raw + alpha returns for ``ticker`` over ``holding_days`` from
    ``trade_date``, benchmarked against ``benchmark`` (akshare/Sina).

    Returns ``(raw_return, alpha_return, actual_holding_days)`` or
    ``(None, None, None)`` when price data is unavailable. Never raises:
    callers use None to mean "not yet resolvable".
    """
    logger.debug(
        "get_market_returns called for %s trade_date=%s holding_days=%d benchmark=%s",
        ticker, trade_date, holding_days, benchmark,
    )
    try:
        end_date = (pd.Timestamp(trade_date) + pd.Timedelta(days=holding_days + 7)).strftime("%Y-%m-%d")

        stock_df = _download_daily(ticker, trade_date, end_date)
        bench_symbol = _BENCHMARK_TO_AKSHARE.get(str(benchmark).upper(), str(benchmark).upper())
        if bench_symbol in _INDEX_SYMBOLS:
            bench_df = _download_index_daily(bench_symbol, trade_date, end_date)
        else:
            bench_df = _download_daily(bench_symbol, trade_date, end_date)

        def _closes(df: pd.DataFrame) -> list[float]:
            col = "close" if "close" in df.columns else "Close"
            return [float(x) for x in df[col].tolist()]

        stock_closes = _closes(stock_df)
        bench_closes = _closes(bench_df)
        if len(stock_closes) < 2 or len(bench_closes) < 2:
            return None, None, None

        actual_days = min(holding_days, len(stock_closes) - 1, len(bench_closes) - 1)
        raw = (stock_closes[actual_days] - stock_closes[0]) / stock_closes[0]
        bench_ret = (bench_closes[actual_days] - bench_closes[0]) / bench_closes[0]
        logger.debug(
            "realized return computed for %s @ %s: raw=%.4f alpha=%.4f days=%d",
            ticker, trade_date, raw, raw - bench_ret, actual_days,
        )
        return raw, raw - bench_ret, actual_days
    except Exception as exc:  # noqa: BLE001 — resolution failure is not fatal
        logger.warning("akshare realized-return lookup failed for %s @ %s: %s", ticker, trade_date, exc)
        return None, None, None
