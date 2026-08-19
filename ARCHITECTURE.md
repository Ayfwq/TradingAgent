# TradingAgents 项目架构分析

> 版本：v0.3.1 · 基于 LangGraph 的多智能体金融交易分析框架
> 本文档用于后续较大优化的基线认知。

## 1. 一句话概括

TradingAgents 把一次股票/加密资产分析拆成 **分析师 → 多空研究员辩论 → 交易员 → 风险团队辩论 → 组合经理决策** 五段流水线，用 LangGraph 的 StateGraph 串成可流式执行的有状态图，全部节点由 LLM 驱动（deep/quick 两档模型），数据由可插拔 vendor 层（yfinance / Alpha Vantage / FRED / Polymarket）提供。

## 2. 目录结构

```
main.py                        # 程序化入口：TradingAgentsGraph().propagate("NVDA", date)
cli/                           # 交互式 Typer CLI（tradingagents 命令）
  main.py                      #   选择 ticker/日期/分析师/模型 → 流式展示 → 存报告
  utils.py                     #   provider 表格、模型选择、API key 确认、backend URL 解析
  models.py stats_handler.py announcements.py
tradingagents/
  default_config.py            # 中央配置 + TRADINGAGENTS_* 环境变量覆盖（单一事实源）
  reporting.py                 # 结果 markdown 报告树写出
  graph/                       # ★ LangGraph 编排层
    trading_graph.py           #   TradingAgentsGraph 主类：建 LLM、工具节点、编译图、propagate()
    setup.py                   #   图装配：节点/边/条件路由
    conditional_logic.py       #   辩论轮数与转向条件
    analyst_execution.py       #   分析师执行计划（顺序、工具节点、清理节点）
    propagation.py             #   初始 state 构建
    reflection.py signal_processing.py checkpointer.py
  agents/                      # ★ Agent 工厂（每个 agent = 一个 LangGraph 节点）
    analysts/                  #   market / sentiment(social) / news / fundamentals
    researchers/               #   bull / bear（辩论双方）
    managers/                  #   research_manager（deep LLM 裁判）, portfolio_manager（deep LLM 终审）
    risk_mgmt/                 #   aggressive / conservative / neutral 三位风控辩手
    trader/                    #   trader（quick LLM）
    schemas.py                 #   结构化输出 Pydantic 模型（ResearchPlan/TraderProposal/PortfolioDecision/SentimentReport）
    utils/                     #   agent_states, agent_utils(工具导入+identity解析), memory(决策记忆), structured(结构化回退), rating, 各数据工具
  llm_clients/                 # ★ LLM 提供商抽象层
    factory.py                 #   create_llm_client(provider, model, base_url)
    base_client.py             #   抽象基类 + content 归一化
    openai_client.py           #   ★ OpenAI 兼容提供商注册表 OPENAI_COMPATIBLE_PROVIDERS + DeepSeekChatOpenAI
    model_catalog.py           #   CLI 模型下拉目录（含 deepseek-v4-flash）
    capabilities.py            #   按模型声明的 API 能力表（tool_choice/结构化方法/reasoning 回传）
    api_key_env.py             #   provider → API key 环境变量名映射
    anthropic/google/azure/bedrock_client.py
  dataflows/                   # ★ 数据 vendor 抽象层
    interface.py               #   按方法路由到配置的 vendor，带降级/哨兵
    akshare_data.py            #   ★ akshare 国内数据源 vendor（新浪/东财/金十，本部署新增）
    y_finance.py yfinance_news.py stockstats_utils.py
    alpha_vantage*.py fred.py polymarket.py reddit.py stocktwits.py
    symbol_utils.py market_data_validator.py config.py errors.py
```

## 3. 执行流水线（LangGraph 图结构）

