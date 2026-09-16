"""TradingAgents 的只追加 Markdown 决策日志。"""

import logging
import re
from pathlib import Path

from tradingagents.agents.utils.rating import parse_rating

logger = logging.getLogger(__name__)


class TradingMemoryLog:
    """只追加保存交易决策和反思内容的 Markdown 日志。"""

    # HTML 注释不会出现在 LLM 的自然语言输出中，可安全用作硬分隔符。
    _SEPARATOR = "\n\n<!-- ENTRY_END -->\n\n"
    # 预编译正则，避免每次调用 load_entries() 时重复编译。
    _DECISION_RE = re.compile(r"DECISION:\n(.*?)(?=\nREFLECTION:|\Z)", re.DOTALL)
    _REFLECTION_RE = re.compile(r"REFLECTION:\n(.*?)$", re.DOTALL)

    def __init__(self, config: dict = None):
        cfg = config or {}
        self._log_path = None
        path = cfg.get("memory_log_path")
        if path:
            self._log_path = Path(path).expanduser()
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
        # 可选的已完成条目数量上限；None 表示不轮换。
        self._max_entries = cfg.get("memory_log_max_entries")
        logger.debug(
            "TradingMemoryLog 已初始化：日志路径=%s，最大条目数=%s",
            self._log_path, self._max_entries,
        )

    # --- 写入路径（阶段 A）---

    def store_decision(
        self,
        ticker: str,
        trade_date: str,
        final_trade_decision: str,
    ) -> None:
        """在 propagate() 末尾追加待处理条目，不调用 LLM。"""
        logger.debug(
            "已调用 store_decision：ticker=%s，trade_date=%s",
            ticker, trade_date,
        )
        if not self._log_path:
            return
        # 幂等保护：扫描原始文本，避免完整解析。
        if self._log_path.exists():
            raw = self._log_path.read_text(encoding="utf-8")
            for line in raw.splitlines():
                if line.startswith(f"[{trade_date} | {ticker} |") and line.endswith("| pending]"):
                    logger.debug(
                        "store_decision 跳过重复的待处理条目：%s / %s",
                        ticker, trade_date,
                    )
                    return
        rating = parse_rating(final_trade_decision)
        tag = f"[{trade_date} | {ticker} | {rating} | pending]"
        entry = f"{tag}\n\nDECISION:\n{final_trade_decision}{self._SEPARATOR}"
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(entry)
        logger.info(
            "store_decision 已写入待处理条目：ticker=%s，trade_date=%s，rating=%s",
            ticker, trade_date, rating,
        )

    # --- 读取路径（阶段 A）---

    def load_entries(self) -> list[dict]:
        """解析日志中的所有条目，返回字典列表。"""
        logger.debug("正在加载记忆条目：log_path=%s", self._log_path)
        if not self._log_path or not self._log_path.exists():
            logger.debug("load_entries：日志文件不存在，返回空列表")
            return []
        text = self._log_path.read_text(encoding="utf-8")
        raw_entries = [e.strip() for e in text.split(self._SEPARATOR) if e.strip()]
        entries = []
        for raw in raw_entries:
            parsed = self._parse_entry(raw)
            if parsed:
                entries.append(parsed)
        logger.debug("load_entries 已解析 %d 个条目", len(entries))
        return entries

    def get_pending_entries(self) -> list[dict]:
        """返回 outcome:pending 的条目（供阶段 B 使用）。"""
        pending = [e for e in self.load_entries() if e.get("pending")]
        logger.debug("get_pending_entries 找到 %d 个待处理条目", len(pending))
        return pending

    def get_past_context(self, ticker: str, n_same: int = 5, n_cross: int = 3) -> str:
        """返回格式化的历史上下文字符串，供注入 Agent 提示词。"""
        logger.debug(
            "正在获取历史上下文：ticker=%s，n_same=%d，n_cross=%d",
            ticker, n_same, n_cross,
        )
        entries = [e for e in self.load_entries() if not e.get("pending")]
        if not entries:
            logger.debug("get_past_context：未找到 %s 的已完成条目", ticker)
            return ""

        same, cross = [], []
        for e in reversed(entries):
            if len(same) >= n_same and len(cross) >= n_cross:
                break
            if e["ticker"] == ticker and len(same) < n_same:
                same.append(e)
            elif e["ticker"] != ticker and len(cross) < n_cross:
                cross.append(e)

        if not same and not cross:
            logger.debug("get_past_context：未找到 %s 的匹配条目", ticker)
            return ""

        parts = []
        if same:
            parts.append(f"{ticker} 的历史分析（最新在前）：")
            parts.extend(self._format_full(e) for e in same)
        if cross:
            parts.append("近期其他股票的经验：")
            parts.extend(self._format_reflection_only(e) for e in cross)
        result = "\n\n".join(parts)
        logger.debug(
            "get_past_context 为 %s 构建了 %d 个字符（%d 个同股票条目，%d 个其他股票条目）",
            len(result), ticker, len(same), len(cross),
        )
        return result

    # --- 更新路径（阶段 B）---

    def update_with_outcome(
        self,
        ticker: str,
        trade_date: str,
        raw_return: float,
        alpha_return: float,
        holding_days: int,
        reflection: str,
    ) -> None:
        """通过原子写入替换待处理标签，并追加 REFLECTION 部分。

        查找第一个匹配（trade_date、ticker）的待处理条目，在标签中写入收益率，
        并追加 REFLECTION 部分。使用临时文件和 os.replace()，即使写入中途崩溃
        也不会损坏日志。
        """
        logger.debug(
            "已调用 update_with_outcome：ticker=%s，trade_date=%s，raw_return=%s，alpha_return=%s，holding_days=%d",
            ticker, trade_date, raw_return, alpha_return, holding_days,
        )
        if not self._log_path or not self._log_path.exists():
            logger.debug("update_with_outcome：日志文件不存在，跳过")
            return

        text = self._log_path.read_text(encoding="utf-8")
        blocks = text.split(self._SEPARATOR)

        pending_prefix = f"[{trade_date} | {ticker} |"
        raw_pct = f"{raw_return:+.1%}"
        alpha_pct = f"{alpha_return:+.1%}"

        updated = False
        new_blocks = []
        for block in blocks:
            stripped = block.strip()
            if not stripped:
                new_blocks.append(block)
                continue

            lines = stripped.splitlines()
            tag_line = lines[0].strip()

            if (
                not updated
                and tag_line.startswith(pending_prefix)
                and tag_line.endswith("| pending]")
            ):
                # 从现有的待处理标签中解析评级。
                fields = [f.strip() for f in tag_line[1:-1].split("|")]
                rating = fields[2]
                new_tag = (
                    f"[{trade_date} | {ticker} | {rating}"
                    f" | {raw_pct} | {alpha_pct} | {holding_days}d]"
                )
                rest = "\n".join(lines[1:])
                new_blocks.append(
                    f"{new_tag}\n\n{rest.lstrip()}\n\nREFLECTION:\n{reflection}"
                )
                updated = True
            else:
                new_blocks.append(block)

        if not updated:
            logger.debug(
                "update_with_outcome：未找到匹配的待处理条目：%s / %s",
                trade_date, ticker,
            )
            return

        new_blocks = self._apply_rotation(new_blocks)
        new_text = self._SEPARATOR.join(new_blocks)
        tmp_path = self._log_path.with_suffix(".tmp")
        tmp_path.write_text(new_text, encoding="utf-8")
        tmp_path.replace(self._log_path)
        logger.info(
            "update_with_outcome 已完成条目：ticker=%s，trade_date=%s，raw=%s，alpha=%s",
            ticker, trade_date, raw_pct, alpha_pct,
        )

    def batch_update_with_outcomes(self, updates: list[dict]) -> None:
        """通过一次读取和原子写入应用多个结果更新。

        updates 中的每个元素都必须包含 ticker、trade_date、raw_return、
        alpha_return、holding_days、reflection 键。
        """
        logger.debug(
            "已调用 batch_update_with_outcomes，包含 %d 个更新", len(updates)
        )
        if not self._log_path or not self._log_path.exists() or not updates:
            logger.debug("batch_update_with_outcomes：没有日志文件或更新内容，跳过")
            return

        text = self._log_path.read_text(encoding="utf-8")
        blocks = text.split(self._SEPARATOR)

        # 构建以（trade_date、ticker）为键的查找表，实现 O(1) 分发。
        update_map = {(u["trade_date"], u["ticker"]): u for u in updates}

        new_blocks = []
        for block in blocks:
            stripped = block.strip()
            if not stripped:
                new_blocks.append(block)
                continue

            lines = stripped.splitlines()
            tag_line = lines[0].strip()

            matched = False
            for (trade_date, ticker), upd in list(update_map.items()):
                pending_prefix = f"[{trade_date} | {ticker} |"
                if tag_line.startswith(pending_prefix) and tag_line.endswith("| pending]"):
                    fields = [f.strip() for f in tag_line[1:-1].split("|")]
                    rating = fields[2]
                    raw_pct = f"{upd['raw_return']:+.1%}"
                    alpha_pct = f"{upd['alpha_return']:+.1%}"
                    new_tag = (
                        f"[{trade_date} | {ticker} | {rating}"
                        f" | {raw_pct} | {alpha_pct} | {upd['holding_days']}d]"
                    )
                    rest = "\n".join(lines[1:])
                    new_blocks.append(
                        f"{new_tag}\n\n{rest.lstrip()}\n\nREFLECTION:\n{upd['reflection']}"
                    )
                    del update_map[(trade_date, ticker)]
                    matched = True
                    break

            if not matched:
                new_blocks.append(block)

        new_blocks = self._apply_rotation(new_blocks)
        new_text = self._SEPARATOR.join(new_blocks)
        tmp_path = self._log_path.with_suffix(".tmp")
        tmp_path.write_text(new_text, encoding="utf-8")
        tmp_path.replace(self._log_path)
        logger.info(
            "batch_update_with_outcomes 已应用 %d 个更新",
            len(updates) - len(update_map),
        )

    # --- 辅助方法 ---

    def _apply_rotation(self, blocks: list[str]) -> list[str]:
        """当已完成块数量超过 max_entries 时删除最早的块。

        待处理块始终保留（它们代表尚未处理的工作）。禁用轮换或未超过上限时，
        原样返回 ``blocks``。
        """
        if not self._max_entries or self._max_entries <= 0:
            return blocks

        # 解析标签行标记，为每个块标注是否已完成。
        decisions = []
        for block in blocks:
            stripped = block.strip()
            if not stripped:
                decisions.append((block, False))
                continue
            tag_line = stripped.splitlines()[0].strip()
            is_resolved = (
                tag_line.startswith("[")
                and tag_line.endswith("]")
                and not tag_line.endswith("| pending]")
            )
            decisions.append((block, is_resolved))

        resolved_count = sum(1 for _, r in decisions if r)
        if resolved_count <= self._max_entries:
            return blocks

        to_drop = resolved_count - self._max_entries
        logger.debug(
            "_apply_rotation 正在删除 %d 个已完成块（max_entries=%s）",
            to_drop, self._max_entries,
        )
        kept: list[str] = []
        for block, is_resolved in decisions:
            if is_resolved and to_drop > 0:
                to_drop -= 1
                continue
            kept.append(block)
        return kept

    def _parse_entry(self, raw: str) -> dict | None:
        lines = raw.strip().splitlines()
        if not lines:
            return None
        tag_line = lines[0].strip()
        if not (tag_line.startswith("[") and tag_line.endswith("]")):
            logger.debug("_parse_entry 跳过了不含标签括号的区块")
            return None
        fields = [f.strip() for f in tag_line[1:-1].split("|")]
        if len(fields) < 4:
            logger.debug("_parse_entry 跳过了字段数为 %d 的区块", len(fields))
            return None
        entry = {
            "date": fields[0],
            "ticker": fields[1],
            "rating": fields[2],
            "pending": fields[3] == "pending",
            "raw": fields[3] if fields[3] != "pending" else None,
            "alpha": fields[4] if len(fields) > 4 else None,
            "holding": fields[5] if len(fields) > 5 else None,
        }
        body = "\n".join(lines[1:]).strip()
        decision_match = self._DECISION_RE.search(body)
        reflection_match = self._REFLECTION_RE.search(body)
        entry["decision"] = decision_match.group(1).strip() if decision_match else ""
        entry["reflection"] = reflection_match.group(1).strip() if reflection_match else ""
        return entry

    def _format_full(self, e: dict) -> str:
        raw = e["raw"] or "n/a"
        alpha = e["alpha"] or "n/a"
        holding = e["holding"] or "n/a"
        tag = f"[{e['date']} | {e['ticker']} | {e['rating']} | {raw} | {alpha} | {holding}]"
        parts = [tag, f"DECISION:\n{e['decision']}"]
        if e["reflection"]:
            parts.append(f"REFLECTION:\n{e['reflection']}")
        return "\n\n".join(parts)

    def _format_reflection_only(self, e: dict) -> str:
        tag = f"[{e['date']} | {e['ticker']} | {e['rating']} | {e['raw'] or 'n/a'}]"
        if e["reflection"]:
            return f"{tag}\n{e['reflection']}"
        text = e["decision"][:300]
        suffix = "..." if len(e["decision"]) > 300 else ""
        return f"{tag}\n{text}{suffix}"
