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

1. **Implement a model from a research report** — bundled sample PDF, best first try
2. **Data Interpreter on a Kaggle task** — needs Kaggle credentials secrets
3. **Finance factor mining** / 4. **Finance whole pipeline** — long-running qlib loops

Each run streams live progress on the page and appears in the dashboard history.

## Access control (invitation links)

The app is wrapped with an invitation gate (`gate/gate.py`):

- Visitors must open an **invite link** `https://<host>/?invite=<token>` (sets a cookie,
  token then disappears from the URL). Invites expire after **14 days** by default.
- The **admin** sets a master key via the Fly secret `ADMIN_MASTER_KEY`, then opens
  **`/admin?key=<MASTER>`** to create / list / revoke invite links.
- `/test` (health check) stays open; everything else requires a valid invite.

```bash
flyctl secrets set --app rd-agent ADMIN_MASTER_KEY=so…cret
```

> Invite tokens are stored in `git_ignore_folder/invites.json` on the machine's local disk
> (ephemeral): re-create invites after a redeploy if you haven't attached a volume.

## Notes

- **Code execution**: generated code runs inside the container's own Python
  (`*_env_type=conda`, no extra setup). For containerised execution, mount the Docker
  socket and switch both env vars to `docker`.
- **First finance run** provisions a qlib conda environment and can take a while.
- **Persistence**: workspace/traces live on the machine's ephemeral disk. Add a Fly
  volume if you need them to survive redeploys.
- Models: defaults to `qwen3-max`; any DashScope model works via the OpenAI-compatible
  endpoint (e.g. `openai/qwen-plus`, `openai/qwen3-coder-plus`).
