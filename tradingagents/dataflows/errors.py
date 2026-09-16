"""供应商数据错误分类。

使用统一层级，使路由层按行为而不是按供应商处理错误：供应商无法返回可用数据
的所有情况都派生自 ``VendorError``，路由器捕获基类即可。新供应商抛出这些异常
（或定义一个简单的供应商专属子类）即可，无需增加新的 ``except`` 分支。

    VendorError
    ├── NoMarketDataError          没有可用行（空结果或数据过期）
    ├── VendorRateLimitError       临时限流 -> 跳过并尝试下一个供应商
    └── VendorNotConfiguredError   缺少 API key/配置 -> 供应商不可用

异常类型数量对应路由器的不同处理方式，而不是人类可描述原因的数量：空数据和
过期数据处理方式相同，因此共用 ``NoMarketDataError``，只在自由文本 ``detail``
中区分。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class VendorError(Exception):
    """供应商无法返回可用数据时使用的异常基类。"""


class NoMarketDataError(VendorError):
    """供应商没有为代码返回可用行（结果为空或数据过期）。

    携带用户请求的代码、实际查询的规范代码以及自由文本 ``detail``，让调用方
    可以构建清晰消息，而不是将供应商专属的空字符串写入数据通道。
    """

    def __init__(self, symbol: str, canonical: str | None = None, detail: str = ""):
        self.symbol = symbol
        self.canonical = canonical or symbol
        self.detail = detail
        msg = f"没有 {symbol!r} 的市场数据"
        if canonical and canonical != symbol:
            msg += f"（实际查询代码为 {canonical!r}）"
        if detail:
            msg += f": {detail}"
        logger.warning("为 %s（规范代码 %s）抛出 NoMarketDataError：%s", symbol, self.canonical, self.detail)
        super().__init__(msg)


class VendorRateLimitError(VendorError):
    """供应商对请求限流；路由器跳过并尝试下一个供应商。"""


class VendorNotConfiguredError(VendorError, ValueError):
    """已选择供应商，但缺少其 API key 或配置。

    同时继承 ``ValueError``，使捕获 ``ValueError`` 的现有调用方继续工作，而
    路由层可以将其视为“供应商不可用”。
    """