```
START
 └─ 分析师链（可配置子集，默认 4 个，均为 quick LLM + 工具循环）：
    market(技术面) → sentiment(社交情绪) → news(新闻/宏观) → fundamentals(基本面)
    每个分析师节点：LLM 带工具 → 条件边（有 tool_calls → 工具节点 → 回到分析师；否则 → 清理节点）
    清理节点清空消息上下文，注入占位提示，避免上下文无限膨胀
 └─ 研究团队：Bull ↔ Bear 循环辩论（每轮交替），轮数 = 2 × max_debate_rounds
    结束 → Research Manager（deep LLM，结构化输出 ResearchPlan）
 └─ Trader（quick LLM，结构化输出 TraderProposal，含 BUY/HOLD/SELL + 价位）
 └─ 风控团队：Aggressive → Conservative → Neutral 循环（轮数 = 3 × max_risk_discuss_rounds）
    结束 → Portfolio Manager（deep LLM，结构化输出 PortfolioDecision → 最终评级）
 └─ END
```

节点类型：
- **Agent 节点**：`prompt | llm.bind_tools(tools)` 或 `with_structured_output(Schema)`
- **工具节点**：`ToolNode([get_stock_data, get_indicators, ...])`，按分析师分组
- **清理节点**：`create_msg_delete()` — RemoveMessage + 锚定上下文的占位 HumanMessage

## 4. LLM 客户端架构（改模型配置的关键）

`create_llm_client(provider, model, base_url, **kwargs)` 工厂：
- **原生 API**（不走 OpenAI 兼容）：anthropic / google / azure / bedrock
- **OpenAI 兼容注册表** `OPENAI_COMPATIBLE_PROVIDERS`（openai_client.py）：
  openai, xai, deepseek, qwen, qwen-cn, glm, glm-cn, minimax, minimax-cn,
  openrouter, mistral, kimi, groq, nvidia, ollama, openai_compatible
- 每个 ProviderSpec 声明：`base_url`（默认端点）、`base_url_env`、`key_optional`、
  `placeholder_key`、`require_base_url`、`use_responses_api`、`chat_class`（子类 quirks）
- **URL 优先级**：`self.base_url`（来自 config backend_url ← `TRADINGAGENTS_LLM_BACKEND_URL`）
  > provider 专属 env（如 OLLAMA_BASE_URL）> 注册表默认端点
- **API key**：`api_key_env.PROVIDER_API_KEY_ENV` 单一映射，deepseek → `DEEPSEEK_API_KEY`
- **DeepSeek 特殊处理** `DeepSeekChatOpenAI`：
  - `_get_request_payload` 把上一轮 assistant 的 `reasoning_content` 回传给 API（否则 400）
  - `_create_chat_result` 捕获返回的 `reasoning_content`
- **能力表** capabilities.py：`deepseek-v4-flash` → `_DEEPSEEK_THINKING`
  （`supports_tool_choice=False`：结构化输出只绑 schema 为 tool、不发 tool_choice；
   `requires_reasoning_content_roundtrip=True`）
- **结构化输出**：`with_structured_output` 按能力表选方法（function_calling / json_mode /
  json_schema / none），失败自动回退 free-text（structured.py）

## 5. 配置体系

- `default_config.py` 的 `DEFAULT_CONFIG` 是唯一事实源
- `_ENV_OVERRIDES` 把 `TRADINGAGENTS_*` 环境变量映射到 config key，按默认值类型强转
- `tradingagents/__init__.py` 在 import 时 `load_dotenv(usecwd=True)` 加载项目根 `.env`
- CLI 交互项凡设置了对应 env var 即跳过（provider/模型/backend URL/辩论轮数/语言）

### 当前生效配置（.env）

```ini
TRADINGAGENTS_LLM_PROVIDER=deepseek
TRADINGAGENTS_LLM_BACKEND_URL=http://8.134.103.73:3000/v1
DEEPSEEK_API_KEY=sk-knwewGqnX0TWQMItWXxVYyReUL0YQNKdgwUbS8CBIShy8MsZ
TRADINGAGENTS_DEEP_THINK_LLM=deepseek-v4-flash
TRADINGAGENTS_QUICK_THINK_LLM=deepseek-v4-flash
TRADINGAGENTS_OUTPUT_LANGUAGE=English
TRADINGAGENTS_MAX_DEBATE_ROUNDS=1
TRADINGAGENTS_MAX_RISK_ROUNDS=1
TRADINGAGENTS_DATA_VENDORS={"core_stock_apis":"akshare","technical_indicators":"akshare","fundamental_data":"akshare","news_data":"akshare","macro_data":"akshare"}
NO_PROXY=*        # 绕过间歇性抽风的系统代理(127.0.0.1:7897)，数据层直连国内源
```

