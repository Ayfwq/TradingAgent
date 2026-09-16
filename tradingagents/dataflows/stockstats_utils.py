import logging
import os
import time
from typing import Annotated

import pandas as pd
import yfinance as yf
from stockstats import wrap
from yfinance.exceptions import YFRateLimitError

from .config import get_config
from .symbol_utils import NoMarketDataError, normalize_symbol
from .utils import safe_ticker_component

logger = logging.getLogger(__name__)

# 如果数据供应商返回的最新 OHLCV 行比请求日期早这么多日历日，
# 就视为过期。该阈值足以覆盖较长的节假日周末，也能捕获 yfinance
# 偶尔返回的旧到一年前的数据（#1021）。
MAX_OHLCV_STALE_DAYS = 10

# 当日缓存尚未覆盖请求日期时，最多复用多久后重新获取（#1150）。
# 时间足够短，盘中运行可以在收盘数据发布后很快获取；也足够长，
# 不会因为周末或节假日没有 K 线而每次调用都下载。
OHLCV_CACHE_TTL_SECONDS = 900


def yf_retry(func, max_retries=3, base_delay=2.0):
    """执行 yfinance 调用，并在触发限流时使用指数退避重试。

    yfinance 在收到 HTTP 429 响应时会抛出 YFRateLimitError，但不会自动重试。
    该包装器专门为限流增加重试逻辑，其他异常会立即向上抛出。
    """
    for attempt in range(max_retries + 1):
        try:
            return func()
        except YFRateLimitError:
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"Yahoo Finance 触发限流，将在 {delay:.0f} 秒后重试（第 {attempt + 1}/{max_retries} 次）")
                time.sleep(delay)
            else:
                raise


def _ensure_date_column(data: pd.DataFrame) -> pd.DataFrame:
    """将日期列规范化为 ``Date``。

    某些 yfinance 版本会让索引保持未命名状态（此时 ``reset_index()`` 产生
    ``index``），或在盘中数据中使用 ``Datetime``。将第一个类似日期的列重命名，
    避免因列名不是 ``Date`` 而导致指标静默丢失。
    """
    if "Date" in data.columns:
        return data
    for candidate in ("index", "Datetime", "date"):
        if candidate in data.columns:
            return data.rename(columns={candidate: "Date"})
    return data


def _clean_dataframe(data: pd.DataFrame) -> pd.DataFrame:
    """为 stockstats 规范化股票 DataFrame：解析日期、删除无效行并填充价格缺口。"""
    data = _ensure_date_column(data)
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data = data.dropna(subset=["Date"])

    price_cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in data.columns]
    data[price_cols] = data[price_cols].apply(pd.to_numeric, errors="coerce")
    data = data.dropna(subset=["Close"])
    data[price_cols] = data[price_cols].ffill().bfill()

    return data


def _coerce_ohlcv_dates(data: pd.DataFrame) -> pd.Series:
    """返回 OHLCV 数据中的解析日期，无论 Date 是列还是索引。"""
    if "Date" in data.columns:
        return pd.to_datetime(data["Date"], errors="coerce").dropna()
    # yfinance 会将日期保留在索引中（通常是未命名的 DatetimeIndex）。
    if isinstance(data.index, pd.DatetimeIndex):
        return pd.Series(pd.to_datetime(data.index, errors="coerce")).dropna()
    # 回退处理：展开索引并查找类似日期的列。
    df = data.reset_index()
    for col in ("Date", "Datetime", "date", "index"):
        if col in df.columns:
            parsed = pd.to_datetime(df[col], errors="coerce").dropna()
            if not parsed.empty:
                return parsed
    return pd.Series(dtype="datetime64[ns]")


def _assert_ohlcv_not_stale(
    data: pd.DataFrame,
    curr_date: str,
    symbol: str,
    canonical: str | None = None,
    *,
    max_stale_days: int = MAX_OHLCV_STALE_DAYS,
) -> None:
    """拒绝最新行明显早于 curr_date 的 OHLCV 数据。

    抛出带有过期详情的 NoMarketDataError，让路由器像处理“供应商没有可用数据”
    一样尝试下一个供应商，最后再输出明确的不可用信号。空数据仍由调用方的
    原有逻辑处理；这里只防护“有数据但已过期”的危险情况（例如供应商返回一年前
    的数据，导致 Agent 使用错误价格，#1021）。
    """
    if data is None or data.empty:
        return
    requested = pd.to_datetime(curr_date, errors="coerce")
    if pd.isna(requested):
        return
    requested = requested.normalize()
    dates = _coerce_ohlcv_dates(data)
    if dates.empty:
        return
    latest = dates.max().normalize()
    stale_days = (requested - latest).days
    if stale_days > max_stale_days:
        raise NoMarketDataError(
            symbol,
            canonical,
            f"最新数据行为 {latest.date()}，比请求日期 {requested.date()} 早 {stale_days} 天，"
            "数据已过期，拒绝使用",
        )


