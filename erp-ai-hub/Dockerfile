# 业务 Hub（appid: erp-ai-hub）：构建上下文为仓库根目录
FROM python:3.12-slim

WORKDIR /app

COPY erp-ai-hub/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 服务代码 + harness 资产（三层解析：Standard/Partner/Tenant）
COPY erp-ai-hub/hub ./hub
COPY harness-assets ./harness-assets

EXPOSE 8001
CMD ["uvicorn", "hub.main:app", "--host", "0.0.0.0", "--port", "8001"]
