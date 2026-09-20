# ============================================================
# RD-Agent(Q) reproduction — production image (single-task)
# Reproduces arXiv:2505.15155 (joint factor + model optimization)
# via the fin_quant loop. Flask log-server + Vue frontend,
# LLM via Qwen/DashScope (.env).
# ============================================================
# Pin upstream RD-Agent to a known-good commit. An unpinned `main` drifts and breaks
# the strict-match patcher / frontend anchors (this build failed at P11b model.py
# imports when upstream changed). 6762f84 is the commit this image was tested against.
ARG RDAGENT_COMMIT=6762f84f9bc0f5c6486c50a00e128a57ac6c3683

FROM node:22-alpine AS frontend
ARG RDAGENT_COMMIT
RUN apk add --no-cache git
RUN git init -q /src \
 && git -C /src remote add origin https://github.com/microsoft/RD-Agent.git \
 && git -C /src fetch -q --depth 1 origin "$RDAGENT_COMMIT" \
 && git -C /src checkout -q FETCH_HEAD
# Deep-link support: /#/Playground?trace=<id> opens a specific run in the dashboard
COPY web-extras/patch-frontend.js /tmp/patch-frontend.js
RUN node /tmp/patch-frontend.js
WORKDIR /src/web
RUN npm install --legacy-peer-deps --no-audit --no-fund \
 && npm run build:flask           # outputs to /src/git_ignore_folder/static

FROM python:3.10-slim
ARG RDAGENT_COMMIT
ENV PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends git curl \
 && rm -rf /var/lib/apt/lists/*
RUN pip install uv

RUN git init -q /app/RD-Agent \
 && git -C /app/RD-Agent remote add origin https://github.com/microsoft/RD-Agent.git \
 && git -C /app/RD-Agent fetch -q --depth 1 origin "$RDAGENT_COMMIT" \
 && git -C /app/RD-Agent checkout -q FETCH_HEAD
# The RD-Agent(Q) fin_quant loop runs inside this container (no conda/docker):
# patch env selection, qlib data provisioning and memory limits before install,
# and lock /upload to this one scenario. The patcher loads code snippets from
# ./injected/ relative to itself.
COPY web-extras/patch-rdagent.py /tmp/web-extras/patch-rdagent.py
COPY web-extras/injected/ /tmp/web-extras/injected/
RUN python3 /tmp/web-extras/patch-rdagent.py /app/RD-Agent
WORKDIR /app/RD-Agent

# Install rdagent + all runtime deps (uses uv for speed/reliability)
RUN uv pip install --system -r requirements.txt \
 && uv pip install --system --no-deps .

# litellm 1.97.0 regression: its `Message` model is not fully defined, so every
# chat completion raises before any HTTP call and RD-Agent surfaces it as
# "Failed to create chat completion after 10 retries" (killing each scenario at
# its first LLM call -> "No hypothesis generated ..."). 1.95.0 is verified good
# with pydantic 2.13 / openai 2.54; keep this pin until upstream fixes it.
RUN uv pip install --system "litellm==1.95.0"

# Finance (qlib) scenarios: qlib + mlflow + lightgbm + deps
RUN uv pip install --system pyqlib

# mlflow 3.x regression: its FileStore rejects the legacy './mlruns' backend and
# its async metric logging breaks qlib's recorder ("Metric 'Rank IC' is malformed.
# No data found."), which kills every qlib backtest in the finance loops. qlib
# needs mlflow 2.x; keep this pin until qlib supports mlflow 3.
RUN uv pip install --system "mlflow==2.22.2"

# The fin_quant model step's CoSTEER runner does `import torch` and calls the
# generated nn.Module. Use the PyTorch CPU index ONLY - it is self-contained (hosts torch's
# pure-python deps) and resolves torch==<ver>+cpu with no nvidia/CUDA packages.
# Adding PyPI as an extra index makes uv prefer the multi-GB CUDA build, so it is
# deliberately omitted (verified via uv pip install --dry-run).
RUN uv pip install --system torch --index-url https://download.pytorch.org/whl/cpu

# Built Vue frontend served by the Flask log server
COPY --from=frontend /src/git_ignore_folder/static /app/RD-Agent/git_ignore_folder/static

# Single-task reproduction page (served from /examples.html)
COPY web-extras/examples.html git_ignore_folder/static/examples.html
COPY web-extras/add_examples_link.py /tmp/add_examples_link.py
RUN python3 /tmp/add_examples_link.py git_ignore_folder/static/index.html

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
