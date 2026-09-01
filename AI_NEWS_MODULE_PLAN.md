# TradingAgents AI 资讯模块实施规划

> 文档状态：可进入实施  
> 编制日期：2026-08-30  
> 首版目标：本地完整运行，并可平滑部署到阿里云 ECS 进行 24 小时采集

## 1. 项目结论与完成把握

在本规划限定的 MVP 范围内，项目具备明确的数据源、技术路径、降级方案和验收标准，完成把握为 **95%**。

这里的“完成”是指：

- 至少 6 个核心来源可以持续采集，单个来源故障不会中断系统；
- 每 15 分钟自动检查新资讯，不要求浏览器保持打开；
- 资讯可以完成去重、分类、中文摘要、标签提取和持久化；
- 网页能够按时间和分类浏览，并可跳转至原文；
- AI 服务不可用时仍能使用 RSS 摘要和规则分类继续运行；
- 本地经过持续运行验证后，可以通过 Docker Compose 部署到阿里云 ECS；
- 有来源健康状态、错误日志和失败恢复机制。

剩余约 5% 的不确定性主要来自第三方平台未来可能改版、临时封禁、网络波动或停止提供 RSS。这不是代码本身无法完成的问题，将通过多来源、来源隔离、自动降级和健康检查降低影响。

## 2. 首版范围

### 2.1 必须实现

1. 独立的“AI 资讯”页面，并加入现有网站导航。
2. 后台定时采集 RSS/API，默认间隔 15 分钟，可配置为 10～30 分钟。
3. 保存标题、摘要、来源、发布时间、原文链接、分类、标签和抓取时间。
4. 按原文链接和标题指纹去重。
5. 使用简单规则完成相关性过滤和分类。
6. 可选调用现有模型配置生成中文摘要和标签。
7. AI 调用失败时自动退回 RSS 摘要，不影响采集。
8. 页面支持分类筛选、分页/继续加载、自动刷新和原文跳转。
9. 提供来源状态：最后成功时间、耗时、连续失败次数和最近错误。
10. 支持本地运行和 Docker Compose/ECS 常驻运行。

### 2.2 首版不做

- 不抓取付费墙后的正文；
- 不绕过验证码、登录、Cloudflare 或其他反爬机制；
- 不将 Web Search 作为主要采集渠道；
- 不做复杂推荐算法和用户画像；
- 不直接根据新闻生成买卖建议；
- 不引入 React、Next.js、Celery、Redis 或独立向量数据库；
- 不追求毫秒级实时，采集目标是 10～30 分钟级更新。

## 3. 资讯分类

首版使用 5 个主分类，无法确定时进入内部“其他”分类：

| 分类 | 典型内容 | 示例标签 |
|---|---|---|
| 模型与技术 | 模型发布、算法、论文、多模态、智能体 | GPT、Gemini、Agent、推理 |
| 产品与开源 | AI 产品、开发工具、开源模型与项目 | GitHub、Hugging Face、SDK |
| 芯片与算力 | GPU、AI 芯片、云计算、数据中心 | NVIDIA、昇腾、CUDA、算力 |
| 公司与资本 | 公司动态、融资、并购、合作、财报 | 公司名、股票代码、融资轮次 |
| 政策与安全 | 政府政策、监管、版权、数据与模型安全 | 网信办、欧盟、版权、合规 |

分类和股票板块分开处理。行业、公司和股票代码作为标签保存，以便后续增加“只看可能影响股票的资讯”等筛选条件。

## 4. 数据源方案与网络验证

### 4.1 核心来源

2026-09-01 已从当前开发环境重新进行只读 HTTPS 请求测试。鉴于项目用于 A 股分析，默认来源改为“国内官方政策 + A 股主流财经媒体 + 国内 AI 专业媒体”为主，海外官方/权威源用于补充全球产业链，综合聚合源不默认启用。

