# 更新日志

TradingAgents 的所有重要变更都记录在此。

格式基于 [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)，
项目遵循 [Semantic Versioning](https://semver.org/spec/v2.0.0.html)。
0.x 系列中的破坏性变更会单独标注。

## [0.3.1] — 2026-07-05

正确性与稳定性补丁：数据未来泄漏、图路由器崩溃安全、检查点身份、
加密货币情绪来源以及可配置的韧性。

### 修复

- **Alpha Vantage 的未来数据过滤器现在会执行。** 基本面载荷是 JSON 字符串，
  之前仅检查字典的保护逻辑跳过了过滤，导致未来日期的报告泄漏到历史运行中；
  现改为先解析再过滤。（#1115，@zachthebird）
- **新闻分析师提示词与工具一致。** 提示词原先宣传 `get_news(query, ...)`，
  但工具接收的是 ticker；现已对齐，避免模型虚构自由文本查询调用。
  （#1116，@shcheuk）
- **共享辩论/风险路由器不会在运行中崩溃。** 两个路由器返回的目标多于任一
  单条边的映射数量；现在每条边共享完整路径映射，即使提示词、国际化或重构
  出现偏差，落空路径仍可路由。（#1088，@Fr3ya，@sa7an7，@Sushanth012）
- **检查点恢复遵循图结构。** 线程 ID 纳入所选分析师、辩论/风险深度和资产模式，
  因此使用不同选择恢复时不会继续错误的图。（#1089，@bossjoker1，@Ghraven）
- **加密货币情绪来源可正确解析。** StockTwits 将加密货币列为 `<BASE>.X`
  （Yahoo 的 `BTC-USD` 会返回 404），而 Reddit 需要基础代码才能匹配；
  社交数据路径现在会为两者正确映射加密货币。（#1113，@suremadoreai）

### 新增

- **可配置的 LLM 重试额度。** `llm_max_retries` /
  `TRADINGAGENTS_LLM_MAX_RETRIES` 会转发给每个供应商，因此短暂的 429 请求突发不再中止运行。
  （#1091，@yanggaome）
- **Bedrock API 密钥认证。** `AWS_BEARER_TOKEN_BEDROCK` 无需 AWS 访问密钥即可
  认证 Amazon Bedrock，且优先于环境中的 `AWS_PROFILE`。（#1103，@praxstack）
- **最新 Claude 模型。** 新增 Claude Sonnet 5（`claude-sonnet-5`）和
  Fable 5（`claude-fable-5`）；Claude 5 系列现在支持 effort 控制。

## [0.3.0] — 2026-06-22

稳定性与可扩展性版本：新增 CI 门禁、统一的数据访问校验契约、供应商与数据
供应商注册表，并通过维护性清理强化配置优先级、模型目录、数据韧性和结构化输出。

### 新增

- **CI 门禁。** GitHub Actions 在 Python 3.10-3.13 上运行 pytest 测试套件、
  严格的 `ruff` 检查，以及导入包和 CLI 的干净安装冒烟测试，用于发现未声明依赖。
  （#994，#197）
- **供应商注册表。** OpenAI 兼容供应商注册为统一规格，通用
  `openai_compatible` 端点覆盖 vLLM、LM Studio 和中继服务；新增 NVIDIA NIM、
  Kimi、Groq、Mistral 以及原生 Amazon Bedrock 客户端。
- **宏观与预测市场供应商。** FRED 宏观指标和 Polymarket 事件概率会提供给
  新闻与宏观分析师。
- **程序化报告输出。** `TradingAgentsGraph.save_reports()` 为无头运行和 API
  运行写入与 CLI 相同的报告树。（#1037）
- **可通过环境变量配置推理深度。** 通过
  `TRADINGAGENTS_OPENAI_REASONING_EFFORT`、`TRADINGAGENTS_GOOGLE_THINKING_LEVEL`
  和 `TRADINGAGENTS_ANTHROPIC_EFFORT` 设置，并仅对接受这些参数的模型启用。

### 变更

- **统一的数据访问校验契约。** 每个供应商路径（身份、收益、CLI、新闻）都进行
  代码规范化；配置的供应商列表就是准确的解析链，不会静默回退到未选择的供应商；
  建立类型化的 `VendorError` 分类；新闻窗口防止未来数据；拒绝过期 OHLCV；
  yfinance 日期范围改为包含边界。
- **配置优先级。** 显式的 `TRADINGAGENTS_*` 值或 CLI 标志现在优先于辩论和风险
  轮数、`--checkpoint / --no-checkpoint` 以及 Docker 供应商配置的交互式默认值；
  无效布尔环境变量会明确报错。（#975，#976，#977）
- **当前代际模型目录。** 刷新供应商阵容，移除 `gpt-4.1`、Claude Sonnet 4.5
  和 Gemini 2.5 系列。
- **可选供应商会降级**而不是中止运行：宏观或预测市场查询失败时返回无数据哨兵值。
- **分析师提示词以当前日期开头**，使工具调用的日期范围锚定运行日期，而不是模型
  的训练截止日期。（#836）

### 修复

- **标的身份。** 确定性的代码到公司解析可防止错误公司幻觉，经校验的市场数据快照
  为价格和指标结论提供依据。（#814，#830）
- **社交与市场数据来源。** Reddit 优先使用 RSS 并在 429 时退避；强化 StockTwits
  传输；处理 Alpha Vantage 超时以及密钥错误与限流的区别。
- **结构化输出。** 本地 OpenAI 兼容服务器不再拒绝对象形式的 `tool_choice`；
  未返回解析结果的思考模型会回退到自由文本；可选价格字段中的类空字符串会转换为
  `None`。（#1038，#1051，#1057）

### 移除

- 无实际作用的 `analyst_concurrency_limit` 配置项；并行分析师执行计划在后续版本推出。
  （#979）
- 未使用但已提交的 `uv.lock`。（#1030）

### 贡献者

感谢所有通过代码、设计和报告参与塑造此版本的人：

[@CadeYu](https://github.com/CadeYu), [@Zavianx](https://github.com/Zavianx), [@weijianz-opc](https://github.com/weijianz-opc), [@naltun](https://github.com/naltun), [@brahmasky](https://github.com/brahmasky), [@nik2208](https://github.com/nik2208), [@thieucong98](https://github.com/thieucong98), [@Derekko-web](https://github.com/Derekko-web), [@LukiPrince](https://github.com/LukiPrince), [@Eddieargenal](https://github.com/Eddieargenal), [@Ghraven](https://github.com/Ghraven), [@ms32035](https://github.com/ms32035), [@yting27](https://github.com/yting27), [@nyxst4ck](https://github.com/nyxst4ck), [@KenCheung-AIxFinance](https://github.com/KenCheung-AIxFinance), [@yangyusheng2n](https://github.com/yangyusheng2n), [@fareloj](https://github.com/fareloj), [@haosenwang1018](https://github.com/haosenwang1018), [@octo-patch](https://github.com/octo-patch), [@seifenk](https://github.com/seifenk), [@CaoYuhaoCarl](https://github.com/CaoYuhaoCarl), [@mihailnica10](https://github.com/mihailnica10), [@Dado-hash](https://github.com/Dado-hash), [@Handsomemikezzz](https://github.com/Handsomemikezzz), [@ydhawesome](https://github.com/ydhawesome), [@macd2](https://github.com/macd2), [@AyushKar2005](https://github.com/AyushKar2005), [@wildhuman](https://github.com/wildhuman), [@robert23kim](https://github.com/robert23kim), [@bngness](https://github.com/bngness), [@tedix-rodrigo](https://github.com/tedix-rodrigo), [@malaccan](https://github.com/malaccan), [@rfalken78](https://github.com/rfalken78), [@dengli1971-droid](https://github.com/dengli1971-droid), [@proofconcept39](https://github.com/proofconcept39), [@prasta1](https://github.com/prasta1), [@liximin](https://github.com/liximin), [@jeffhuen](https://github.com/jeffhuen), [@mazar](https://github.com/mazar), [@soyangelromero](https://github.com/soyangelromero), [@CNQQC](https://github.com/CNQQC), [@dovetaill](https://github.com/dovetaill), [@fperdigon](https://github.com/fperdigon), [@gyx09212214-prog](https://github.com/gyx09212214-prog), [@RSXLX](https://github.com/RSXLX).

## [0.2.5] — 2026-05-11

### 新增

- **基于真实数据的情绪分析师。** 重命名后的 `sentiment_analyst` 会在生成报告前读取
  真实的 Yahoo News、StockTwits 和 Reddit 数据，替代之前可能在提示词压力下虚构
  社交帖子的流程。（#557，#607）
- **MiniMax 供应商**提供完整的 M2.x 目录（M2.7 / M2.5 / M2.1 / M2 及高速版本，
  204K 上下文），支持全球（`MINIMAX_API_KEY`）和中国
  （`MINIMAX_CN_API_KEY`）双区域。
- **Qwen 和 GLM 双区域**，每个区域使用独立密钥——国际区域
  （`DASHSCOPE_API_KEY`、`ZHIPU_API_KEY`）和中国区域
  （`DASHSCOPE_CN_API_KEY`、`ZHIPU_CN_API_KEY`），可通过二级区域提示选择。
  （#758）
- **`TRADINGAGENTS_*` 环境变量可配置 `DEFAULT_CONFIG`。** 可通过 `.env` 覆盖
  `llm_provider`、深度/快速模型 ID、`backend_url`、`output_language`、
  辩论轮数、检查点开关和基准代码，并自动按字符串/整数/布尔值进行类型转换。（#602）
- **CLI 交互式 API 密钥检测。** 选定供应商缺少密钥时，CLI 会提示输入并将值持久化到
  `.env`，无需重启即可继续分析。
- **远程 Ollama 支持。** `OLLAMA_BASE_URL` 可让 CLI 和程序化客户端连接远程
  `ollama-serve`。CLI 会展示解析后的端点，并提示常见格式错误；新增“自定义模型 ID”
  选项，可选择通过 `ollama pull` 获取的模型。（#648，#768）
- **可配置的新闻获取参数。** `DEFAULT_CONFIG` 支持设置每个代码的文章上限、
  宏观标题上限、回溯窗口和宏观搜索查询。（#606，#683）
- **可配置的非美股 Alpha 基准。** 用区域指数替换硬编码的 SPY，支持
  `.NS`（^NSEI）、`.T`（^N225）、`.HK`（^HSI）、
  `.L`（^FTSE）、`.TO`（^GSPTSE）、`.AX`（^AXJO）、
  `.BO`（^BSESN），也支持显式覆盖 `benchmark_ticker`。
  消除外币汇率漂移主导非美元上市标的 Alpha 的问题。（#628，#684）
- **多语言输出覆盖所有面向用户的智能体**——包括研究员、风险辩手、研究经理和交易员，
  结束之前报告仅部分本地化的状态。（#575）
- **模型目录刷新。** 更新 OpenAI GPT-5.5 前沿模型、Anthropic Claude Opus 4.7、
  Gemini 3.1 Flash-Lite 正式版、xAI Grok 4.20 和 Qwen 3.6 系列；只展示带版本号的 ID，
  自动变化的别名移至“自定义模型 ID”选项。

### 变更

- **情绪分析师**现在在 CLI 下拉框、状态面板和最终报告中统一命名
  （之前后端已重命名，但 CLI 仍显示“Social Analyst”）。协议值
  `AnalystType.SOCIAL = "social"` 保留，以兼容已保存配置。

### 修复

- **DeepSeek V4 / reasoner 与 MiniMax M2.x 支持结构化输出。** 这些供应商根据工具调用文档
  拒绝 `tool_choice`；现在绑定流程通过能力表自动跳过该参数。
- **`pip install .` 安装后可读取项目 `.env`。** 以控制台脚本运行 CLI 时同样生效。（#747）
- **报告端到端保存。** 之前流式块会从 `complete_report.md` 中丢失，现在已修复。（#719，#736）
- **股票代码提示词保留交易所后缀。** 对 A 股、港股、东京及其他非美股流程保留
  `.SH`、`.SZ`、`.SS`、`.HK`、`.T` 等后缀。（#770）
- **Docker 权限错误**不再阻止首次写入 `~/.tradingagents/`。（#519，#627，#672，#771）
- **配置状态不再在多次运行之间泄漏。** 修改子字典时，`set_config` 的局部更新会保留同级默认值。
  （#788）
- **`max_recur_limit` 配置真正生效。** 之前虽然读取了它，但没有转发给传播器。（#764）
- **缺少 API 密钥的错误**会指出需要设置的确切环境变量。（#680）
- **启动更安静。** 抑制来自 langgraph-checkpoint 的上游
  `LangChainPendingDeprecationWarning`；待该软件包发布修复后即可移除。

### 安全

- **在所有文件系统路径位置校验股票代码路径遍历。** 覆盖缓存、检查点数据库和结果目录，
  防止恶意股票代码逃逸出预期目录。（#618）

## [0.2.4] — 2026-04-25

### 新增

- **结构化输出决策智能体。** 研究经理、交易员和投资组合经理现在在主要调用中使用
  `llm.with_structured_output(Schema)`，并返回类型化 Pydantic 实例。各供应商使用
  原生结构化输出模式（OpenAI / xAI 使用 `json_schema`，Gemini 使用
  `response_schema`，Anthropic 使用工具调用，OpenAI 兼容供应商使用函数调用）。
  渲染辅助函数保留现有 Markdown 形状，确保记忆日志、CLI 显示和保存报告不变。（#434）
- **LangGraph 检查点恢复**——通过 `--checkpoint` 选择启用。每个节点后保存状态，
  崩溃或中断时可从最后一个成功步骤恢复。当前统一保存于 PostgreSQL；旧版本曾使用
  每个代码独立的本地文件数据库，`--clear-checkpoints` 可重置它们。（#594）
- **持久化决策日志**替代每个智能体的 BM25 记忆。决策会在 `propagate()` 末尾自动保存；
  下一次同代码运行会用实际收益、相对 SPY 的 Alpha 和一段反思更新之前的待处理条目。
  可通过 `TRADINGAGENTS_MEMORY_LOG_PATH` 覆盖路径；可选的
  `memory_log_max_entries` 配置限制已完成条目数量，待处理条目永不清理。（#578，#563，#564，#579）
- **DeepSeek、Qwen（阿里云 DashScope）、GLM（智谱）和 Azure OpenAI** 供应商，
  并支持动态选择 OpenRouter 模型。
- **Docker 支持**——提供独立开发和运行镜像的多阶段构建。
- **`scripts/smoke_structured_output.py`**——针对任意供应商检查三个结构化输出智能体，
  让贡献者可以用一条命令验证配置。
- **五级评级尺度**（Buy / Overweight / Hold / Underweight / Sell）由研究经理、
  投资组合经理、信号处理器和记忆日志统一使用；交易员保留三级（Buy / Hold / Sell），
  因为交易方向天然是三值的。
- **Pytest 测试夹具**——延迟导入 LLM 客户端并提供占位 API 密钥，确保测试套件无需凭据即可运行。
  （#588）

### 变更

- **`backend_url` 默认值现在是 `None`**，不再是 OpenAI URL。每个供应商客户端
  会回退到自身默认值，避免用户切换供应商却未覆盖 `backend_url` 时产生错误请求 URL。
  CLI 流程不受影响。
- 所有文件 I/O 都显式传入 `encoding="utf-8"`，Windows 用户不再因 cp1252 默认编码
  遇到 `UnicodeEncodeError`。（#543，#550，#576）
- 缓存和日志目录移至 `~/.tradingagents/`，以解决 Docker 权限问题。（#519）
- `SignalProcessor` 通过确定性启发式从投资组合经理渲染的 Markdown 中读取评级，
  不再额外调用 LLM。
- OpenAI 结构化输出调用默认使用 `method="function_calling"`，避免
  langchain-openai Responses API 解析路径产生嘈杂的 `PydanticSerializationUnexpectedValue`
  警告；类型化结果不变且无警告。

### 修复

- 空记忆不再触发智能体提示词中的虚构历史经验；记忆日志重构从结构上杜绝了该问题，
  因为只有投资组合经理会在存在条目时查询记忆。（#572）
- 工具调用日志处理每个块消息，而不只是最后一条；记忆得分归一化也能处理空得分数组。
  （#534，#531）

### 移除

- `FinancialSituationMemory`（每个智能体的 BM25 系统）和无效的
  `reflect_and_remember()` 连接逻辑；其功能已由持久化决策日志接替。
- 导致 `langchain-google-genai` 更改 API 路径后返回 404 的硬编码 Google 端点。
  （#493，#496）

### 贡献者

感谢所有通过代码、设计和报告参与塑造此版本的人：

- [@claytonbrown](https://github.com/claytonbrown) — 检查点恢复（#594）、测试夹具（#588）、成本统计设计反馈（#582）和结构化校验（#583）
- [@Bcardo](https://github.com/Bcardo) — 记忆日志重构（#579）、空记忆幻觉报告（#572）和编码修复提案（#570）
- [@voidborne-d](https://github.com/voidborne-d) — 记忆持久化设计（#564）和投资组合经理状态修复（#503）
- [@mannubaveja007](https://github.com/mannubaveja007) — 结构化输出功能请求（#434）
- [@kelder66](https://github.com/kelder66) — 仅内存存储问题（#563）
- [@Gujiassh](https://github.com/Gujiassh) — 工具调用日志修复（#534）和测试伪实现 PR（#533）
- [@iuyup](https://github.com/iuyup) — 记忆得分归一化修复（#531）
- [@kaihg](https://github.com/kaihg) — Google base_url 修复（#496）
- [@32ryh98yfe](https://github.com/32ryh98yfe) — Gemini 404 报告（#493）
- [@uppb](https://github.com/uppb) — OpenRouter 动态模型选择（#482）
- [@guoz14](https://github.com/guoz14) — OpenRouter 模型限制报告（#337）
- [@samchenku](https://github.com/samchenku) — 指标名称规范化（#490）
- [@JasonOA888](https://github.com/JasonOA888) — y_finance pandas 导入修复（#488）
- [@tiffanychum](https://github.com/tiffanychum) — 过期导入清理（#499）
- [@zaizou](https://github.com/zaizou) — Docker 权限问题（#519）
- [@Stosman123](https://github.com/Stosman123)、[@mauropuga](https://github.com/mauropuga)、[@hotwind2015](https://github.com/hotwind2015) — Windows 编码错误报告（#543、#550、#576）
- [@nnishad](https://github.com/nnishad)、[@atharvajoshi01](https://github.com/atharvajoshi01) — 编码修复提案（#568、#549）

## [0.2.3] — 2026-03-29

### 新增

- **多语言输出**用于分析师报告和最终决策，并提供 CLI 选择器。智能体内部辩论保留英文
  以保证推理质量。（#472）
- **GPT-5.4 系列模型**加入默认目录，并区分深度/快速模型。
- **统一模型目录**作为 CLI 选项和供应商校验的唯一事实来源。

### 变更

- `base_url` 会转发给 Google 和 Anthropic 客户端，使企业代理在不同供应商间
  一致工作。（#427）
- 将 Google 的 `api_key` 参数统一为 `api_key` 形式。

### 修复

- 当 `curr_date` 位于获取窗口中间时，回测数据获取器不再泄漏未来数据。（#475）
- LLM 返回的无效指标名称会在工具边界捕获，而不是导致运行崩溃。（#429）
- yfinance 新闻获取器与价格获取器一样遵循指数退避重试。（#445）

### 贡献者

- [@ahmedk20](https://github.com/ahmedk20) — 多语言输出（#472）
- [@CadeYu](https://github.com/CadeYu) — 模型目录类型定义（#464）
- [@javierdejesusda](https://github.com/javierdejesusda) — 统一 Google API 密钥参数（#453）
- [@voidborne-d](https://github.com/voidborne-d) — yfinance 新闻重试（#445）
- [@kostakost2](https://github.com/kostakost2) — 未来数据偏差报告（#475）
- [@lu-zhengda](https://github.com/lu-zhengda) — 代理/base_url 支持请求（#427）
- [@VamsiKrishna2021](https://github.com/VamsiKrishna2021) — 无效指标崩溃报告（#429）

## [0.2.2] — 2026-03-22

### 新增

- **五级评级尺度**（Buy / Overweight / Hold / Underweight / Sell）引入投资组合经理。
- **Anthropic effort 等级**支持 Claude 模型。
- **OpenAI Responses API** 路径支持原生 OpenAI 模型。

### 变更

- `risk_manager` 重命名为 `portfolio_manager`，以匹配 CLI 显示的角色描述。
- 交易所限定的股票代码（例如 `7203.T`、`BRK.B`）在所有智能体提示词和工具调用中保留。
- 尝试设置进程级 UTF-8 默认值以保证跨平台一致性（注意：该方法实际未生效；
  v0.2.4 已改为每次调用显式传入 `encoding="utf-8"` 参数）。

### 修复

- yfinance 限流错误会使用指数退避重试。（#426）
- HTTP 客户端支持需要自定义证书包的环境配置 SSL。（#379）
- 报告章节写入可以优雅处理字符串列表内容。

### 贡献者

- [@CadeYu](https://github.com/CadeYu) — 保留带交易所限定的股票代码（#413）
- [@yang1002378395-cmyk](https://github.com/yang1002378395-cmyk) — HTTP 客户端 SSL 自定义（#379）

## [0.2.1] — 2026-03-15

### 安全

- 修复 `langchain-core` 漏洞（LangGrinch）。（#335）
- 移除受 CVE-2026-22218 影响的 `chainlit` 依赖。

### 新增

- `pyproject.toml` 构建系统配置；项目现在可通过现代打包工具安装。

### 移除

- `setup.py` — 依赖已集中到 `pyproject.toml`。

### 修复

- 风险管理读取正确的基本面报告来源。（#341）
- 所有 `open()` 调用显式使用 UTF-8 编码（初始版本）。
- `get_indicators` 工具支持处理 LLM 返回的逗号分隔指标名称。（#368）
- `Propagation` 初始化所有辩论状态字段，风险辩手不会再看到缺失的键。
- 股票数据解析可以容忍格式错误的 CSV 和 NaN 值。
- 条件辩论逻辑遵循配置的轮数。（#361）

### 贡献者

- [@RinZ27](https://github.com/RinZ27) — `langchain-core` 安全补丁（#335）
- [@Ljx-007](https://github.com/Ljx-007) — 风险管理基本面报告修复（#341）
- [@makk9](https://github.com/makk9) — 辩论轮数配置问题（#361）

## [0.2.0] — 2026-02-04

这是自初始公开版本以来规模最大的发布版本。框架从单供应商架构升级为多供应商
架构，并增加了多个可用于生产的功能面。

### 新增

- **多供应商 LLM 支持**（OpenAI、Google、Anthropic、xAI、OpenRouter、Ollama），
  通过工厂模式接入，并支持供应商专属的思考配置。
- **Alpha Vantage** 集成作为可配置的主数据供应商，以 yfinance 作为社区稳定性备用来源。
- **CLI 页脚统计**：通过 LangChain 回调实时跟踪 LLM 调用、工具调用和 token 使用量。
- **分析后保存报告**——运行完成时，框架写入分章节 Markdown 文件
  （分析师报告、辩论记录和最终决策）。
- **公告面板**——从 `api.tauric.ai/v1/announcements` 获取 CLI 欢迎屏幕的更新。
- **工具回退**，单个供应商中断不会停止流水线。

### 变更

- 为与显示的智能体标签一致，Risky / Safe 风险辩手重命名为
  **Aggressive / Conservative**。
- 默认数据供应商调整，以平衡社区部署中的可靠性和配额。
- 更新 Ollama 和 OpenRouter 模型列表，并明确默认端点。

### 修复

- 实时显示中的分析师状态跟踪和消息去重。
- 智能体循环中的无限循环保护，并强化反思与日志记录。
- 修复多个数据供应商实现错误和工具签名不匹配问题。

### 贡献者

这是首次获得大量外部贡献的版本；许多来自 2025 年末社区的 PR 也在此版本合入。

- [@luohy15](https://github.com/luohy15) — Alpha Vantage 数据供应商集成（#235）
- [@EdwardoSunny](https://github.com/EdwardoSunny) — yfinance 获取优化（#245）
- [@Mirza-Samad-Ahmed-Baig](https://github.com/Mirza-Samad-Ahmed-Baig) — 无限循环保护、反思和日志修复（#89）
- [@ZeroAct](https://github.com/ZeroAct) — 保存结果路径支持（#29）
- [@Zhongyi-Lu](https://github.com/Zhongyi-Lu) — `.env` gitignore 配置（#49）
- [@csoboy](https://github.com/csoboy) — 本地 Ollama 设置（#53）
- [@chauhang](https://github.com/chauhang) — 首次 Docker 支持尝试（#47，后续回滚；合入的 Docker 支持在 v0.2.4 发布）

## [0.1.1] — 2025-06-07

### 移除

- 随 v0.1.0 打包的静态网站资源；公共网站现在独立维护。

## [0.1.0] — 2025-06-05

### 新增

- TradingAgents 多智能体交易框架的**首次公开发布**：市场、情绪、新闻和基本面分析师；
  看多与看空研究员；交易员；激进、保守和中性风险辩手；投资组合经理。
  支持 LangGraph 编排、yfinance 数据、每个智能体的 BM25 记忆、单供应商 OpenAI
  集成以及交互式 CLI。

[0.2.4]: https://github.com/TauricResearch/TradingAgents/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/TauricResearch/TradingAgents/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/TauricResearch/TradingAgents/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/TauricResearch/TradingAgents/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/TauricResearch/TradingAgents/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/TauricResearch/TradingAgents/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/TauricResearch/TradingAgents/releases/tag/v0.1.0
