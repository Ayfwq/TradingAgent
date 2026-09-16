# TradingAgents/graph/reflection.py：决策反思。

import logging
from typing import Any

logger = logging.getLogger(__name__)


class Reflector:
    """处理交易决策反思。"""

    def __init__(self, quick_thinking_llm: Any):
        """使用 LLM 初始化反思器。"""
        self.quick_thinking_llm = quick_thinking_llm
        self.log_reflection_prompt = self._get_log_reflection_prompt()
        logger.debug("反思器已初始化")

    def _get_log_reflection_prompt(self) -> str:
        """用于 reflect_on_final_decision 的简洁提示词（阶段 B 日志条目）。

        生成 2-4 句纯文本，足够简洁，可以重新注入后续 Agent 提示词而不会撑大上下文窗口。
        """
        return (
            "你是一名交易分析师，现在结果已经明确，请复盘自己过去的决策。\n"
            "只写 2-4 句纯文本（不要项目符号、标题或 Markdown）。\n\n"
            "按以下顺序覆盖：\n"
            "1. 方向判断是否正确？（引用 Alpha 数值）\n"
            "2. 投资论点的哪一部分成立或失败？\n"
            "3. 对下一次类似分析的一条具体经验。\n\n"
            "具体、简洁。输出会原样保存到决策日志，并由未来的分析师重新阅读，"
            "因此每个词都必须有价值。"
        )

    def reflect_on_final_decision(
        self,
        final_decision: str,
        raw_return: float,
        alpha_return: float,
        benchmark_name: str = "SPY",
    ) -> str:
        """结合结果上下文，对最终交易决策执行一次反思调用。

        由阶段 B 延迟反思使用。final_trade_decision 已综合所有分析师观点，因此不需
        单独的市场上下文。``benchmark_name`` 是 Alpha 行使用的标签（例如美股代码
        使用 ``"SPY"``，``.T`` 上市代码使用 ``"^N225"``）；尚未传入基准的调用方
        默认使用 SPY。
        """
        messages = [
            ("system", self.log_reflection_prompt),
            (
                "human",
                (
                    f"原始收益：{raw_return:+.1%}\n"
                    f"相对于 {benchmark_name} 的 Alpha：{alpha_return:+.1%}\n\n"
                    f"最终决策：\n{final_decision}"
                ),
            ),
        ]
        logger.debug(
            "正在反思决策（原始=%+.1f%%，Alpha=%+.1f%%，基准=%s）",
            raw_return, alpha_return, benchmark_name,
        )
        try:
            result = self.quick_thinking_llm.invoke(messages).content
            logger.debug("反思内容已生成（%d 个字符）", len(result or ""))
            return result
        except Exception as exc:
            logger.warning("反思 LLM 调用失败：%s", exc)
            raise