选择 provider=`deepseek` 而非 `openai_compatible` 的原因：保留 `DeepSeekChatOpenAI`
子类（reasoning_content 回传），这对 `deepseek-v4-flash` 的思考模式是必需的；
`backend_url` 覆盖默认端点指向自定义网关。

数据源选择 `akshare` 的原因：本机出口 IP 被 Yahoo Finance 429 封锁（中国大陆
常见），akshare 背后的新浪/东财/金十接口国内直连可达、免费、无限额。实现要点：

- `dataflows/akshare_data.py`：符号映射（`600519.SS→sh600519`、`000001.SZ→sz000001`、
  `NVDA→us`、`0700.HK→00700`）+ 各数据工具实现
- `stockstats_utils.load_ohlcv` 新增 `_fetch_ohlcv`：按 `technical_indicators`
  vendor 链降级（yfinance 失败 → akshare），技术指标与市场验证快照共用
- `get_indicators` 的 akshare 路由复用 yfinance 的 stockstats 计算（数据来自 akshare）
- 美股/港股行情走新浪 `stock_us_daily` / `stock_hk_daily`；A 股基本面走新浪
  `stock_financial_analysis_indicator` + `stock_financial_abstract`；A 股新闻走
  东财搜索域（`stock_news_em`，与 kline 域不同、未被封锁）；宏观走金十系列；
  A 股内幕/董监高交易走雪球 `stock_inner_trade_xq`（按代码 + 90 天窗口过滤）
- 美股基本面/个股新闻无稳定国内源 → 优雅降级为提示文本，不中断流水线
- `TRADINGAGENTS_DATA_VENDORS`（JSON）在 `TradingAgentsGraph` 初始化时应用，
  避免 import 期生效泄漏进单元测试（测试断言 yfinance 默认值）

### A 股为完整链路（推荐用法）

akshare 对 A 股覆盖最全：行情/指标/快照/基本面/三大报表/新闻/全球快讯/宏观/
内幕交易**全部真实数据、零降级**。运行方式：

```bash
uv run python scripts/run_ashare.py 600519.SS          # 默认今天
uv run python scripts/run_ashare.py 000001.SZ 2026-08-14
```

输出：最终决策（终端）+ 记忆日志（`~/.tradingagents/memory/`）+ 报告树
（`~/.tradingagents/logs/`）+ 状态日志 JSON。

美股（NVDA 等）仍可跑（行情/指标完整），但基本面与个股新闻会降级为提示文本。

## 6. 数据层（dataflows）

- 方法级 vendor 路由：`route_to_vendor(method, ...)` 按 `data_vendors`/`tool_vendors`
  配置取 vendor 链，依次尝试，仅显式配置的 vendor 会被使用
- 核心类别失败会抛错；可选类别（macro/prediction_markets）降级为
  `DATA_UNAVAILABLE` 哨兵不中断运行；无数据返回 `NO_DATA_AVAILABLE` 哨兵
- `symbol_utils.normalize_symbol`：XAUUSD→GC=F 等归一化，保证价格路径与身份解析一致
- 防幻觉机制：`resolve_instrument_identity` 确定性解析公司身份注入每个 agent 的
  instrument_context；market analyst 强制调用 `get_verified_market_snapshot` 作事实基准

## 7. 记忆与恢复

- **决策日志**（默认开启）：每次运行 append 到 `~/.tradingagents/memory/trading_memory.md`；
  下次同 ticker 运行先 `_resolve_pending_entries` 拉真实收益（raw + alpha vs 基准）生成反思，
  注入 Portfolio Manager prompt
- **检查点续跑**（`--checkpoint` 开启）：per-ticker SQLite，崩溃后从最后成功节点续跑；
  线程 ID 绑定 ticker+date+图形态签名

## 8. 关键优化切入点（供后续讨论）