| 来源 | 地址 | 实测状态 | 首版角色 |
|---|---|---:|---|
| 工业和信息化部·工信动态 | 官方 RSS API | HTTP 200 | AI、机器人、智能制造及信息产业政策 |
| 工业和信息化部·征求意见 | 官方 RSS API | HTTP 200 | 人形机器人、脑机接口等产业标准前瞻信号 |
| 财联社·A股电报 | `https://www.cls.cn/v1/roll/get_roll_list` | HTTP 200 | A 股公司、产业链和快讯 |
| 东方财富·7×24 | `https://np-weblist.eastmoney.com/comm/web/getFastNewsList` | HTTP 200 | 上市公司公告摘要与盘中资讯 |
| 中国新闻网·财经/即时 | `https://www.chinanews.com.cn/rss/finance.xml` | HTTP 200 | 中央媒体财经与产业新闻 |
| InfoQ 中文 | `https://www.infoq.cn/feed` | HTTP 200 | 中文专业媒体 |
| 量子位 | `https://www.qbitai.com/feed` | HTTP 200 | 中文 AI 专业媒体 |
| OpenAI | `https://openai.com/news/rss.xml` | HTTP 200 | 官方模型与产品源 |
| Google AI | `https://blog.google/technology/ai/rss/` | HTTP 200 | 官方 AI 产品源 |
| Google DeepMind | `https://deepmind.google/blog/rss.xml` | HTTP 200 | 官方研究与模型源 |
| Hugging Face | `https://huggingface.co/blog/feed.xml` | HTTP 200 | 开源模型与生态源 |
| NVIDIA | `https://developer.nvidia.com/blog/category/generative-ai/feed/` | HTTP 200 | 芯片、算力和开发源 |
| TechCrunch AI | `https://techcrunch.com/category/artificial-intelligence/feed/` | HTTP 200 | 公司、产品和资本媒体源 |
| Google Research | `https://research.google/blog/rss/` | HTTP 200 | 官方研究源 |
| Microsoft 官方博客 | `https://blogs.microsoft.com/feed/` | HTTP 200 | 官方发布，需 AI 关键词过滤 |
| Microsoft Research | `https://www.microsoft.com/en-us/research/feed/` | HTTP 200 | 官方研究源，需 AI 关键词过滤 |
| AWS Machine Learning | `https://aws.amazon.com/blogs/machine-learning/feed/` | HTTP 200 | 官方机器学习源 |
| Nature · Machine Learning | `https://www.nature.com/subjects/machine-learning.rss` | HTTP 200 | 学术期刊来源 |
| MIT Technology Review · AI | `https://www.technologyreview.com/topic/artificial-intelligence/feed/` | HTTP 200 | 权威科技媒体 |
| BBC Technology | `https://feeds.bbci.co.uk/news/technology/rss.xml` | HTTP 200 | 权威新闻媒体，需 AI 关键词过滤 |
| The Guardian · AI | `https://www.theguardian.com/technology/artificialintelligenceai/rss` | HTTP 200 | 主流新闻媒体 |

### 4.2 备用/发现来源

| 来源 | 地址 | 用途 |
|---|---|---|
| IT之家 | `https://www.ithome.com/rss/` | 综合聚合备用源；默认禁用 |
| 开源中国 | `https://www.oschina.net/news/rss` | 中文开源资讯备用源 |
| VentureBeat AI | `https://venturebeat.com/category/ai/feed` | 海外行业媒体备用源 |
| Hacker News Algolia | `https://hn.algolia.com/api/v1/search_by_date` | 热点发现；默认降低权重 |

### 4.3 暂不采用

| 来源 | 实测情况 | 处理决定 |
|---|---|---|
| NewsNow 公共实例 | 本次请求返回 HTTP 403 | 不作为首版依赖 |
| Microsoft AI 旧 RSS | 返回 HTTP 410 | 使用主站 RSS 作为备用 |
| 机器之心 RSS | 跳转为普通 HTML 页面 | 暂不做易失效的页面解析 |
| AIbase | 仅返回 HTML 页面 | 暂不采用 |
| 36氪 Feed | 返回 HTML 而非标准 Feed | 暂不采用 |
| arXiv cs.AI | RSS 可达但本次无新条目 | 后续作为论文模块考虑 |

### 4.4 来源准入规则

新增来源必须同时满足：

1. 使用 HTTPS；
2. 在当前网络或 ECS 网络可访问；
3. 可稳定获得标题、发布时间和原文链接；
4. 优先采用官方 RSS、Atom 或公开 API；
5. 不需要登录、验证码或绕过反爬措施；
6. 单次失败不会阻塞其他来源；
7. 来源协议和使用方式允许合理频率的聚合读取。

## 5. 系统架构

```text
定时调度器（默认每 15 分钟）
              │
              ▼
      RSS / Atom / API 适配器
              │
              ▼
  字段标准化、时间转换、URL 规范化
              │
              ▼
     AI 相关性过滤与两级去重
              │
              ▼
  规则分类、标签提取、可选 AI 摘要
              │
              ▼
        SQLite（WAL 模式）
              │
              ▼
          FastAPI 接口
              │
              ▼
      独立 AI 资讯网页
```

### 5.1 进程划分

