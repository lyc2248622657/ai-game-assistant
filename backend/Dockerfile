# 后端镜像：FastAPI + LangGraph Agent + RAG（Chroma / bge-small-zh）
FROM python:3.11-slim

WORKDIR /app

# 依赖层（利用层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 应用代码
COPY app ./app
COPY config ./config
COPY scripts ./scripts

# 数据与模型目录由 volume 挂载（宿主机 data/、models/ 复用，避免容器内重新下载 embedding 模型）
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
