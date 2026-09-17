# 语义服务（appid: erp-ai-context）：构建上下文为仓库根目录
FROM python:3.12-slim

WORKDIR /app

COPY erp-ai-context/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 语义资产 + 服务 + 漂移检测 + 规格真源（规格即工具）
COPY erp-ai-context/service ./service
COPY erp-ai-context/domains ./domains
COPY erp-ai-context/overlays ./overlays
COPY erp-ai-context/questions-capability.yaml ./questions-capability.yaml
COPY erp-ai-context/drift ./drift
COPY boapi-spec/bo-ap.yaml ./boapi-spec/bo-ap.yaml

EXPOSE 8002
CMD ["uvicorn", "service.main:app", "--host", "0.0.0.0", "--port", "8002"]