1. **LLM 成本/延迟**：deep/quick 目前同模型（deepseek-v4-flash），可考虑 quick 用更小模型；
   辩论轮数、分析师子集与 token 消耗正相关
2. **客户端单例化**：`TradingAgentsGraph.__init__` 每次建两个 client；多 run 复用可缓存
3. **工具循环**：分析师工具调用链无 max_tool_rounds 上限（靠 recursion_limit 兜底），
   弱模型可能空转；可加工具调用轮数上限
4. **结构化输出**：deepseek 走 function_calling 且无 tool_choice，`invoke_structured_or_freetext`
   失败会重试一次 free-text，可观测性（失败率/回退率）值得统计
5. **数据缓存**：yfinance 每次全量拉取，OHLCV 有 freshness 校验但缺少跨 run 持久缓存策略
6. **并发**：四个分析师目前串行；数据工具与分析师可并行化（LangGraph 支持 fan-out）
7. **测试**：tests/ 覆盖广（60+ 文件），改动后跑 `uv run pytest -q` 保底

---

## 9. 优化记录（2026-08 · 全链路优化）

> 本轮优化目标：速度、成本、可信度、A股特化、工程健壮性。全部改动保持既有测试基线，并在末尾经过全量测试 + 端到端流水线验证。

### 9.1 ① 分析师工具循环轮数上限
- `default_config.py` 新增 `max_tool_rounds`（默认 3）。
- `graph/conditional_logic.py` 的 `should_continue_*` 数当前分析师消息通道中带 `tool_calls` 的轮数，达到上限强制出报告（原来只有整图 recursion_limit 兜底，话痨模型会空转烧 token）。

### 9.2 ② 分析师并行化（本轮最大提速）
- 原串行链（analyst1 → … → analystN）改为 **fan-out/fan-in**：START 同时进入全部选中分析师，各分析师完成后 fan-in 进 Bull Researcher（LangGraph 自动等待全部完成）。
- 关键配套：**per-analyst 消息隔离**。`AgentState` 新增 `market/sentiment/news/fundamentals_messages` 四个通道（`add_messages` reducer）；各分析师节点、ToolNode（`messages_key`）、clear 节点（`create_msg_delete(messages_key)`）、初始 state 全部按通道读写，避免并行下共享 `messages` 互相污染。保留 `state["messages"]` 读回退与写镜像，旧调用/旧 checkpoint 兼容。
- checkpoint 签名加入 `layout=parallel-v1`，旧串行 checkpoint 自动失效。

### 9.3 ③ LLM 客户端连接复用
- `TradingAgentsGraph.__init__` 创建共享 `httpx.Client`（300s/connect 10s 超时），经 `http_client` 传给 deep/quick 两个 client，网关 keep-alive 连接池复用。

### 9.4 ④ deep/quick 模型分层 + ⑦ 温度
- `.env`：`TRADINGAGENTS_DEEP_THINK_LLM=deepseek-v4-pro`（旗舰，deep 环节），`TRADINGAGENTS_QUICK_THINK_LLM=deepseek-v4-flash`（高频环节），`TRADINGAGENTS_TEMPERATURE=0.2`。
- `deepseek-v4-pro` 已在 capabilities（`_DEEPSEEK_THINKING`，reasoning_content 回传），实测连通。

### 9.5 ⑧⑨ A股特色数据工具（新增 5 个，全部降级友好）
`dataflows/akshare_data.py` + `agents/utils/ashare_context_tools.py` + `interface.py` 新类别：
| 工具 | 数据源 | 挂载 |
|---|---|---|
| `get_lhb_context` 龙虎榜 | 东财 datacenter（可用） | market |
| `get_northbound_flow` 北向资金 | 东财（可用） | market |
| `get_limit_up_context` 涨停池 | 东财 push2ex（可用） | market |
| `get_sector_context` 行业板块 | 新浪（可用） | market |
| `get_earnings_forecast` 业绩预告 | 东财 datacenter（可用） | fundamentals |

实测边界：东财 push2 域（spot/行业板块/个股信息/分红）被 WAF 拦，未采用；深交所两融 SSL 失败，未采用。