def _needs_same_day_refresh(data_file, curr_date_dt, today_date) -> bool:
    """判断是否必须重新获取缓存数据，以反映请求日期的数据。

    缓存文件按日期索引。如果没有此检查，在当日 K 线尚未最终确定前启动的运行会
    持续向后续运行提供同一快照（#1150）。当前日期请求存在两种过期情况：K 线
    完全缺失，或者仍在形成中——Yahoo 会在交易时段发布部分日线蜡烛图，此时
    ``Close`` 不是收盘价。仅靠行检查无法区分部分 K 线和最终 K 线，因此所有
    当日缓存都由 TTL 控制。历史日期数据不可变，可以始终复用缓存。
    """
    if curr_date_dt.date() < today_date.date():
        return False
    return time.time() - os.path.getmtime(data_file) > OHLCV_CACHE_TTL_SECONDS


def _fetch_ohlcv(symbol: str, canonical: str, start_str: str, end_str: str) -> pd.DataFrame:
    """根据配置的 ``technical_indicators`` 供应商链下载 OHLCV 数据。

    yfinance 仍是历史默认供应商。当配置指定 ``akshare``（或供应商链包含它且
    yfinance 不可用，例如中国大陆网络无法访问 Yahoo）时，改用 akshare/Sina
    下载器。返回包含 ``Date`` 列的数据框；当所有配置的供应商都无法返回可用数据
    时抛出 ``NoMarketDataError``。
    """
    from .config import get_config

    config = get_config()
    chain = config.get("data_vendors", {}).get("technical_indicators", "default")
    vendors = [
        v.strip()
        for v in str(chain).split(",")
        if v.strip() and v.strip() != "default"
    ]
    if not vendors:
        vendors = ["yfinance", "akshare"]  # 默认链：尝试所有可用供应商。

    errors = []
    for vendor in vendors:
        if vendor == "yfinance":
            try:
                downloaded = yf_retry(lambda: yf.download(
                    canonical,
                    start=start_str,
                    end=end_str,
                    multi_level_index=False,
                    progress=False,
                    auto_adjust=True,
                ))
                frame = _ensure_date_column(downloaded.reset_index())
                if frame.empty or "Close" not in frame.columns:
                    raise NoMarketDataError(
                    symbol, canonical, "Yahoo Finance 未返回数据行"
                    )
                return frame
            except NoMarketDataError as exc:
                # 空的 yfinance 数据框含义不明确：可能是真正的未知代码，也可能是
                # Yahoo 限流（HTTP 429）导致空下载而没有抛出异常。不要中断供应商链，
                # 给下一个配置的供应商（例如 akshare）一次机会。
                logger.warning("yfinance 未返回 %s 的数据行：%s", canonical, exc)
                errors.append(f"yfinance：{exc}")
                continue
            except Exception as exc:  # noqa: BLE001 — 继续尝试供应商链中的下一个供应商
                logger.warning("获取 %s 的 yfinance OHLCV 失败：%s", canonical, exc)
                errors.append(f"yfinance：{exc}")
                continue
        elif vendor == "akshare":
            try:
                from .akshare_data import load_ohlcv_akshare

                # akshare 辅助函数会过滤自身的 5 年窗口；传入今天，让下面调用方的
                # curr_date 过滤真正负责防止未来数据泄漏。
                frame = load_ohlcv_akshare(
                    symbol, pd.Timestamp.today().strftime("%Y-%m-%d")
                )
                if frame.empty or "Close" not in frame.columns:
                    raise NoMarketDataError(symbol, canonical, "akshare 未返回数据行")
                return frame
            except NoMarketDataError as exc:
                # 原因与 yfinance 相同：让下一个配置的供应商继续尝试。
                logger.warning("akshare 未返回 %s 的数据行：%s", canonical, exc)
                errors.append(f"akshare：{exc}")
                continue
            except Exception as exc:  # noqa: BLE001 — 继续尝试供应商链中的下一个供应商
                logger.warning("获取 %s 的 akshare OHLCV 失败：%s", canonical, exc)
                errors.append(f"akshare：{exc}")
                continue

    detail = "；".join(errors) if errors else "没有可用的配置供应商"
    raise NoMarketDataError(symbol, canonical, detail)


