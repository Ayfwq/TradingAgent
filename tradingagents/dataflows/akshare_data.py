"""面向中国大陆网络环境的 akshare 数据供应商。

akshare 背后的数据源（均可在中国大陆访问，无需 Yahoo Finance）：
  - 新浪财经：A 股 / 美股 / 港股日 OHLCV、财务指标；
  - 东方财富：按股票代码查询新闻（使用 search-api 域名，而非被阻断的
    push2his K 线域名）和实时行情；
  - 金十：宏观序列（CPI、GDP、LPR、M2 等）。

设计规则（与 yfinance 供应商保持一致）：
  - 函数要么返回格式化字符串，要么抛出类型化的 ``NoMarketDataError``，
    让路由器输出明确的不可用信号；不会抛出导致图崩溃的通用异常；
  - OHLCV 使用框架其余部分期望的相同大写列名
    （``Date/Open/High/Low/Close/Volume``）返回；
  - 代码处理：A 股 ``600519.SS`` -> ``sh600519``，``000001.SZ`` ->
    ``sz000001``，美股 ``NVDA`` 保持不变，港股 ``0700.HK`` -> ``00700``。
    不支持的标的抛出 ``NoMarketDataError``。
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
# 线程安全。
#
# 新浪日线接口（stock_zh_a_daily / stock_zh_index_daily / stock_us_daily /
# stock_hk_daily）使用 py_mini_racer 解密数据。它所使用的 V8 引擎不是线程安全的：
# 两次并发调用会使整个进程崩溃（FATAL: partition_address_space.cc），且无法捕获。
# 分析师会并发运行工具，因此所有 akshare 调用都通过可重入锁串行化。
# LLM 调用（主要耗时部分）仍保持并行，只有快速的数据获取会串行。
# ---------------------------------------------------------------------------
_AK_LOCK = threading.RLock()

# ---------------------------------------------------------------------------
# 代码映射。
# ---------------------------------------------------------------------------


def _to_akshare_symbol(ticker: str) -> tuple[str, str]:
    """将框架股票代码映射为（市场、akshare 代码）。

    markets：``ashare`` | ``us`` | ``hk`` | None（不支持）。
    """
    if not isinstance(ticker, str) or not ticker.strip():
        return None, ""
    raw = ticker.strip().upper()

    # A 股：带交易所后缀（600519.SS / 000001.SZ / 430047.BJ）或不带后缀的 6 位代码。
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

    # 港股：0700.HK -> 00700（补齐为 5 位）。
    if raw.endswith(".HK") and raw[: -3].isdigit():
        digits = raw[: -3]
        return "hk", digits.zfill(5)

    # 美股/普通代码直接透传（NVDA、AAPL、BRK.B、^GSPC 等）。
    if _is_plain_us_symbol(raw):
        return "us", raw

    return None, raw


def _is_plain_us_symbol(raw: str) -> bool:
    """接受字母、数字、点号、脱字符和等号，只要不是明显带交易所后缀或数字型的中国标的。"""
    if not raw or raw[0].isdigit():
        return False
    if any(raw.endswith(s) for s in (".SS", ".SH", ".SZ", ".BJ", ".HK", ".T", ".L", ".TO", ".AX", ".NS", ".BO")):
        return False
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-^=: ")
    return all(c in allowed for c in raw)


# ---------------------------------------------------------------------------
# OHLCV 辅助函数。
# ---------------------------------------------------------------------------


def _download_daily(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """通过 akshare（新浪）下载指定代码的日 OHLCV 数据。

    返回包含新浪小写列（date/open/high/low/close/volume）的 DataFrame，按日期排序；
    数据源支持时已裁剪到 [start_date, end_date]。

    代码不支持或结果为空时抛出 NoMarketDataError。
    """
    import akshare as ak

    market, symbol = _to_akshare_symbol(ticker)
    if market is None:
        logger.warning("akshare 供应商不支持该市场：%s", ticker)
        raise NoMarketDataError(ticker, ticker, "akshare 供应商不支持该市场")
    try:
        if market == "us":
            # 新浪美股日线返回完整历史，在客户端过滤。
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
        # 约定：供应商只暴露一个类型化信号（NoMarketDataError），让路由器输出
        # 明确的“不可用”，避免原始通用异常泄漏到图中。
        logger.warning("下载 %s（%s）的 akshare 数据失败：%s", ticker, symbol, exc)
        raise NoMarketDataError(ticker, symbol, f"akshare 下载失败：{exc}") from exc

    if df is None or df.empty:
        logger.warning("akshare 未返回 %s（%s）的数据行", ticker, symbol)
        raise NoMarketDataError(ticker, symbol, "akshare 未返回数据行")

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")

    if market in ("us", "hk"):
        start_dt = pd.Timestamp(start_date)
        end_dt = pd.Timestamp(end_date)
        df = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)]

    if df.empty:
        logger.warning("akshare 在 %s 至 %s 期间未返回 %s 的数据行", start_date, end_date, ticker)
        raise NoMarketDataError(ticker, symbol, f"{start_date} 至 {end_date} 期间没有数据行")
    logger.debug("akshare 为 %s（%s）返回 %d 行", ticker, symbol, len(df))
    return df


def _ak_retry(func, max_retries=2, base_delay=1.0):
    """akshare 调用的轻量重试包装器（网络抖动很常见）。

    通过 ``_AK_LOCK`` 串行化：akshare 的新浪接口使用 py_mini_racer V8 引擎，
    并发使用会导致进程崩溃。
    """
    with _AK_LOCK:
        last = None
        for attempt in range(max_retries + 1):
            try:
                return func()
            except Exception as exc:  # noqa: BLE001 — akshare 会抛出多种非标准异常类型。
                last = exc
                if attempt < max_retries:
                    logger.debug("第 %d 次 akshare 调用失败，将重试：%s", attempt + 1, exc)
                    time.sleep(base_delay * (attempt + 1))
        raise last


def _to_capitalized_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """将 akshare 的小写日线数据框转换为框架格式。

    输出列：``Date``（datetime）、``Open/High/Low/Close/Volume``。
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
    """通过 akshare 获取截至今天的 5 年 OHLCV 窗口，与
    ``stockstats_utils.load_ohlcv`` 使用 yfinance 的方式一致，使指标和市场数据
    校验器可以使用同一缓存约定。

    返回包含大写列 ``Date/Open/High/Low/Close/Volume`` 的 DataFrame，仅保留
    ``curr_date`` 当日及之前的行。没有可用数据时抛出 NoMarketDataError。
    """
    today = pd.Timestamp.today()
    start_str = (today - pd.DateOffset(years=5)).strftime("%Y-%m-%d")
    end_str = (today + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    logger.debug("已调用 load_ohlcv_akshare：%s，curr_date=%s", symbol, curr_date)
    df = _download_daily(symbol, start_str, end_str)
    out = _to_capitalized_ohlcv(df)
    if out.empty:
        logger.warning("akshare 未返回 %s 的 OHLCV 数据行", symbol)
        raise NoMarketDataError(symbol, symbol, "akshare 未返回 OHLCV 数据行")

    cutoff = pd.Timestamp(curr_date)
    out = out[out["Date"] <= cutoff].sort_values("Date")
    if out.empty:
        logger.warning("akshare 未返回 %s 在 %s 当日及之前的数据行", symbol, curr_date)
        raise NoMarketDataError(
            symbol, symbol, f"no rows on or before {curr_date}"
        )
    logger.debug("akshare 为 %s 返回 %d 行 OHLCV 数据", symbol, len(out))
    return out.reset_index(drop=True)


def get_stock_data_akshare(
    symbol: str,
    start_date: str,
    end_date: str,
) -> str:
    """以 CSV 字符串（表头 + 数据行）返回 OHLCV，格式与 yfinance 供应商一致，
    使 Agent 提示词和下游解析保持不变。"""
    logger.debug("已调用 get_stock_data_akshare：%s（%s 至 %s）", symbol, start_date, end_date)
    try:
        df = _download_daily(symbol, start_date, end_date)
        market, canonical = _to_akshare_symbol(symbol)
        csv_string = _to_capitalized_ohlcv(df).to_csv(index=False)
        label = canonical if canonical != symbol.upper() else symbol.upper()
        header = f"# {label} 的股票数据（akshare/{market}），日期范围 {start_date} 至 {end_date}\n"
        header += f"# 记录总数：{len(df)}\n"
        header += f"# 数据获取时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        logger.debug("akshare 为 %s 返回 %d 行数据", symbol, len(df))
        return header + csv_string
    except NoMarketDataError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("获取 %s 的 akshare 股票数据失败：%s", symbol, exc)
        raise NoMarketDataError(symbol, symbol, f"akshare 错误：{exc}") from exc


# ---------------------------------------------------------------------------
# 基本面数据（新浪）。
# ---------------------------------------------------------------------------


def _strip_ashare_suffix(ticker: str) -> str:
    """600519.SS -> 600519；非 A 股代码返回 None。"""
    market, symbol = _to_akshare_symbol(ticker)
    if market != "ashare":
        return None
    return symbol[2:] if symbol[:2] in ("sh", "sz", "bj") else symbol


def _filter_financial_frame_by_date(df: pd.DataFrame, curr_date: str | None) -> pd.DataFrame:
    """过滤报告日期，避免基本面数据在回测中泄漏未来信息。

    东方财富的 A/H/US 接口使用的日期列名称并不完全一致；这个小的适配层
    统一处理常见列名，同时保留无法解析的供应商数据（供应商有时会把报告期
    编码放在非日期列中）。
    """
    if df is None or df.empty or not curr_date:
        return df
    cutoff = pd.Timestamp(curr_date)
    for name in ("REPORT_DATE", "STD_REPORT_DATE", "报告日期", "报告期", "公告日期"):
        if name not in df.columns:
            continue
        parsed = pd.to_datetime(df[name], errors="coerce")
        if parsed.notna().any():
            return df.loc[parsed <= cutoff].copy()
    return df


def _render_financial_frame(
    ticker: str,
    frame: pd.DataFrame,
    title: str,
    source: str,
    curr_date: str | None = None,
    max_rows: int = 80,
) -> str:
    """将 akshare 财务 DataFrame 渲染成工具统一使用的 CSV 文本。"""
    if frame is None or frame.empty:
        raise NoMarketDataError(ticker, ticker, f"未返回{title}数据")
    frame = _filter_financial_frame_by_date(frame, curr_date)
    if frame.empty:
        raise NoMarketDataError(ticker, ticker, f"截至 {curr_date} 未返回{title}数据")
    recent = frame.head(max_rows)
    header = f"# {ticker} 的{title}（akshare/{source}）\n"
    header += f"# 数据获取时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    return header + recent.to_csv(index=False)


def get_fundamentals_akshare(ticker: str, curr_date: str = None) -> str:
    """从 akshare 获取公司基本面概览，覆盖 A 股、港股和美股。

    A 股沿用新浪财务指标；港股/美股使用东方财富 F10 主要指标接口。这样
    在无法访问 Yahoo 的环境中，AAPL、0700.HK 等代码仍有国内可用数据源。
    """
    logger.debug("已调用 get_fundamentals_akshare：%s，curr_date=%s", ticker, curr_date)
    market, code = _to_akshare_symbol(ticker)
    if market is None:
        return (
            f"通过 akshare 无法获取 '{ticker}' 的基本面数据（不支持的市场代码）。"
            "请继续分析其他数据。"
        )
    try:
        import akshare as ak

        if market == "ashare":
            start_year = str(max(2020, int(pd.Timestamp(curr_date or datetime.now()).year) - 3))
            df = _ak_retry(
                lambda: ak.stock_financial_analysis_indicator(
                    symbol=code[2:], start_year=start_year
                )
            )
            result = _render_financial_frame(ticker, df, "公司基本面", "新浪", curr_date, 8)
        elif market == "hk":
            df = _ak_retry(
                lambda: ak.stock_financial_hk_analysis_indicator_em(
                    symbol=code, indicator="报告期"
                )
            )
            result = _render_financial_frame(ticker, df, "公司基本面", "东方财富港股", curr_date, 12)
        else:  # us
            # 东方财富对 BRK.B / BRK-B 等类别股代码使用 BRK_B；普通美股
            # 代码保持原样。Yahoo 常见的连字符格式和东方财富的下划线格式
            # 在这里统一，避免类别股被误判为“无数据”。
            em_code = code.replace(".", "_").replace("-", "_")
            df = _ak_retry(
                lambda: ak.stock_financial_us_analysis_indicator_em(
                    symbol=em_code, indicator="年报"
                )
            )
            result = _render_financial_frame(ticker, df, "公司基本面", "东方财富美股", curr_date, 8)

        logger.debug("akshare 为 %s 返回基本面数据", ticker)
        return result
    except NoMarketDataError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("获取 %s 的 akshare 基本面数据失败：%s", ticker, exc)
        return f"通过 akshare 获取 {ticker} 的基本面失败：{exc}"


def _financial_abstract_report(
    ticker: str,
    curr_date: str | None,
    section: str,
    freq: str = "quarterly",
) -> str:
    """将 A/H/US 财务报表 DataFrame 渲染为统一报告。

    A 股使用新浪摘要表，港股/美股使用东方财富三大报表接口；``section``
    仅用于选择报表类型和标记报告。
    """
    logger.debug("_financial_abstract_report called for %s section=%s curr_date=%s", ticker, section, curr_date)
    market, code = _to_akshare_symbol(ticker)
    if market is None:
        return (
            f"通过 akshare 无法获取 '{ticker}' 的{section}（不支持的市场代码）。"
            "请继续分析其他数据。"
        )
    try:
        import akshare as ak

        if market == "ashare":
            df = _ak_retry(lambda: ak.stock_financial_abstract(symbol=code[2:]))

            if df is None or df.empty:
                logger.warning("akshare 未返回 %s 的 %s 数据（%s）", ticker, section, code)
                raise NoMarketDataError(ticker, code, "未返回财务摘要")

            # A 股摘要把报告期作为列名（例如 20251231），保留 curr_date 及之前
            # 的日期以防止前视，并按最新在前排序。
            period_cols = [c for c in df.columns if str(c).isdigit()]
            if curr_date:
                cutoff = pd.Timestamp(curr_date)
                period_cols = [c for c in period_cols if pd.Timestamp(str(c)) <= cutoff]
            period_cols = sorted(period_cols, reverse=True)[:4]
            keep = [c for c in df.columns if c not in period_cols] + period_cols
            table = df[keep].head(60)
            header = f"# {code[2:]} 的{section}数据（akshare/新浪，A 股）\n"
            header += f"# 数据获取时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            return header + table.to_csv(index=False)

        report_names = {
            "Balance Sheet": "资产负债表",
            "Cash Flow": "现金流量表",
            "Income Statement": "利润表" if market == "hk" else "综合损益表",
        }
        report_name = report_names[section]
        if market == "hk":
            indicator = "报告期" if str(freq).lower() == "quarterly" else "年度"
            df = _ak_retry(
                lambda: ak.stock_financial_hk_report_em(
                    stock=code, symbol=report_name, indicator=indicator
                )
            )
            source = "东方财富港股"
        else:  # us
            indicator = "单季报" if str(freq).lower() == "quarterly" else "年报"
            df = _ak_retry(
                lambda: ak.stock_financial_us_report_em(
                    stock=code.replace(".", "_").replace("-", "_"),
                    symbol=report_name,
                    indicator=indicator,
                )
            )
            source = "东方财富美股"

        return _render_financial_frame(ticker, df, section, source, curr_date, 100)
    except NoMarketDataError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("获取 %s 的 akshare %s 数据失败：%s", ticker, section, exc)
        return f"通过 akshare 获取 {ticker} 的{section}失败：{exc}"


def get_balance_sheet_akshare(ticker: str, freq: str = "quarterly", curr_date: str = None) -> str:
    return _financial_abstract_report(ticker, curr_date, "Balance Sheet", freq)


def get_cashflow_akshare(ticker: str, freq: str = "quarterly", curr_date: str = None) -> str:
    return _financial_abstract_report(ticker, curr_date, "Cash Flow", freq)


def get_income_statement_akshare(ticker: str, freq: str = "quarterly", curr_date: str = None) -> str:
    return _financial_abstract_report(ticker, curr_date, "Income Statement", freq)


# ---------------------------------------------------------------------------
# 新闻。
# ---------------------------------------------------------------------------


def get_news_akshare(ticker: str, start_date: str, end_date: str) -> str:
    """通过东方财富搜索 API（中国大陆可访问）获取指定股票新闻。

    东方财富搜索接口本身不限制 A 股；将规范化后的 A/HK/US 代码作为
    关键词查询，因此在 Yahoo 不可达时，三类市场都可以使用同一个国内
    新闻源。A 股去掉 ``sh/sz/bj`` 前缀，港股使用五位代码，美股保留
    ticker（例如 ``AAPL``）。
    """
    logger.debug("已调用 get_news_akshare：%s（%s 至 %s）", ticker, start_date, end_date)
    market, code = _to_akshare_symbol(ticker)
    if market is None:
        return (
            f"通过 akshare 未找到 {ticker} 的新闻（不支持的市场代码）。"
        )
    search_code = code[2:] if market == "ashare" else code
    try:
        import akshare as ak

        limit = get_config()["news_article_limit"]
        df = _ak_retry(lambda: ak.stock_news_em(symbol=search_code))
        if df is None or df.empty:
            logger.warning("akshare 未返回 %s 的新闻（%s）", ticker, search_code)
            return f"未找到 {ticker} 的新闻。"

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
            news_str += f"### {title}（来源：{source or '未知'}）\n"
            if content:
                news_str += f"{content[:400]}\n"
            if link:
                news_str += f"链接：{link}\n"
            news_str += "\n"
            kept += 1
            if kept >= limit:
                break

        if kept == 0:
            logger.warning("akshare 在 %s..%s 内没有 %s 的新闻", start_date, end_date, ticker)
            return f"在 {start_date} 至 {end_date} 期间未找到 {ticker} 的新闻。"
        logger.debug("akshare 为 %s 返回 %d 篇新闻", ticker, kept)
        return f"## {ticker} 的新闻（{start_date} 至 {end_date}）：\n\n{news_str}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("获取 %s 的 akshare 新闻失败：%s", ticker, exc)
        return f"通过 akshare 获取 {ticker} 的新闻失败：{exc}"


def get_global_news_akshare(
    curr_date: str,
    look_back_days: int | None = None,
    limit: int | None = None,
) -> str:
    """通过新浪 7x24 快讯（中国大陆稳定可访问）获取全球宏观新闻。"""
    logger.debug("已调用 get_global_news_akshare：%s，look_back_days=%s，limit=%s", curr_date, look_back_days, limit)
    config = get_config()
    if look_back_days is None:
        look_back_days = config["global_news_lookback_days"]
    if limit is None:
        limit = config["global_news_article_limit"]
    try:
        import akshare as ak

        df = _ak_retry(lambda: ak.stock_info_global_sina())
        if df is None or df.empty:
            logger.warning("akshare 未返回 %s 的全球新闻", curr_date)
            return f"未找到 {curr_date} 的全球新闻。"

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
            logger.warning("akshare 在 %s..%s 内没有全球新闻", start_dt, curr_date)
            return f"在 {start_dt:%Y-%m-%d} 至 {curr_date} 期间未找到全球新闻。"
        logger.debug("akshare 为 %s 返回 %d 篇全球新闻", curr_date, kept)
        return f"## 全球市场新闻（{start_dt:%Y-%m-%d} 至 {curr_date}）：\n\n{news_str}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("获取 %s 的 akshare 全球新闻失败：%s", curr_date, exc)
        return f"通过 akshare 获取全球新闻失败：{exc}"


def get_insider_transactions_akshare(ticker: str) -> str:
    """通过雪球内幕交易数据流获取 A 股董监高交易记录。

    数据流覆盖整个市场；这里只保留请求股票代码最近 90 天的数据。
    ``600519.SS`` / ``000001.SZ`` 等代码会映射为雪球的 ``SH600519`` /
    ``SZ000001`` 格式。
    """
    logger.debug("已调用 get_insider_transactions_akshare：%s", ticker)
    code = _strip_ashare_suffix(ticker)
    if code is None:
        return (
            f"通过 akshare 无法获取 '{ticker}' 的内幕交易数据（仅支持 A 股）。"
            "请继续分析其他数据。"
        )
    try:
        import akshare as ak

        # 雪球代码格式：SH600519 / SZ000001 / BJ……
        if code.startswith(("60", "68", "90")):
            xq_code = "SH" + code
        elif code.startswith(("00", "30", "20")):
            xq_code = "SZ" + code
        else:
            xq_code = "BJ" + code

        df = _ak_retry(lambda: ak.stock_inner_trade_xq())
        if df is None or df.empty:
            return f"股票代码 '{ticker}' 没有内幕交易记录。"

        df = df.copy()
        df["变动日期"] = pd.to_datetime(df["变动日期"], errors="coerce")
        df = df.dropna(subset=["变动日期"])

        match = df[df["股票代码"] == xq_code]
        if match.empty:
            return f"股票代码 '{ticker}' 没有内幕交易记录。"

        # 最近 90 天，最新记录在前。
        cutoff = pd.Timestamp.today() - pd.Timedelta(days=90)
        match = match[match["变动日期"] >= cutoff].sort_values("变动日期", ascending=False)

        header = f"# {ticker} 的内幕交易数据（akshare/雪球，A 股）\n"
        header += f"# 数据获取时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        if match.empty:
            logger.debug("最近 90 天内没有 %s 的 akshare 内部人交易数据", ticker)
            return header + f"'{ticker}' 最近 90 天没有内幕交易记录。"
        logger.debug("akshare 为 %s 返回 %d 行内部人交易数据", ticker, len(match))
        return header + match.head(30).to_csv(index=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("获取 %s 的 akshare 内部人交易数据失败：%s", ticker, exc)
        return f"通过 akshare 获取 {ticker} 的内幕交易失败：{exc}"


# ---------------------------------------------------------------------------
# 宏观数据（金十 / akshare 宏观序列）。
# ---------------------------------------------------------------------------

# 友好别名 ->（akshare 函数名、显示标签）。
_MACRO_SERIES = {
    "cpi": ("macro_china_cpi_yearly", "中国 CPI（年度，%）"),
    "gdp": ("macro_china_gdp_yearly", "中国 GDP（年度，%）"),
    "real_gdp": ("macro_china_gdp_yearly", "中国 GDP（年度，%）"),
    "m2": ("macro_china_m2_yearly", "中国 M2 货币供应量（年度）"),
    "pmi": ("macro_china_pmi_yearly", "中国 PMI（年度）"),
    "lpr": ("macro_china_lpr", "中国 LPR 贷款市场报价利率"),
    "loan_rate": ("macro_china_lpr", "中国 LPR 贷款市场报价利率"),
    "unemployment": ("macro_china_urban_unemployment", "中国城镇调查失业率"),
}


def get_macro_indicators_akshare(
    indicator: str,
    curr_date: str,
    look_back_days: int | None = None,
) -> str:
    """通过 akshare 获取中国宏观序列（金十/国家统计局）。"""
    key = (indicator or "").strip().lower()
    if key not in _MACRO_SERIES:
        return (
            f"DATA_UNAVAILABLE: akshare 供应商不支持宏观指标 '{indicator}'。"
            f"支持的指标：{sorted(_MACRO_SERIES)}。"
        )
    func_name, label = _MACRO_SERIES[key]
    logger.debug("已调用 get_macro_indicators_akshare：%s，curr_date=%s", indicator, curr_date)
    try:
        import akshare as ak

        func = getattr(ak, func_name)
        df = _ak_retry(func)
        if df is None or df.empty:
            logger.warning("akshare 未返回 %s 数据", label)
            return f"DATA_UNAVAILABLE: 未返回 {label} 数据。"

        # 输出最近观测值，最新在前。
        df = df.copy()
        date_col = next((c for c in ("日期", "TRADE_DATE") if c in df.columns), None)
        if date_col is not None:
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
            df = df.dropna(subset=[date_col]).sort_values(date_col, ascending=False)
        head = df.head(12).to_csv(index=False)
        logger.debug("akshare 返回 %d 行 %s 数据", len(head.splitlines()) - 1, label)
        return f"## {label}（akshare）\n\n{head}"
    except Exception as exc:  # noqa: BLE001
        logger.warning("获取 %s 的 akshare 宏观数据失败：%s", indicator, exc)
        return f"DATA_UNAVAILABLE: akshare 宏观数据获取失败（{exc}）。"


# ---------------------------------------------------------------------------
# A 股专项上下文工具（龙虎榜 / 北向资金 / 涨停池 / 行业板块 / 业绩预告）。
#
# 这些工具为核心分析师补充美股市场没有对应物的 A 股特有信号。每个函数都会降级
# 为简短字符串（不会崩溃）：股票没有记录本身就是有效答案（“今天不在涨停池”），
# 网络失败则返回 DATA_UNAVAILABLE，让 Agent 可以在缺少这些特色数据时继续运行。
# ---------------------------------------------------------------------------


def _ashare_code(ticker: str) -> str | None:
    """返回 6 位 A 股代码（600519），非 A 股代码返回 None。"""
    market, symbol = _to_akshare_symbol(ticker)
    if market != "ashare":
        return None
    return symbol[2:] if symbol[:2] in ("sh", "sz", "bj") else symbol


def get_lhb_context(ticker: str, curr_date: str = None, look_back_days: int = 10) -> str:
    """返回股票在龙虎榜上的记录。

    展示异常波动期间的机构/席位活动、净买入、上榜原因以及上榜后 1/2/5 日收益，
    是直接的 A 股情绪/资金流信号。
    """
    logger.debug("已调用 get_lhb_context：%s，curr_date=%s，look_back_days=%s", ticker, curr_date, look_back_days)
    code = _ashare_code(ticker)
    if code is None:
        return f"通过 akshare 无法获取 '{ticker}' 的龙虎榜上下文（仅支持 A 股）。"
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
            return f"'{ticker}' 最近 {look_back_days} 天没有龙虎榜记录。"
        rows = df[df["代码"].astype(str) == code]
        if rows.empty:
            return (
                f"'{ticker}' 最近 {look_back_days} 天没有龙虎榜记录。"
                "大多数股票不在榜单中属于正常情况。"
            )
        keep = [c for c in rows.columns if c in (
            "名称", "上榜日", "涨跌幅", "龙虎榜净买额", "龙虎榜买入额",
            "龙虎榜卖出额", "上榜原因", "上榜后1日", "上榜后2日", "上榜后5日",
        )]
        logger.debug("akshare 为 %s 返回 %d 行龙虎榜数据", ticker, len(rows))
        return (
            f"# {ticker} 的龙虎榜记录（最近 {look_back_days} 天，akshare/东方财富）\n"
            f"# 数据获取时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            + rows[keep].head(10).to_csv(index=False)
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("获取 %s 的 akshare 龙虎榜数据失败：%s", ticker, exc)
        return f"DATA_UNAVAILABLE: 龙虎榜数据获取失败（{exc}）。请继续分析其他数据。"


def get_northbound_flow(curr_date: str = None, look_back_days: int = 10) -> str:
    """北向资金流：港股通流入 A 股的净买入，是最接近机构资金流的 A 股指标。
    返回近期历史和最新交易日摘要。"""
    logger.debug("已调用 get_northbound_flow：curr_date=%s，look_back_days=%s", curr_date, look_back_days)
    try:
        import akshare as ak

        hist = _ak_retry(lambda: ak.stock_hsgt_hist_em(symbol="北向资金"))
        if hist is None or hist.empty:
            return "DATA_UNAVAILABLE: 未返回北向资金历史数据。"
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
                "## 最新交易日摘要（北向资金）：\n" + summary[keep].to_csv(index=False) + "\n"
            )

        return (
            f"## 北向资金流（{start_dt:%Y-%m-%d} 至 {end_dt:%Y-%m-%d}，akshare/东方财富）\n"
            f"# 数据获取时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            + summary_block
            + "## 近期成交净买额（亿元）：\n"
            + recent.tail(10).to_csv(index=False)
        )
    except Exception as exc:  # noqa: BLE001
        return f"DATA_UNAVAILABLE: 北向资金流获取失败（{exc}）。请继续分析其他数据。"


def get_limit_up_context(ticker: str, curr_date: str = None) -> str:
    """涨停池上下文：判断股票今天是否涨停，并分析涨停池广度反映的市场情绪。"""
    logger.debug("已调用 get_limit_up_context：%s，curr_date=%s", ticker, curr_date)
    code = _ashare_code(ticker)
    if code is None:
        logger.warning("为非 A 股代码 %s 请求涨停池上下文", ticker)
        return f"通过 akshare 无法获取 '{ticker}' 的涨停池上下文（仅支持 A 股）。"
    try:
        import akshare as ak

        date_str = (pd.Timestamp(curr_date or datetime.now())).strftime("%Y%m%d")
        df = _ak_retry(lambda: ak.stock_zt_pool_em(date=date_str))
        if df is None or df.empty:
            logger.warning("akshare 在 %s 未返回 %s 的涨停池数据", date_str, ticker)
            return f"{date_str} 没有涨停池数据（周末、节假日或无数据）。"

        row = df[df["代码"].astype(str) == code]
        out = [
            f"# {date_str} 的 {ticker} 涨停池上下文（akshare/东方财富）",
            f"# 数据获取时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            f"今日涨停股票总数：{len(df)}",
        ]
        if not row.empty:
            r = row.iloc[0]
            out.append(
                f"该股票今日涨停：名称={r.get('名称')}，涨跌幅={r.get('涨跌幅'):.2f}%，"
                f"连板数={r.get('连板数')}, 封板资金={r.get('封板资金'):,.0f}, "
                f"所属行业={r.get('所属行业')}, 换手率={r.get('换手率'):.2f}%"
            )
        else:
            out.append(f"'{ticker}' 今日不在涨停池中。")

        # 广度信号：涨停股票的行业分布和最高连板数。
        if "所属行业" in df.columns:
            dist = df["所属行业"].value_counts().head(5)
            out.append("\n涨停池中数量最多的行业：\n" + dist.to_string())
        if "连板数" in df.columns and len(df):
            top = df.sort_values("连板数", ascending=False).head(3)
            out.append("\n今日最高连板：\n" + top[["代码", "名称", "连板数", "所属行业"]].to_csv(index=False))
        logger.debug("涨停池为 %s 在 %s 返回 %d 行数据", ticker, date_str, len(df))
        return "\n".join(out)
    except Exception as exc:  # noqa: BLE001
        logger.warning("获取 %s 在 %s 的 akshare 涨停池数据失败：%s", ticker, date_str, exc)
        return f"DATA_UNAVAILABLE: 涨停池数据获取失败（{exc}）。请继续分析其他数据。"


def get_sector_context(ticker: str, curr_date: str = None) -> str:
    """行业广度：新浪行业板块今日表现最好/最差的行业及其龙头股，
    为个股决策提供市场背景。"""
    logger.debug("已调用 get_sector_context：%s，curr_date=%s", ticker, curr_date)
    try:
        import akshare as ak

        df = _ak_retry(lambda: ak.stock_sector_spot(indicator="新浪行业"))
        if df is None or df.empty:
            logger.warning("akshare 未返回 %s 的板块行情数据", ticker)
            return "DATA_UNAVAILABLE: 未返回行业板块实时数据。"
        df = df.copy()
        df["涨跌幅"] = pd.to_numeric(df["涨跌幅"], errors="coerce")
        df = df.dropna(subset=["涨跌幅"]).sort_values("涨跌幅", ascending=False)

        leader_cols = ["板块", "涨跌幅", "股票名称", "股票代码", "个股-涨跌幅", "个股-当前价"]
        top = df.head(5)[leader_cols].to_csv(index=False)
        bottom = df.tail(5)[leader_cols].to_csv(index=False)

        # 判断该代码今天是否为板块龙头。
        market, symbol = _to_akshare_symbol(ticker)
        leader_hit = ""
        if market == "ashare" and "股票代码" in df.columns:
            row = df[df["股票代码"].astype(str) == symbol]
            if not row.empty:
                r = row.iloc[0]
                leader_hit = (
                    f"\n{ticker} 是行业“{r['板块']}”的龙头股 "
                    f"（行业 {r['涨跌幅']:+.2f}%，个股 {r['个股-涨跌幅']:+.2f}%）。\n"
                )

        stamp = (pd.Timestamp(curr_date) if curr_date else pd.Timestamp.now()).strftime("%Y-%m-%d")
        logger.debug("板块行情为 %s 返回 %d 个板块", ticker, len(df))
        return (
            f"## {stamp} 的行业板块广度（新浪行业，akshare）\n"
            f"# 数据获取时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"### 今日表现最好的 5 个行业：\n{top}\n### 今日表现最差的 5 个行业：\n{bottom}"
            + leader_hit
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("获取 %s 的 akshare 板块上下文失败：%s", ticker, exc)
        return f"DATA_UNAVAILABLE: 行业上下文获取失败（{exc}）。请继续分析其他数据。"


def _recent_report_periods(curr_date: str) -> list[str]:
    """返回 curr_date 当日及之前最近两个季度报告期末（YYYYMMDD）。"""
    dt = pd.Timestamp(curr_date)
    periods = [
        pd.Timestamp(y, m, d)
        for y in range(dt.year - 1, dt.year + 1)
        for m, d in ((3, 31), (6, 30), (9, 30), (12, 31))
    ]
    recent = sorted([p for p in periods if p <= dt], reverse=True)[:2]
    return [p.strftime("%Y%m%d") for p in recent]


def get_earnings_forecast(ticker: str, curr_date: str = None) -> str:
    """业绩预告：公司对最近报告期的自主指引，是早于正式财务报表发布的领先信号。"""
    logger.debug("已调用 get_earnings_forecast：%s，curr_date=%s", ticker, curr_date)
    code = _ashare_code(ticker)
    if code is None:
        logger.warning("为非 A 股代码 %s 请求业绩预告", ticker)
        return f"通过 akshare 无法获取 '{ticker}' 的业绩预告（仅支持 A 股）。"
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
            hits.append(f"## 业绩预告窗口 {period}：\n" + rows[keep].to_csv(index=False))

        if not hits:
            logger.debug("%s 在期间 %s 内没有业绩预告数据行", ticker, periods)
            return (
                f"最近报告期内未找到 '{ticker}' 的业绩预告。A 股业绩预告并非强制披露，"
                "没有记录属于正常情况。"
            )
        logger.debug("业绩预告为 %s 返回 %d 个期间", ticker, len(hits))
        return (
            f"# {ticker} 的业绩预告（akshare/东方财富）\n"
            f"# 数据获取时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            + "\n".join(hits)
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("获取 %s 的 akshare 业绩预告失败：%s", ticker, exc)
        return f"DATA_UNAVAILABLE: 业绩预告获取失败（{exc}）。请继续分析其他数据。"


# ---------------------------------------------------------------------------
# 实际收益查询，用于决策跟踪/回测。
#
# 图会将待处理决策解析为实际收益（原始收益及相对于基准的 Alpha），从而最终为
# 每个决策评分。当前网络无法访问 Yahoo，因此使用 akshare 查询：股票使用新浪日线，
# 框架基准代码（000001.SS / 399001.SZ / SPY 等）使用对应的指数/美股序列。
# ---------------------------------------------------------------------------

# 框架基准代码 -> akshare 序列。
# A 股：指数（000001.SS 是上证综指，不是股票）。
# 美股：ETF/指数透传给美股日线序列。
_BENCHMARK_TO_AKSHARE: dict[str, str] = {
    "000001.SS": "sh000001",    # 上证综指
    "399001.SZ": "sz399001",    # 深证成指
    "399006.SZ": "sz399006",    # 创业板指
    "000300.SS": "sh000300",    # 沪深 300
    "000905.SS": "sh000905",    # 中证 500
    "SPY": "SPY",
    "QQQ": "QQQ",
    "^GSPC": "SPX",
}
_INDEX_SYMBOLS = {"sh000001", "sz399001", "sz399006", "sh000300", "sh000905"}


def _download_index_daily(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """获取新浪指数日线（sh000001 / sz399001 等），并裁剪到指定窗口。"""
    logger.debug("_download_index_daily called for %s %s..%s", symbol, start_date, end_date)
    import akshare as ak

    df = _ak_retry(lambda: ak.stock_zh_index_daily(symbol=symbol))
    if df is None or df.empty:
        logger.warning("akshare 指数 %s 未返回数据行", symbol)
        raise NoMarketDataError(symbol, symbol, "指数未返回数据行")
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).sort_values("date")
    start_dt = pd.Timestamp(start_date)
    end_dt = pd.Timestamp(end_date)
    df = df[(df["date"] >= start_dt) & (df["date"] <= end_dt)]
    if df.empty:
        logger.warning("akshare 指数 %s 在 %s..%s 期间没有数据行", symbol, start_date, end_date)
        raise NoMarketDataError(symbol, symbol, f"指数在 {start_date}..{end_date} 期间没有数据行")
    logger.debug("指数日线为 %s 返回 %d 行", symbol, len(df))
    return df


def get_market_returns(
    ticker: str,
    trade_date: str,
    holding_days: int = 5,
    benchmark: str = "SPY",
) -> tuple[float | None, float | None, int | None]:
    """计算 ``ticker`` 从 ``trade_date`` 开始持有 ``holding_days`` 天的实际原始收益
    和 Alpha，并以 ``benchmark``（akshare/新浪）为基准。

    返回 ``(raw_return, alpha_return, actual_holding_days)``；价格数据不可用时返回
    ``(None, None, None)``。该函数不会抛出异常，调用方用 None 表示“暂时无法解析”。
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
            "已计算 %s @ %s 的实际收益：原始=%.4f Alpha=%.4f 天数=%d",
            ticker, trade_date, raw, raw - bench_ret, actual_days,
        )
        return raw, raw - bench_ret, actual_days
    except Exception as exc:  # noqa: BLE001 — 解析失败不会导致流程终止。
        logger.warning("通过 akshare 查询 %s @ %s 的实际收益失败：%s", ticker, trade_date, exc)
        return None, None, None