- `web`：现有 FastAPI 服务，负责页面和只读 API；
- `news-worker`：独立后台进程，负责定时抓取、处理和写入；
- 两个进程使用同一个持久化数据目录；
- Worker 是否运行不影响现有股票分析功能；
- 页面关闭后 Worker 仍然持续采集。

独立 Worker 可以避免未来 Web 服务开启多个 Uvicorn worker 时重复执行定时任务。

### 5.2 建议目录结构

```text
web/
  news/
    __init__.py
    config.py             # 来源与调度配置
    models.py             # 数据模型
    repository.py         # SQLite 存取
    pipeline.py           # 标准化、过滤、去重、分类、摘要
    scheduler.py          # 定时运行与重试
    sources/
      base.py
      feed.py             # RSS/Atom 通用适配器
      hacker_news.py      # API 适配器（备用）
  news_worker.py          # Worker 启动入口
  static/
    news.html
    news.js
    news.css
tests/
  test_news_repository.py
  test_news_pipeline.py
  test_news_sources.py
  test_news_api.py
```

若现有静态资源更适合复用，也可将新闻页面样式合并到当前 `styles.css`，避免重复维护。

## 6. 数据模型

### 6.1 `news_items`

| 字段 | 说明 |
|---|---|
| `id` | 内部唯一 ID |
| `source_id` | 来源标识 |
| `source_name` | 来源展示名称 |
| `title` | 原始标题 |
| `summary` | 中文短摘要 |
| `original_summary` | RSS/API 原始摘要 |
| `url` | 原文链接 |
| `canonical_url` | 去除追踪参数后的链接 |
| `published_at` | 原始发布时间，统一存 UTC |
| `fetched_at` | 抓取时间 |
| `category` | 五个主分类之一 |
| `tags_json` | 公司、股票、产品和技术标签 |
| `language` | 内容语言 |
| `title_hash` | 标题去重指纹 |
| `content_hash` | 内容去重指纹 |
| `importance_score` | 0～100 热度/重要性 |
| `summary_status` | 规则摘要、AI 摘要或失败降级 |

### 6.2 `news_sources`

保存来源配置及健康状态：

- 是否启用；
- 抓取间隔；
- 最后尝试时间；
- 最后成功时间；
- 最近耗时；
- 连续失败次数；
- 最近错误；
- `ETag` 和 `Last-Modified`；
- 最近成功读取的条目数量。

### 6.3 `fetch_runs`

保存每次采集运行的来源、开始/结束时间、新增数量、重复数量、过滤数量和错误，用于排查 24 小时运行问题。

## 7. 处理链路

### 7.1 抓取

- 启动后立即执行一次，此后按配置间隔执行；
- 各来源增加少量随机抖动，避免同一秒集中请求；
- 默认连接/读取总超时 10 秒；
- 失败重试 2 次，使用指数退避；
- 单次响应限制为 2 MB；
- 使用 `ETag`/`Last-Modified` 减少无效下载；
- 每个来源独立处理并记录结果。

### 7.2 标准化

- 将 RSS、Atom 和 JSON 统一为内部模型；
- 所有时间存为 UTC，前端显示为 `Asia/Shanghai`；
- 清除 URL 的 `utm_*` 等追踪参数；
- 清除摘要中的脚本、样式和危险 HTML；
- 保留来源名称和原文链接，不复制完整正文。

### 7.3 相关性过滤

综合来源类型和关键词判断是否属于 AI 资讯：

- AI 垂直来源默认通过；
- 综合科技来源必须命中 AI/模型/芯片/算力等关键词；
- 明显无关内容直接过滤；
- 过滤原因写入运行统计，方便调整规则。

### 7.4 去重

1. `canonical_url` 完全一致时直接判重；
2. 规范化标题后计算指纹；
3. 标题高度相似且发布时间接近时合并为同一事件；
4. 多来源报道同一事件时保留主条目，并累计来源数量用于热度计算。

### 7.5 分类与标签

- 首先使用可解释的关键词和来源规则；
- 规则无法确定时再调用 AI；
- AI 返回必须经过固定 JSON Schema 校验；
- 分类失败进入“其他”，不能阻塞入库；
- 公司和股票代码只在有足够证据时生成，不做猜测。

### 7.6 摘要

摘要目标为 60～120 个中文字符，说明“发生了什么”和“为什么值得关注”，不生成投资建议。

降级顺序：

1. AI 中文摘要；
2. 清洗后的 RSS 原始摘要；
3. 标题加来源说明。

