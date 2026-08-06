# ============================================================
# RD-Agent web app — production image
# Flask log-server + Vue frontend, LLM via Qwen/DashScope (.env)
# ============================================================
FROM node:22-alpine AS frontend
RUN apk add --no-cache git
RUN git clone --depth 1 https://github.com/microsoft/RD-Agent.git /src
WORKDIR /src/web
RUN npm install --legacy-peer-deps --no-audit --no-fund \
 && npm run build           # outputs to /src/git_ignore_folder/static

FROM python:3.10-slim
ENV PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends git curl \
 && rm -rf /var/lib/apt/lists/*
RUN pip install uv

RUN git clone --depth 1 https://github.com/microsoft/RD-Agent.git /app/RD-Agent
WORKDIR /app/RD-Agent

# Install rdagent + all runtime deps (uses uv for speed/reliability)
RUN uv pip install --system -r requirements.txt \
 && uv pip install --system --no-deps .

# Built Vue frontend served by the Flask log server
COPY --from=frontend /src/git_ignore_folder/static /app/RD-Agent/git_ignore_folder/static

# Workspace, traces and logs live in git_ignore_folder/ and log/ — mount volumes to persist
RUN mkdir -p git_ignore_folder/static git_ignore_folder/traces log

EXPOSE 19899
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -fs http://127.0.0.1:19899/test || exit 1

CMD ["python3", "-m", "rdagent.log.server.app", "--port", "19899"]
