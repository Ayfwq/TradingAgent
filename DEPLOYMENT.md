# TradingAgents 部署说明

本文档适用于中国大陆的 Ubuntu 22.04 / 24.04 服务器。项目使用 `uv` 锁定 Python 依赖，并通过 Docker Compose 运行 Web 服务。

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
```

浏览器访问 `http://服务器公网IP:5000`。请在阿里云安全组中只开放实际需要的端口。

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
docker compose restart
docker compose down
```

持久数据保存在 Docker 卷 `tradingagents_data` 中。普通更新或重新构建镜像不会删除该卷。