同一条新闻只摘要一次，避免重复调用和费用失控。AI 调用只处理新条目，并设置每轮最大调用数量。

### 7.7 热度

首版不使用复杂模型，采用可解释评分：

- 新鲜度：50%；
- 同一事件的来源数量：25%；
- 来源权重：15%；
- 是否涉及重点公司、政策或芯片：10%。

默认页面仍按发布时间排序，热度用于“热门”筛选和同类资讯排序。

## 8. API 设计

### `GET /api/news`

参数：

- `category`：分类；
- `source`：来源；
- `q`：标题/摘要关键词；
- `since`：起始时间；
- `limit`：每页数量，默认 30，最大 100；
- `cursor`：游标分页。

返回资讯列表及下一页游标。

### `GET /api/news/categories`

返回分类名称、条目数量和最近更新时间。

### `GET /api/news/sources`

返回公开的来源健康信息，不返回内部堆栈或敏感配置。

### `GET /api/news/health`

供 Docker/ECS 健康检查使用，判断数据库、最近抓取和 Worker 心跳是否正常。

首版不提供由网页调用的“任意 URL 抓取”或“手动添加来源”接口。

## 9. 页面设计

页面沿用现有网站视觉风格，不引入新的前端框架。

### 页面结构

1. 网站导航：股票分析 / AI 资讯；
2. 页面标题及最近更新时间；
3. 五个分类筛选标签；
4. 可选来源筛选和关键词搜索；
5. 资讯卡片列表；
6. 数据源状态入口；
7. 加载更多或游标分页。

### 资讯卡片

显示：

- 标题；
- 60～120 字摘要；
- 来源；
- 北京时间；
- 分类及少量标签；
- “查看原文”按钮；
- 多来源报道数量（如有）。

原文使用新窗口打开，并设置 `rel="noopener noreferrer"`。页面每 60 秒读取一次本地 API；真正的外部抓取由后台 Worker 执行。

## 10. 安全设计

1. 外部请求只允许配置文件中的 HTTPS 域名；
2. 每次重定向后重新校验协议、主机名和最终地址；
3. 禁止请求本机、内网地址、云元数据地址和任意用户输入 URL，防止 SSRF；
4. 不执行目标网页 JavaScript，不携带用户 Cookie；
5. 限制下载大小、超时、并发数和重试次数；
6. 标题和摘要在服务端清洗、前端转义，防止 XSS；
7. AI 将新闻内容视为不可信输入，不执行内容中的指令或工具调用；
8. 日志不得记录 API Key、完整环境变量或敏感响应头；
9. ECS 容器继续使用非 root 用户和 `no-new-privileges`；
10. 遵循合理抓取频率，优先使用明确用于聚合的 RSS/Atom/API。

## 11. 配置建议

建议使用环境变量控制运行参数：

```text
NEWS_ENABLED=true
NEWS_FETCH_INTERVAL_MINUTES=15
NEWS_REQUEST_TIMEOUT_SECONDS=10
NEWS_MAX_RESPONSE_BYTES=2097152
NEWS_MAX_CONCURRENCY=4
NEWS_RETENTION_DAYS=90
NEWS_AI_SUMMARY_ENABLED=true
NEWS_AI_MAX_ITEMS_PER_RUN=30
NEWS_DATABASE_PATH=/data/news/news.db
```

来源列表、关键词和来源权重使用项目内 YAML/JSON 配置，并提供安全默认值。API Key 继续使用现有模型配置机制，不写入仓库。

## 12. 本地与 ECS 运行

### 12.1 本地

支持两种方式：

- 开发模式：分别启动 FastAPI 和 `news-worker`；
- 验收模式：通过 Docker Compose 启动完整环境。

本地数据库放入可配置的数据目录，不写入 Git。SQLite 开启 WAL、忙等待和必要索引，适合“单 Worker 写、Web 读取”的模式。

### 12.2 阿里云 ECS

在现有 Compose 基础上增加 `news-worker` 服务：

- Web 和 Worker 使用同一镜像；
- 使用不同启动命令；
- 共用 `tradingagents_data` 数据卷；
- 两个服务均配置 `restart: unless-stopped`；
- 配置健康检查和日志轮转；
- 主机和容器时区显示按上海时间，数据库仍存 UTC；
- 部署后先观察 24 小时，再扩大来源数量。

如果未来运行多个 Web 实例或采集量显著增加，再评估 PostgreSQL；首版无需提前增加复杂度。

## 13. 测试与验收标准

### 13.1 自动化测试

