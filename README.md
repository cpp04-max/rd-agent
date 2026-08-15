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

## Repo layout

| Path | Purpose |
|---|---|
| `Dockerfile` | Two-stage build: patched RD-Agent + Vue frontend + invitation gate |
| `fly.toml` | Fly.io config (machine size, `/data` volume, health check) |
| `gate/gate.py` | Invitation gate (WSGI wrapper) + `/admin` console, wraps the Flask app |
| `web-extras/patch-rdagent.py` | Build-time patches to upstream `rdagent/` (env selection, qlib data, progress streaming) |
| `web-extras/injected/` | Code blocks the patcher injects, kept as lintable `.py` files |
| `web-extras/patch-frontend.js` | Build-time patches to the Vue frontend (deep links, dialog pre-fill, live panel) |
| `web-extras/examples.html` | Quickstart examples page (served at `/examples.html`) |
| `web-extras/gen_example_specs.py` | Regenerates the bundled sample spec PDFs (`sample_*.pdf`) |
| `web-extras/add_examples_link.py` | Injects the floating Quickstart button into the built `index.html` |

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
"Quickstart Examples" button in the dashboard). Designed for quant researchers, it provides one-click runs:

1. **Implement a volatility model from a research report** — bundled EWMA-GARCH paper (General Model Implementation)
2. **Implement an ensemble regressor from a report** — the end-to-end validated demo
3. **Explore alpha factors** — qlib factor-mining loop (Finance Data Building)
4. **Implement a factor from a research report** — bundled VWMOM factor report (Finance Data Building (Reports))
5. **Whole quant pipeline** — factors → model → strategy (Finance Whole Pipeline)
6. **Data Interpreter on a Kaggle task** — finance competition shortcuts; needs Kaggle credentials secrets
7. **Paper playground: Prime Attention (mini)** — reproduce a simplified version of the pair-modulated attention MTS paper (arXiv 2509.12196)
8. **Paper playground: ChaTSFM (mini)** — reproduce a simplified channel adapter for frozen time-series foundation models (ICML 2026)
9. **Architecture lab: Stock-ranking Mixture-of-Experts** — implement sector/dynamic-KNN/global-factor experts with a regime router, evaluated on one year of real public US large-cap daily closes (16 assets / 4 sectors, bundled in the spec PDF)

Each run streams live progress on the page and appears in the dashboard history.

Inside the dashboard, a **Live activity** panel streams the run's stdout in real time (a "thinking flow": hypothesis generation, code evolution, experiment runs, feedback), with a one-line phase summary; it can be collapsed.
It also works for past runs reopened after a redeploy (stdout is read from the persisted trace log), and resets automatically when switching traces.

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

- **Code execution**: generated code runs inside the container's own Python. The
  build-time patches make the `conda` env types fall back to the container interpreter
  when conda is absent (as in this image), so no extra setup is needed. For containerised
  execution, mount the Docker socket and switch both env vars to `docker`.
- **Finance scenarios** run in the container's own Python (build-time patches in
  `web-extras/patch-rdagent.py` replace upstream's conda/Docker env selection). The image
  ships qlib/mlflow/lightgbm via `pyqlib`. The first finance run downloads qlib CN market
  data (~200 MB) to the `/data` volume and builds the factor dataset — expect a slow start.
  Factor development/backtesting is scoped to the CSI300 universe (`RDAGENT_QLIB_UNIVERSE`).
- **Persistence**: `fly.toml` mounts the `rdagentdata` volume at `/data` for invites,
  traces and qlib market data; create it once with
  `flyctl volumes create rdagentdata --region lax`.
- **Machine size**: finance runs need the 2 GB memory setting in `fly.toml` (qlib dataset
  construction).
- Models: defaults to `qwen3-max`; any DashScope model works via the OpenAI-compatible
  endpoint (e.g. `openai/qwen-plus`, `openai/qwen3-coder-plus`).
