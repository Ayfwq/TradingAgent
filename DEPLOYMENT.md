# TradingAgents 部署说明

本文档适用于中国大陆的 Ubuntu 22.04 / 24.04 服务器。项目使用 `uv` 锁定 Python 依赖，并通过 Docker Compose 运行 Web 服务与 AI 资讯采集 Worker。

## 仓库中应该提交的内容

- 源代码、测试和文档
- `pyproject.toml` 与 `uv.lock`（保证依赖可复现）
- `Dockerfile`、`docker-compose.yml`、`.dockerignore`
- `.env.example` 与 `.env.enterprise.example`（只保留空值和示例）
- Web 前后端代码

## 不应该提交的内容

- `.env`、`.env.production` 和任何真实 API Key
- 私钥、证书、SSH 密钥
- `.venv`、缓存、构建产物
- 运行日志、研报、SQLite 检查点和 memory log
- 用户数据以及本地编辑器配置
- AI 资讯数据库（`news.db`，位于数据目录）

相关规则已写入 `.gitignore` 和 `.dockerignore`。

## 阿里云镜像约束

Dockerfile 的构建下载仅使用：

- 阿里云官方 AC2 Python 3.12 基础镜像
- `https://mirrors.aliyun.com/pypi/simple/` Python 包镜像

`uv.lock` 同样应由上述索引生成。请勿把 Dockerfile 的基础镜像改回 Docker Hub，也不要增加额外 Python 索引，否则会破坏“仅阿里源”的构建约束。

## 首次部署

```bash
git clone https://github.com/Ayfwq/TradingAgent.git
cd TradingAgent
cp .env.example .env
```

编辑 `.env`，至少填写一个模型供应商的 API Key，并设置对应模型。例如：

```dotenv
OPENAI_API_KEY=替换为真实密钥
TRADINGAGENTS_LLM_PROVIDER=openai
TRADINGAGENTS_DEEP_THINK_LLM=gpt-5.5
TRADINGAGENTS_QUICK_THINK_LLM=gpt-5.4-mini
TRADINGAGENTS_OUTPUT_LANGUAGE=Chinese
TRADINGAGENTS_WEB_PORT=8000
```

中国大陆数据源可使用：

```dotenv
TRADINGAGENTS_DATA_VENDORS={"core_stock_apis":"akshare","technical_indicators":"akshare","fundamental_data":"akshare","news_data":"akshare","macro_data":"akshare"}
```

构建并启动：

```bash
docker compose build
docker compose up -d
docker compose ps
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/news/health
```

浏览器访问 `http://服务器公网IP:5000`。请在阿里云安全组中只开放实际需要的端口。

启动后 Compose 会同时拉起两个服务：

- `tradingagents`：FastAPI Web（股票研报 + AI 资讯页面 `/news`）；
- `news-worker`：AI 资讯采集 Worker，共用 `tradingagents_data` 卷，每 15 分钟采集一轮。

## 更新部署

```bash
git pull --ff-only
docker compose build
docker compose up -d --remove-orphans
docker image prune -f
```

## 运维命令

```bash
docker compose logs -f --tail=200
docker compose logs -f --tail=200 news-worker
docker compose restart
docker compose down
```

持久数据保存在 Docker 卷 `tradingagents_data` 中。普通更新或重新构建镜像不会删除该卷。

# AI 资讯模块

独立于股票分析的后台资讯采集与展示模块。实现细节见 `AI_NEWS_MODULE_PLAN.md`，代码位于 `web/news/`，入口 `web/news_worker.py`，测试 `tests/test_news_*.py`。

## 本地运行

开发模式（两个终端）：

```bash
# 终端 1：Web 服务（含 /news 页面与只读 API）
uv run uvicorn web.app:app --host 127.0.0.1 --port 5000

# 终端 2：采集 Worker（启动立即抓一次，此后每 15 分钟一轮）
uv run python -m web.news_worker
```

快速验证（只抓一轮）：

```bash
uv run python -m web.news_worker --once
```

本地数据库默认位于 `~/.tradingagents/news/news.db`（Docker 内为 `/data/news/news.db`），不写入 Git。启动后 2 分钟内完成首次采集；浏览器打开 `http://127.0.0.1:5000/news`。

验收模式与生产一致：`docker compose up -d` 后访问 `/news`。

