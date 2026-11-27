# 多阶段：node 构建管理后台，python 运行 BFF。
FROM node:22-slim AS admin
WORKDIR /build
COPY admin-ui/package.json admin-ui/package-lock.json ./
RUN npm ci
COPY admin-ui/ ./
RUN npm run build

FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=admin /web/admin ./web/admin
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import json,urllib.request;print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/health'))['version'])"
CMD ["python", "-m", "uvicorn", "bff.main:app", "--host", "0.0.0.0", "--port", "8000"]