def load_ohlcv(symbol: str, curr_date: str) -> pd.DataFrame:
    """获取带缓存的 OHLCV 数据，并过滤以防止前视偏差。

    下载截至今天的 5 年数据并按代码缓存，后续调用复用缓存。过滤掉 curr_date
    之后的数据，确保回测永远看不到未来价格。
    """
    # 将经纪商/外汇代码（XAUUSD+ -> GC=F）解析为 Yahoo 约定格式，
    # 然后拒绝插入缓存文件名后会逃逸出缓存目录的值（例如 ``../../tmp/x``）。
    canonical = normalize_symbol(symbol)
    safe_symbol = safe_ticker_component(canonical)

    config = get_config()
    curr_date_dt = pd.to_datetime(curr_date)

    # 缓存使用固定窗口（5 年至今），每个代码对应一个文件。
    today_date = pd.Timestamp.today()
    start_date = today_date - pd.DateOffset(years=5)
    start_str = start_date.strftime("%Y-%m-%d")
    # yfinance 的 ``end`` 为不包含边界；请求明天，以便 curr_date 为今天时包含
    # 今天的数据行（#986）。下面的 curr_date 过滤仍会防止前视。
    end_str = (today_date + pd.Timedelta(days=1)).strftime("%Y-%m-%d")

    os.makedirs(config["data_cache_dir"], exist_ok=True)
    data_file = os.path.join(
        config["data_cache_dir"],
        f"{safe_symbol}-YFin-data-{start_str}-{end_str}.csv",
    )

    # 如果之前获取失败（未知代码或临时限流），缓存文件可能为空。将空文件或无列
    # 文件视为缓存未命中并重新获取，避免永远提供这个无效文件。
    data = None
    if os.path.exists(data_file):
        cached = pd.read_csv(data_file, on_bad_lines="skip", encoding="utf-8")
        # 只有缓存可用且不是请求日期的过期快照时才使用（#1150）；否则继续重新获取。
        if (
            not cached.empty
            and "Close" in cached.columns
            and not _needs_same_day_refresh(data_file, curr_date_dt, today_date)
        ):
            data = cached

    if data is None:
        downloaded = _fetch_ohlcv(symbol, canonical, start_str, end_str)
        # 只缓存真实数据，永远不要持久化空数据框。
        if downloaded.empty or "Close" not in downloaded.columns:
            raise NoMarketDataError(
                symbol, canonical, "没有供应商返回可用数据行"
            )
        downloaded.to_csv(data_file, index=False, encoding="utf-8")
        data = downloaded

    data = _clean_dataframe(data)

    # 过滤到 curr_date，防止回测出现前视偏差。
    data = data[data["Date"] <= curr_date_dt]

    # 拒绝最新行远早于 curr_date 的数据框，避免将一年前的价格输入指标（#1021）。
    _assert_ohlcv_not_stale(data, curr_date, symbol, canonical)

    return data


def filter_financials_by_date(data: pd.DataFrame, curr_date: str) -> pd.DataFrame:
    """删除 curr_date 之后的财务报表列（财务期间时间戳）。

    yfinance 财务报表使用财务期间结束日期作为列名。curr_date 之后的列代表未来
    数据，会被删除以防止前视偏差。
    """
    if not curr_date or data.empty:
        return data
    cutoff = pd.Timestamp(curr_date)
    mask = pd.to_datetime(data.columns, errors="coerce") <= cutoff
    return data.loc[:, mask]


class StockstatsUtils:
    @staticmethod
    def get_stock_stats(
        symbol: Annotated[str, "公司股票代码"],
        indicator: Annotated[
            str, "基于公司股票数据的量化指标",
        ],
        curr_date: Annotated[
            str, "获取股票价格数据的当前日期，格式为 YYYY-mm-dd",
        ],
    ):
        data = load_ohlcv(symbol, curr_date)
        df = wrap(data)
        df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
        curr_date_str = pd.to_datetime(curr_date).strftime("%Y-%m-%d")

        df[indicator]  # 触发 stockstats 计算指标。
        matching_rows = df[df["Date"].str.startswith(curr_date_str)]

        if not matching_rows.empty:
            indicator_value = matching_rows[indicator].values[0]
            return indicator_value
        else:
            return "无数据：非交易日（周末或节假日）"
