import logging
import re
from datetime import date, datetime, timedelta
from typing import Annotated

import pandas as pd

logger = logging.getLogger(__name__)

SavePathType = Annotated[str, "File path to save data. If None, data is not saved."]

# Tickers can contain letters, digits, dot, dash, underscore, caret
# (index symbols like ^GSPC), equals (futures like GC=F), and plus
# (forex/CFD symbols like XAUUSD+). None of these enable directory
# traversal, so the value never escapes a containing directory when
# interpolated into a path. Anything else is rejected.
_TICKER_PATH_RE = re.compile(r"^[A-Za-z0-9._\-\^=+]+$")


def safe_ticker_component(value: str, *, max_len: int = 32) -> str:
    """Validate ``value`` is safe to interpolate into a filesystem path.

    Tickers come from user CLI input or from LLM tool calls, both of which
    can be influenced by attacker-controlled content (e.g. prompt injection
    embedded in fetched news). Without validation, a value like
    ``"../../../etc/foo"`` flows into ``os.path.join`` / ``Path /`` and
    escapes the configured cache, checkpoint, or results directory.

    Returns ``value`` unchanged when it matches the allowed pattern; raises
    ``ValueError`` otherwise.
    """
    logger.debug("safe_ticker_component called for %r max_len=%d", value, max_len)
    if not isinstance(value, str) or not value:
        logger.warning("ticker must be a non-empty string, got %r", value)
        raise ValueError(f"ticker must be a non-empty string, got {value!r}")
    if len(value) > max_len:
        logger.warning("ticker %r exceeds %d chars", value, max_len)
        raise ValueError(f"ticker exceeds {max_len} chars: {value!r}")
    if not _TICKER_PATH_RE.fullmatch(value):
        logger.warning("ticker %r contains characters not allowed in a filesystem path", value)
        raise ValueError(
            f"ticker contains characters not allowed in a filesystem path: {value!r}"
        )
    # The regex above allows '.', so values like '.', '..', '...' would pass,
    # and as a path component they traverse the parent directory. Reject any
    # value that's only dots.
    if set(value) == {"."}:
        logger.warning("ticker %r cannot consist solely of dots", value)
        raise ValueError(f"ticker cannot consist solely of dots: {value!r}")
    return value


def save_output(data: pd.DataFrame, tag: str, save_path: SavePathType = None) -> None:
    logger.debug("save_output called for tag=%s save_path=%s", tag, save_path)
    if save_path:
        data.to_csv(save_path, encoding="utf-8")
        logger.debug("%s saved to %s", tag, save_path)
        print(f"{tag} saved to {save_path}")


def get_current_date():
    logger.debug("get_current_date called")
    return date.today().strftime("%Y-%m-%d")


def decorate_all_methods(decorator):
    def class_decorator(cls):
        for attr_name, attr_value in cls.__dict__.items():
            if callable(attr_value):
                setattr(cls, attr_name, decorator(attr_value))
        return cls

    return class_decorator


def get_next_weekday(date):
    logger.debug("get_next_weekday called for %s", date)
    if not isinstance(date, datetime):
        date = datetime.strptime(date, "%Y-%m-%d")

    if date.weekday() >= 5:
        days_to_add = 7 - date.weekday()
        next_weekday = date + timedelta(days=days_to_add)
        return next_weekday
    else:
        return date
