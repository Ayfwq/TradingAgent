"""供应商调用所需的代码规范化和市场数据错误类型。

Yahoo Finance（默认供应商）使用特定的股票代码约定，与用户常输入的经纪商/
TradingView/MT5 格式不同：

    user types        Yahoo wants       why
    ---------------   ---------------   -----------------------------------
    XAUUSD, XAUUSD+   GC=F              gold has no forex pair on Yahoo;
                                        it is quoted as a COMEX future
    EURUSD            EURUSD=X          spot forex pairs take a ``=X`` suffix
    BTCUSD            BTC-USD           crypto pairs use a ``-`` separator
    SPX500, US500     ^GSPC             index CFDs map to Yahoo index symbols

将原始经纪商代码传给 Yahoo 会返回空结果，Agent 之前会将其当作自由文本并可能
围绕它编造价格（见 issue #781）。将映射集中在这里，可以让所有 yfinance 入口
以相同方式解析代码；新增标的只需增加表格行，无需修改调用点。
"""

from __future__ import annotations

import logging
import re

# NoMarketDataError 位于供应商错误分类（errors.py）中；这里重新导出，便于许多
# 与 normalize_symbol 一起导入它的调用点使用。
from .errors import NoMarketDataError as NoMarketDataError

logger = logging.getLogger(__name__)


# 零售外汇交易对中常见的 ISO-4217 代码。六位且前后半段都在集合中的裸代码，
# 视为即期外汇交易对并添加 Yahoo 的 ``=X`` 后缀。
_FOREX_CURRENCIES = frozenset(
    {
        "USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD",
        "CNY", "CNH", "HKD", "SGD", "SEK", "NOK", "DKK", "PLN",
        "MXN", "ZAR", "TRY", "INR", "KRW", "BRL", "RUB", "THB",
    }
)

# 经纪商以无分隔符形式对美元报价的加密货币基础代码。
_CRYPTO_BASES = frozenset(
    {"BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "LTC", "BCH", "DOT", "AVAX", "LINK"}
)

# 无法通过规则映射到 Yahoo 代码的标的显式别名。金属/能源映射到最近月期货，
# 指数 CFD 名称映射到对应的 Yahoo 指数代码。新增行即可扩展，无需修改调用点。
_ALIASES = {
# 贵金属（现货名称 -> COMEX/NYMEX 期货）。
    "XAUUSD": "GC=F", "XAU": "GC=F", "GOLD": "GC=F",
    "XAGUSD": "SI=F", "XAG": "SI=F", "SILVER": "SI=F",
    "XPTUSD": "PL=F", "XPDUSD": "PA=F",
# 能源。
    "WTICOUSD": "CL=F", "USOIL": "CL=F", "WTI": "CL=F",
    "BCOUSD": "BZ=F", "UKOIL": "BZ=F", "BRENT": "BZ=F",
    "NATGAS": "NG=F", "XNGUSD": "NG=F",
    "COPPER": "HG=F", "XCUUSD": "HG=F",
# 指数 CFD -> Yahoo 指数代码。
    "SPX500": "^GSPC", "US500": "^GSPC", "SPX": "^GSPC",
    "NAS100": "^NDX", "US100": "^NDX", "USTEC": "^NDX",
    "US30": "^DJI", "DJI30": "^DJI", "WS30": "^DJI",
    "GER40": "^GDAXI", "GER30": "^GDAXI", "DE40": "^GDAXI",
    "UK100": "^FTSE", "JP225": "^N225", "JPN225": "^N225",
    "FRA40": "^FCHI", "EU50": "^STOXX50E", "HK50": "^HSI",
}

# Yahoo 代码可以包含字母、数字及这些结构字符。
_YAHOO_SAFE = re.compile(r"^[A-Za-z0-9._\-\^=]+$")


# 都映射到 Yahoo 美元交易对的加密货币报价币种。Yahoo 只列出 ``<BASE>-USD``，
# 不列出 USDT/USDC 稳定币交易对，因此使用这些报价币种的经纪商代码都解析为
# ``-USD``（#982）。按长度降序排列，确保 ``USDT``/``USDC`` 先于 ``USD`` 匹配。
_CRYPTO_QUOTES = ("USDT", "USDC", "USD")


def crypto_base(raw: str) -> str | None:
    """返回已知 USD/USDT/USDC 报价加密货币代码的基础币种（例如 ``BTC``）。
    支持流水线可能持有的 ``BTC-USD``、``BTCUSD``、``BTC-USDT`` 等形式；
    非加密货币代码返回 None。该函数仅执行语法判断。
    """
    if not isinstance(raw, str):
        return None
    compact = raw.strip().upper().rstrip("+").replace("-", "")
    for quote in _CRYPTO_QUOTES:
        if compact.endswith(quote):
            base = compact[: -len(quote)]
            return base if base in _CRYPTO_BASES else None
    return None


def _normalize_crypto(s: str) -> str | None:
    """已知 USD/USDT/USDC 报价加密货币返回 ``<BASE>-USD``，否则返回 None。"""
    base = crypto_base(s)
    return f"{base}-USD" if base else None


def normalize_symbol(raw: str) -> str:
    """将用户/经纪商代码映射为规范的 Yahoo Finance 代码。

    解析顺序（首次匹配优先）：
      1. 显式别名表（金属、能源、指数 CFD）；
      2. 加密货币规则：以 USD/USDT/USDC 报价的已知加密货币（带或不带短横线）
         -> ``BASE-USD``；
      3. 外汇规则：六个字母且由两个 ISO 货币代码组成 -> ``PAIR=X``；
      4. 否则原样返回大写代码（普通股票、ETF、Yahoo 原生代码如 ``GC=F`` 或 ``^GSPC``）。

    匹配前会删除末尾的 ``+``（经纪商 CFD 标记，例如 ``XAUUSD+``）。该函数仅执行
    语法处理，不发起网络请求，因此可以安全地应用于每次请求。
    """
    if not isinstance(raw, str) or not raw.strip():
        return raw

    s = raw.strip().upper()
    # Yahoo 永远不会使用的经纪商 CFD/限定后缀。
    s = s.rstrip("+")

    crypto = _normalize_crypto(s)
    if s in _ALIASES:
        canonical = _ALIASES[s]
    elif crypto is not None:
        canonical = crypto
    elif len(s) == 6 and s[:3] in _FOREX_CURRENCIES and s[3:] in _FOREX_CURRENCIES:
        canonical = f"{s}=X"
    else:
        canonical = s

    if canonical != raw.strip().upper():
        logger.info("已将代码 %r 解析为 Yahoo 代码 %r", raw, canonical)
    return canonical


def is_yahoo_safe(symbol: str) -> bool:
    """当 ``symbol`` 只包含 Yahoo 代码使用的字符时返回 True。"""
    return bool(symbol) and _YAHOO_SAFE.fullmatch(symbol) is not None
