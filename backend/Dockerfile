# 后端镜像：FastAPI + LangGraph Agent + RAG（Chroma / bge-small-zh）
#
# 在线安装：从 requirements.txt 装依赖，**干净 clone 即可构建**。
# 原实现 COPY wheels /wheels + --no-index，而 backend/wheels/ 被 .gitignore 忽略，
# 导致 README 里的 `docker compose up --build` 在 clone 后必然失败。
# 内网/离线构建请改用 Dockerfile.offline（需要本地准备 backend/wheels/）。
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 依赖层（利用层缓存）
COPY requirements.txt .
RUN pip install -r requirements.txt

# 应用代码
COPY app ./app
COPY config ./config
COPY scripts ./scripts

# 数据与模型目录由 volume 挂载（宿主机 data/、models/ 复用，避免容器内重新下载 embedding 模型）

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
