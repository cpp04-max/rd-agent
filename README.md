# RD-Agent Web App — Fly.io Deployment

Self-hosted deployment of [microsoft/RD-Agent](https://github.com/microsoft/RD-Agent) with its
official web UI, running on **Qwen (Alibaba DashScope)** as the LLM backend.

The web UI lets you launch and monitor RD-Agent scenarios from your browser:

| Scenario | What it does |
|---|---|
| **Data Interpreter** (`data_science`) | General-purpose data-science agent: upload data + task, it plans, codes, runs and iterates |
| **General R&D loop** (`general_model`) | Model research & development loop: hypothesis → experiment → feedback |
| **Finance** (`fin_factor` / `fin_model` / `fin_quant`) | qlib-based factor mining & quant model R&D |

This repo is a **deployment wrapper**: the `Dockerfile` pulls the official RD-Agent source,
builds the Vue frontend, and installs everything into a single container.

---

## Deploy to Fly.io

```bash
# 1. one-time: log in
flyctl auth login

# 2. from this repo's directory:
flyctl launch --name rd-agent --region lax --copy-config --no-deploy

# 3. set the LLM credentials (get a key from https://dashscope.console.aliyun.com/)
flyctl secrets set \
  OPENAI_API_KEY=sk-your-dashscope-key \
  OPENAI_API_BASE=https://dashscope-intl.aliyuncs.com/compatible-mode/v1 \
  CHAT_MODEL=openai/qwen3-max \
  EMBEDDING_MODEL=openai/text-embedding-v4 \
  REASONING_THINK_RM=true \
  DS_Coder_CoSTEER_env_type=conda \
  MODEL_CoSTEER_env_type=conda

# 4. build & deploy (remote build, takes ~5-10 min)
flyctl deploy --remote-only

# 5. open it
flyctl open        # -> https://rd-agent.fly.dev
```

For **China-region** DashScope accounts use `OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1`.

## Local / any Docker host

```bash
cp .env.example .env   # fill in OPENAI_API_KEY
docker build -t rdagent-web .
docker run --rm -p 19899:19899 --env-file .env rdagent-web
# open http://localhost:19899
```

## Quickstart examples

After deploy, open **https://rd-agent.fly.dev/examples.html** (also linked via the floating
"Quickstart Examples" button in the dashboard). It provides one-click runs:

Designed for quant researchers, with one-click runs:

1. **Implement a volatility model from a research report** — bundled EWMA-GARCH paper (General Model Implementation)
2. **Implement an ensemble regressor from a report** — the end-to-end validated demo
3. **Explore alpha factors** — qlib factor-mining loop (Finance Data Building)
4. **Implement a factor from a research report** — bundled VWMOM factor report (Finance Data Building (Reports))
5. **Whole quant pipeline** — factors → model → strategy (Finance Whole Pipeline)
6. **Data Interpreter on a Kaggle task** — finance competition shortcuts; needs Kaggle credentials secrets

Each run streams live progress on the page and appears in the dashboard history.

## Access control (invitation links)

The app is wrapped with an invitation gate (`gate/gate.py`):

- Visitors must open an **invite link** `https://<host>/?invite=<token>` (sets a cookie,
  token then disappears from the URL). Invites expire after **14 days** by default.
- The **admin** sets a master key via the Fly secret `ADMIN_MASTER_KEY`, then opens
  **`/admin?key=<MASTER>`** to create invite links **in bulk** (up to 50 at once,
  configurable validity and note), copy single or all links, and revoke any invite.
- `/test` (health check) stays open; everything else requires a valid invite.

```bash
flyctl secrets set --app rd-agent ADMIN_MASTER_KEY=so…cret
```

> Invites and traces persist on the Fly volume (`rdagentdata` mounted at `/data`,
> `INVITE_STORE=/data/invites.json`, `UI_TRACE_FOLDER=/data/traces`) — they survive redeploys.

> **Security:** use a long, random `ADMIN_MASTER_KEY`. Short keys are guessable on a
> public site and appear in the `/admin?key=*** URL.

## Notes

- **Code execution**: generated code runs inside the container's own Python
  (`*_env_type=conda`, no extra setup). For containerised execution, mount the Docker
  socket and switch both env vars to `docker`.
- **First finance run** provisions a qlib conda environment and can take a while.
- **Persistence**: `fly.toml` mounts the `rdagentdata` volume at `/data` for invites and
  traces; create it once with `flyctl volumes create rdagentdata --region lax`.
- Models: defaults to `qwen3-max`; any DashScope model works via the OpenAI-compatible
  endpoint (e.g. `openai/qwen-plus`, `openai/qwen3-coder-plus`).
