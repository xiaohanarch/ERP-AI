# 构建上下文为仓库根目录（compose: context: ..）
FROM python:3.12-slim

WORKDIR /app

COPY erp-ai-action/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 应用代码 + 规格真源 + manifest 生成器（复用 build_manifest，保持单一真源）
COPY erp-ai-action/app ./app
COPY boapi-spec/bo-ap.yaml /app/boapi-spec/bo-ap.yaml
COPY scripts/gen_manifest.py /app/scripts/gen_manifest.py

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
