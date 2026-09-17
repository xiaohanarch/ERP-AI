# mock 模型：OpenAI 兼容脚本化应答（无 LLM key 环境的第一层兜底）
# 构建上下文为仓库根目录（compose: context: ..）
FROM python:3.12-slim

WORKDIR /app
COPY erp-ai-action/docker/mock_model.py ./mock_model.py

EXPOSE 8090

CMD ["python", "mock_model.py"]
