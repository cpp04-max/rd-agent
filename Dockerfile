# ============================================================
# RD-Agent web app — production image
# Flask log-server + Vue frontend, LLM via Qwen/DashScope (.env)
# ============================================================
FROM node:22-alpine AS frontend
RUN apk add --no-cache git
RUN git clone --depth 1 https://github.com/microsoft/RD-Agent.git /src
# Deep-link support: /#/Playground?trace=<id> opens a specific run in the dashboard
COPY web-extras/patch-frontend.js /tmp/patch-frontend.js
RUN node /tmp/patch-frontend.js
WORKDIR /src/web
RUN npm install --legacy-peer-deps --no-audit --no-fund \
 && npm run build:flask           # outputs to /src/git_ignore_folder/static

FROM python:3.10-slim
ENV PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends git curl \
 && rm -rf /var/lib/apt/lists/*
RUN pip install uv

RUN git clone --depth 1 https://github.com/microsoft/RD-Agent.git /app/RD-Agent
# Finance scenarios run inside this container (no conda/docker): patch env selection,
# qlib data provisioning and memory limits before the package is installed.
COPY web-extras/patch-rdagent.py /tmp/patch-rdagent.py
RUN python3 /tmp/patch-rdagent.py /app/RD-Agent
WORKDIR /app/RD-Agent

# Install rdagent + all runtime deps (uses uv for speed/reliability)
RUN uv pip install --system -r requirements.txt \
 && uv pip install --system --no-deps .

# Finance (qlib) scenarios: qlib + mlflow + lightgbm + deps
RUN uv pip install --system pyqlib

# Built Vue frontend served by the Flask log server
COPY --from=frontend /src/git_ignore_folder/static /app/RD-Agent/git_ignore_folder/static

# Quickstart examples page + bundled sample inputs (served from /examples.html)
COPY web-extras/examples.html git_ignore_folder/static/examples.html
COPY web-extras/sample_model_report.pdf git_ignore_folder/static/examples-assets/sample_model_report.pdf
COPY web-extras/sample_quant_model.pdf git_ignore_folder/static/examples-assets/sample_quant_model.pdf
COPY web-extras/sample_factor_report.pdf git_ignore_folder/static/examples-assets/sample_factor_report.pdf
COPY web-extras/sample_prime_attention.pdf git_ignore_folder/static/examples-assets/sample_prime_attention.pdf
COPY web-extras/sample_chatsfm.pdf git_ignore_folder/static/examples-assets/sample_chatsfm.pdf
COPY web-extras/sample_stock_moe_experts.pdf git_ignore_folder/static/examples-assets/sample_stock_moe_experts.pdf
RUN python3 -c "import pathlib; p=pathlib.Path('git_ignore_folder/static/index.html'); s=p.read_text(); s=s.replace('</body>', '<a href=\"/examples.html\" style=\"position:fixed;right:18px;bottom:18px;z-index:9999;background:#1677ff;color:#fff;padding:10px 16px;border-radius:24px;font:600 14px/1 system-ui,sans-serif;text-decoration:none;box-shadow:0 4px 14px rgba(22,119,255,.4)\">Quickstart Examples</a></body>'); p.write_text(s)"

# Workspace, traces and logs live in git_ignore_folder/ and log/ — mount volumes to persist
RUN mkdir -p git_ignore_folder/static git_ignore_folder/traces log
# qlib market data persists on the /data volume (survives redeploys)
RUN ln -s /data/qlib /root/.qlib

EXPOSE 19899
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -fs http://127.0.0.1:19899/test || exit 1

# Invitation gate: wraps the Flask app, requires invite links (admin console at /admin)
COPY gate/gate.py gate.py

CMD ["python3", "gate.py", "--port", "19899"]
