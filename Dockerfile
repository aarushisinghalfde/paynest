# One Python image for the api, worker and mock-payroll-api services;
# docker-compose.yml chooses the command for each.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app PIP_NO_CACHE_DIR=1
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION
# Default command: the AgentCore Runtime entry point (model steps, port 8080, /ping + /invocations).
# docker-compose overrides it for the api, worker and mock-payroll-api services.
EXPOSE 8080
CMD ["uvicorn", "agent.agentcore_app:app", "--host", "0.0.0.0", "--port", "8080"]