## 配置项（环境变量）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `NEWS_ENABLED` | `true` | 总开关（false 时 Worker 待机、页面显示历史数据） |
| `NEWS_FETCH_INTERVAL_MINUTES` | `15` | 采集间隔，允许 10～30 |
| `NEWS_REQUEST_TIMEOUT_SECONDS` | `10` | 单请求连接/读取超时 |
| `NEWS_MAX_RESPONSE_BYTES` | `2097152` | 单响应大小上限（2 MB） |
| `NEWS_MAX_CONCURRENCY` | `4` | 来源并发数 |
| `NEWS_MAX_ENTRIES_PER_FETCH` | `200` | 单来源单轮最多入库条数 |
| `NEWS_RETENTION_DAYS` | `90` | 数据保留天数（自动清理） |
| `NEWS_AI_SUMMARY_ENABLED` | `true` | AI 中文摘要开关 |
| `NEWS_AI_MAX_ITEMS_PER_RUN` | `30` | 每轮最多 AI 摘要条数（费用上限） |
| `NEWS_DATABASE_PATH` | 见上 | SQLite 路径 |
| `NEWS_AI_PROVIDER` / `NEWS_AI_MODEL` / `NEWS_AI_BASE_URL` | 空 | 可选专用摘要端点；不设则复用 `TRADINGAGENTS_LLM_*` |
| `NEWS_SOURCES` | 空 | 逗号分隔的来源 ID，覆盖默认启停列表 |

AI 摘要失败（无 Key、403、超时、返回非法 JSON）会自动降级为清洗后的 RSS 摘要，采集与展示不受影响。

## ECS 部署要点

- Worker 与 Web 使用同一镜像，仅启动命令不同（`python -m web.news_worker`）；
- 两个服务共用 `tradingagents_data` 卷，`restart: unless-stopped`，非 root 用户 + `no-new-privileges`；
- Worker 健康检查：`python -m web.news_worker --health`（心跳超过 3 倍间隔未更新则判为不健康）；
- 部署后先观察 24 小时（`docker compose logs news-worker`），再考虑扩大来源；
- 英文来源依赖海外网络，ECS 出网不稳定时中文源（量子位、IT之家、InfoQ）仍可工作。

## 排障

| 现象 | 排查 |
|---|---|
| 页面"等待首轮采集" | `docker compose logs news-worker`；本地跑 `--once` 看具体错误 |
| 某来源连续失败 | `/news` 页面底部"数据源状态"面板查看最近错误；单个来源故障不影响其他来源 |
| AI 摘要为 RSS 文案 | 检查模型 Key 与端点；确认 `NEWS_AI_SUMMARY_ENABLED=true` |
| 数据库锁冲突 | 已启用 WAL + busy_timeout；确认只有一个 Worker 实例在写 |
| 采集到无关内容 | 综合源（IT之家等）依赖关键词过滤，可调整 `web/news/config.py` 的 `RELEVANCE_KEYWORDS` |

## 数据库备份与恢复

```bash
# 备份（容器内热备，SQLite WAL 模式下安全）
docker compose exec news-worker sqlite3 /data/news/news.db \
  ".backup /data/news/backup-$(date +%F).db"
# 导出宿主机
docker cp $(docker compose ps -q news-worker):/data/news/ /srv/backup/
# 恢复：停止 Worker，替换 news.db 后重启
docker compose stop news-worker
docker cp /srv/backup/news.db $(docker compose ps -q news-worker):/data/news/news.db
docker compose start news-worker
```

本地环境把路径替换为 `~/.tradingagents/news/news.db` 即可。资讯数据可随时重新采集，丢失不致命。

## 来源与关键词维护

- 来源清单（含备用源）在 `web/news/config.py` 的 `CORE_SOURCES` / `BACKUP_SOURCES`；
- 新增来源须满足准入规则（HTTPS、免登录、不绕过反爬、允许聚合读取），先在 `BACKUP_SOURCES` 灰度观察；
- 分类关键词在 `CATEGORY_KEYWORDS`，综合源过滤词在 `RELEVANCE_KEYWORDS`，热度加权词在 `HOT_TERMS`；
- 修改后重启 Worker 生效；相关行为由 `tests/test_news_pipeline.py` 覆盖。

