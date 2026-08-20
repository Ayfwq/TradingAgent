# Only Alibaba Cloud infrastructure is used during the image build:
#   - the base image is from Alibaba Cloud's official AC2 artifact registry;
#   - uv itself and every Python dependency are downloaded from Aliyun PyPI.
# No Docker Hub, ghcr.io, pypi.org, or files.pythonhosted.org URL is used here.
ARG ALIYUN_PYPI=https://mirrors.aliyun.com/pypi/simple/
FROM ac2-registry.cn-hangzhou.cr.aliyuncs.com/ac2/base:ubuntu24.04-py312 AS builder

ARG ALIYUN_PYPI
ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=${ALIYUN_PYPI} \
    UV_DEFAULT_INDEX=${ALIYUN_PYPI} \
    UV_INDEX_STRATEGY=first-index \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

RUN python -m pip install --no-cache-dir --index-url "${ALIYUN_PYPI}" uv==0.11.8

WORKDIR /app

# Install locked third-party dependencies first so source-only changes reuse the
# expensive dependency layer. The project itself is installed after COPY . . .
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev --no-editable

FROM ac2-registry.cn-hangzhou.cr.aliyuncs.com/ac2/base:ubuntu24.04-py312 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    TRADINGAGENTS_RESULTS_DIR=/data/logs \
    TRADINGAGENTS_CACHE_DIR=/data/cache \
    TRADINGAGENTS_MEMORY_LOG_PATH=/data/memory/trading_memory.md \
    TRADINGAGENTS_MODEL_SETTINGS_DIR=/data/settings

RUN useradd --create-home --uid 10001 appuser \
    && install -d -m 0755 -o appuser -g appuser /app /data

WORKDIR /app
COPY --from=builder --chown=appuser:appuser /app /app

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"]

CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers"]