### 9.6 ⑤ 回测框架 + ⑥ 决策跟踪
- `scripts/run_backtest.py`：历史日期跑完整流水线（防未来数据泄漏由框架保证），用 akshare 对齐 20/60/120 日真实收益，输出每期表 + 汇总统计（Buy/Sell/Hold 平均收益）。
- **关键修复**：决策收益解析 `_fetch_returns` 原用 yfinance（Yahoo 封锁下永远失败，决策永远 pending），改为 akshare（`get_market_returns`，含基准指数 sh000001/sz399001/SPY 映射），yfinance 保留为回退。
- memory log 的 pending→resolved+反思机制复用，回测用独立 scratch memory 避免污染线上日志。

### 9.7 线程安全修复（并行化的隐藏炸弹）
- akshare 新浪日线接口（stock_zh_a_daily/index/us/hk）用 **py_mini_racer（V8）** 解密，非线程安全——并行分析师并发调用会**进程级崩溃**（FATAL: partition_address_space.cc，无法 catch）。
- `_ak_retry` 全量加 `threading.RLock` 串行化 akshare 调用；LLM 调用（主要耗时）仍并行。

### 9.7b 并行 fan-in 跨层崩溃修复（Analyst Barrier，本轮最深的坑）
- **现象**：真实 LLM 跑并行图时 `InvalidUpdateError: At key 'investment_debate_state'`（FakeLLM 冒烟测试不触发）。
- **根因**：LangGraph 1.2 的 fan-in **只 join 同一深度层（super-step）的信号**。分析师在 agent↔tool 间循环多轮、各分析师轮数不同 → 4 个 clear 落在不同层 → "Bull Researcher" 提前执行（辩论基于部分报告）→ 晚到的 clear 再次触发 Bull → 与下游（RM/Trader/PM）并发写非 reducer key → 崩溃。最小复现（`scripts/langgraph_fanin_repro.py`）确认跨层信号不等待。
- **修复**：新增 **"Analyst Barrier"** 节点——4 个 clear 全部 fan-in 到它；每次收到 clear 信号执行一次，检查"所有分析师已完成"（报告非空 **或** 其 clear 节点写入了 `*_done` 标记），齐了才路由到 Bull Researcher，否则返回空路由元组 `()` 吸收信号（图继续等未完成的分析师——它们仍是 pending 任务）。
- **配套**：`create_msg_delete(messages_key, done_key=)` 写完成标记；`AgentState` 加 4 个 `*_done` 字段；`AnalystNodeSpec` 加 `done_key`。
- 回归工具：`scripts/repro_tool_rounds_graph.py`（FakeLLM 触发真实工具循环 + 不同深度层，断言全流水线到 PM）。

### 9.8 ⑪⑫⑬⑭⑩ 其余项
- ⑪ `scripts/check_gateway.py`：deep/quick 双模型健康检查。
- ⑫ `scripts/scan_tickers.py`：多 ticker 批量分析，输出对比表 + JSON + 目标价/止损提取。
- ⑬ `run_ashare.py` 输出 `run_summary.json`（ticker/date/耗时/决策/信号/报告路径/模型/数据源/各报告长度）。
- ⑭ `tests/test_akshare_vendor_mock.py`：17 个离线 mock 测试（接口契约+降级），真实网络测试保留在 `scripts/test_akshare_vendor.py`。
- ⑩ `get_language_instruction()` 中文档增强：中文报告锚定 A 股术语（买入/卖出/市盈率/北向资金…）。

### 9.9 优化后的运行方式
```bash
uv run python scripts/check_gateway.py            # 网关健康检查
uv run python scripts/run_ashare.py 600519.SS     # 单票完整分析（今天）
uv run python scripts/scan_tickers.py 600519.SS 000001.SZ   # 批量对比
uv run python scripts/run_backtest.py --ticker 600519.SS --dates 2026-05-15 --hold 20,60
uv run python scripts/probe_ashare_extra.py       # A股特色接口探测
uv run python scripts/check_ashare_coverage.py    # 板块覆盖自检
uv run python -m pytest -q -m "not integration"   # 全量测试
```
