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
flyctl launch --name rd-agent --region ams --copy-config --no-deploy

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

## Notes

- **Code execution**: generated code runs inside the container's own Python
  (`*_env_type=conda`, no extra setup). For containerised execution, mount the Docker
  socket and switch both env vars to `docker`.
- **First finance run** provisions a qlib conda environment and can take a while.
- **Persistence**: workspace/traces live on the machine's ephemeral disk. Add a Fly
  volume if you need them to survive redeploys.
- Models: defaults to `qwen3-max`; any DashScope model works via the OpenAI-compatible
  endpoint (e.g. `openai/qwen-plus`, `openai/qwen3-coder-plus`).