- RSS、Atom、JSON 解析测试；
- 非法 XML、超时、403、410、空 Feed 测试；
- URL 规范化和 SSRF 校验测试；
- 标题及链接去重测试；
- 分类与关键词过滤测试；
- AI 成功、失败、超时和无 API Key 降级测试；
- SQLite 并发读写和分页测试；
- API 参数、排序和响应结构测试；
- HTML 转义和危险链接测试。

网络集成测试与普通单元测试分开，避免第三方短暂不可用导致本地测试全部失败。

### 13.2 功能验收

满足以下条件视为 MVP 完成：

1. 本地一条命令或明确的两个命令可以启动完整服务；
2. 启动后 2 分钟内完成首次采集；
3. 至少 6 个核心来源成功入库；
4. 页面能够显示标题、摘要、来源、北京时间、分类和原文链接；
5. 分类筛选和继续加载正常；
6. 同一链接不会重复入库；
7. AI Key 缺失或调用失败时页面仍能显示资讯；
8. 单个来源超时或返回错误时其他来源继续运行；
9. 来源状态页可以看到最近成功时间和错误；
10. 连续运行 12～24 小时无进程退出、无限重试或明显重复数据；
11. Docker 容器重启后数据库保留，Worker 自动恢复；
12. 现有股票分析和报告功能不受影响。

## 14. 实施阶段

### 阶段 A：采集与存储

- 建立数据模型和 SQLite Repository；
- 实现 RSS/Atom 通用适配器；
- 接入核心来源；
- 完成标准化、去重和来源状态记录；
- 编写解析与存储测试。

**完成标志：** 命令行运行一次即可稳定把新资讯写入数据库。

### 阶段 B：分类、摘要与调度

- 实现关键词相关性过滤；
- 实现五分类和标签；
- 接入可选 AI 摘要与降级；
- 实现独立 Worker、定时调度、重试和心跳。

**完成标志：** Worker 可持续运行，AI 故障不影响入库。

### 阶段 C：API 与网页

- 增加新闻查询、分类和来源状态 API；
- 增加独立资讯页面和网站导航；
- 完成分页、筛选、自动刷新和原文跳转；
- 适配桌面端与移动端布局。

**完成标志：** 用户可以从现有网站完整浏览和打开资讯。

### 阶段 D：稳定性与部署

- 完成异常、限流、安全和回归测试；
- 更新 Docker Compose；
- 本地持续运行 12～24 小时；
- 整理 ECS 部署、备份和排障说明。

**完成标志：** 达到第 13 节全部验收条件。

## 15. 风险与预案

| 风险 | 影响 | 预案 |
|---|---|---|
| 单个 RSS 改版或停用 | 少一个来源 | 来源隔离、健康检查、备用源 |
| ECS 到海外来源网络不稳定 | 部分英文资讯延迟 | 超时重试、保留中文源、部署后重新探测 |
| AI API 不可用或费用上升 | 无法生成新摘要 | RSS 摘要降级、调用上限、只处理新条目 |
| 多平台重复报道 | 页面重复 | URL + 标题两级去重、事件合并 |
| 综合源噪音较多 | 非 AI 内容进入 | 来源级关键词过滤与可调规则 |
| 新闻内容包含恶意指令或 HTML | AI/页面安全风险 | 不可信输入隔离、Schema 校验、HTML 清洗 |
| SQLite 锁竞争 | 短暂写入失败 | WAL、单写进程、忙等待、事务控制 |
| 容器重启 | 定时任务中断 | 持久化数据卷、自动重启、Worker 心跳 |

## 16. 当前不构成阻塞的待确认项

以下信息现在不需要提供，不会阻碍开始开发；可以在对应阶段使用默认值：

- 抓取间隔：默认 15 分钟；
- 页面样式：默认沿用现有网站；
- AI 模型：默认复用现有模型配置，未配置时自动降级；
- 数据保留：默认 90 天；
- ECS 域名、HTTPS 和防火墙信息：部署阶段再提供；
- 是否增加股票代码映射：首版先保留标签字段，后续再增强。

真正部署 ECS 时，需要用户提供服务器登录/部署方式、开放端口或反向代理方案以及最终域名；这些不影响本地版本开发和验收。

## 17. 最终交付物

- AI 资讯采集、处理、存储和查询代码；
- 独立 AI 资讯页面；
- 核心来源配置和健康检查；
- 自动化测试；
- Docker Compose Worker 配置；
- 本地运行说明；
- 阿里云 ECS 部署与排障说明；
- 数据库备份和恢复说明；
- 来源增删及关键词维护说明。
