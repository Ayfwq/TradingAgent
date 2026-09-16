import logging
import re
from datetime import date, datetime, timedelta
from typing import Annotated

import pandas as pd

logger = logging.getLogger(__name__)

SavePathType = Annotated[str, "保存数据的文件路径；为 None 时不保存数据。"]

# 股票代码可以包含字母、数字、点号、短横线、下划线、脱字符（如 ^GSPC）、
# 等号（如 GC=F）和加号（如 XAUUSD+）。这些字符都不能启用目录遍历，因此插入
# 路径时不会逃逸出所在目录；其他字符一律拒绝。
_TICKER_PATH_RE = re.compile(r"^[A-Za-z0-9._\-\^=+]+$")


def safe_ticker_component(value: str, *, max_len: int = 32) -> str:
    """校验将 ``value`` 插入文件系统路径是否安全。

    股票代码来自用户输入或 LLM 工具调用，两者都可能受到攻击者控制的内容
    影响（例如嵌入获取新闻中的提示词注入）。如果不校验，类似 ``"../../../etc/foo"``
    的值会流入 ``os.path.join`` / ``Path /``，逃逸出配置的缓存、检查点或结果目录。

    匹配允许模式时原样返回 ``value``，否则抛出 ``ValueError``。
    """
    logger.debug("已调用 safe_ticker_component：value=%r，max_len=%d", value, max_len)
    if not isinstance(value, str) or not value:
        logger.warning("股票代码必须是非空字符串，实际为 %r", value)
        raise ValueError(f"股票代码必须是非空字符串，实际为 {value!r}")
    if len(value) > max_len:
        logger.warning("股票代码 %r 超过 %d 个字符", value, max_len)
        raise ValueError(f"股票代码超过 {max_len} 个字符：{value!r}")
    if not _TICKER_PATH_RE.fullmatch(value):
        logger.warning("股票代码 %r 包含文件系统路径不允许的字符", value)
        raise ValueError(
            f"股票代码包含文件系统路径不允许的字符：{value!r}"
        )
    # 上面的正则允许 '.', 因此 '.', '..', '...' 等值会通过，但作为路径组件会
    # 遍历到父目录。拒绝只包含点号的值。
    if set(value) == {"."}:
        logger.warning("股票代码 %r 不能只由点号组成", value)
        raise ValueError(f"股票代码不能只由点号组成：{value!r}")
    return value


def save_output(data: pd.DataFrame, tag: str, save_path: SavePathType = None) -> None:
    logger.debug("已调用 save_output：tag=%s，save_path=%s", tag, save_path)
    if save_path:
        data.to_csv(save_path, encoding="utf-8")
        logger.debug("%s 已保存到 %s", tag, save_path)


def get_current_date():
    logger.debug("已调用 get_current_date")
    return date.today().strftime("%Y-%m-%d")


def decorate_all_methods(decorator):
    def class_decorator(cls):
        for attr_name, attr_value in cls.__dict__.items():
            if callable(attr_value):
                setattr(cls, attr_name, decorator(attr_value))
        return cls

    return class_decorator


def get_next_weekday(date):
    logger.debug("已调用 get_next_weekday：%s", date)
    if not isinstance(date, datetime):
        date = datetime.strptime(date, "%Y-%m-%d")

    if date.weekday() >= 5:
        days_to_add = 7 - date.weekday()
        next_weekday = date + timedelta(days=days_to_add)
        return next_weekday
    else:
        return date
