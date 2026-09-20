# RD-Agent(Q) Reproduction — single-purpose Fly.io deployment

A minimal, self-hosted deployment of [microsoft/RD-Agent](https://github.com/microsoft/RD-Agent)
that reproduces **one** paper:

> **R&D-Agent-Quant: A Multi-Agent Framework for Data-Centric Factors and Model Joint Optimization**
> Li, Yang, Yang, Xu, Wang, Liu, Bian — [arXiv:2505.15155](https://arxiv.org/abs/2505.15155) (NeurIPS 2025)

RD-Agent(Q) — the framework the paper describes — *is* RD-Agent's joint factor + model
co-optimization loop, exposed here as the **`fin_quant`** scenario ("Finance Whole Pipeline").
This repo strips the upstream app down to **only that loop**, with a single-task UI and a
Qwen (Alibaba DashScope) LLM backend.

## What this deployment does

One click launches the autonomous R&D loop on real qlib market data:

| Paper stage | RD-Agent implementation |
|---|---|
| **Research** — goal-aligned prompts → hypotheses from domain priors → concrete tasks | hypothesis + task generation in the qlib R&D loop |
| **Development** — `Co-STEER` code agent implements task code, run in real-market backtests | factor + model CoSTEER coders, executed in a qlib backtest |
| **Feedback** — evaluate outcomes, multi-armed-bandit scheduler picks the next direction | qlib metrics (IC / Rank IC, annualized excess return, information ratio, drawdown) → feedback → next round |
| **Joint factor + model co-optimization** | factors and the return-forecasting model evolve together across loops |

The paper reports up to **2× higher annualized return with ~70% fewer factors** than classical
factor libraries, and beats strong deep time-series baselines — the loop here optimizes the
same objective (factor + model quality against backtest feedback).

## What was removed

Everything that is not the RD-Agent(Q) pipeline:

- **Scenarios**: Data Interpreter (`data_science`), General Model (`general_model`), Finance Data
  Building (`fin_factor`), Finance Data Building from Reports (`fin_factor_report`), Finance Model
  Implementation (`fin_model`), and the LOB / statistical-market-making example.
- **Paper playground examples**: Prime Attention, ChaTSFM, Stock-MoE, volatility / ensemble model
  demos, and all bundled `sample_*.pdf` spec inputs + the spec generator.
- The `/upload` endpoint is **scope-locked** to the single `Finance Whole Pipeline` scenario, so no
  other loop can be started even though upstream ships them.

## Repo layout

| Path | Purpose |
|---|---|
| `Dockerfile` | Two-stage build: patched RD-Agent + Vue frontend + invitation gate |
| `fly.toml` | Fly.io config (machine size, `/data` volume, health check) |
| `gate/gate.py` | Invitation gate (WSGI wrapper) + `/admin` console |
| `web-extras/patch-rdagent.py` | Build-time patches to upstream `rdagent/` (env selection, qlib data, progress streaming, **scope-lock to `fin_quant`**) |
| `web-extras/injected/` | Code blocks the patcher injects (`qlib_provision.py`, `progress_endpoint.py`) |
| `web-extras/patch-frontend.js` | Build-time patches to the Vue frontend (deep links, single-scenario instruction pre-fill, live activity panel) |
| `web-extras/examples.html` | The single-task reproduction page (served at `/examples.html`) |
| `web-extras/add_examples_link.py` | Injects the floating "Reproduce RD-Agent(Q)" button into the built `index.html` |

## Upstream version pin

`microsoft/RD-Agent` is fetched at build time, **pinned to a known-good commit** via the
`RDAGENT_COMMIT` build ARG in the `Dockerfile` (currently `6762f84`). The build patches are
strict-match, so an unpinned `main` will eventually drift and break the build (this already
happened once at the `P11b model.py imports` anchor). To track a newer upstream:

```bash
# 1. bump the pin
sed -i 's/^ARG RDAGENT_COMMIT=.*/ARG RDAGENT_COMMIT=<new-sha>/' Dockerfile
# 2. re-run the patcher against that commit to confirm every anchor still matches
git init /tmp/rd && git -C /tmp/rd remote add origin https://github.com/microsoft/RD-Agent.git \
  && git -C /tmp/rd fetch --depth 1 origin <new-sha> && git -C /tmp/rd checkout FETCH_HEAD
python3 web-extras/patch-rdagent.py /tmp/rd      # must print "All rdagent patches applied."
# 3. fix any drifted anchors in patch-rdagent.py / patch-frontend.js, then rebuild
```

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
  MODEL_CoSTEER_env_type=conda

# 4. build & deploy (remote build, ~5-10 min)
flyctl deploy --remote-only

# 5. open it
flyctl open        # -> https://rd-agent.fly.dev/examples.html
```

For **China-region** DashScope accounts use `OPENAI_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1`.

## Local / any Docker host

```bash
cp .env.example .env   # fill in OPENAI_API_KEY
docker build -t rdagent-q .
docker run --rm -p 19899:19899 --env-file .env rdagent-q
# open http://localhost:19899/examples.html
```

## Running the reproduction

1. Open **`/examples.html`** (or the floating **Reproduce RD-Agent(Q)** button in the dashboard).
2. Set **R&D loops** (start with `1` to validate the setup) and press **▶ Reproduce RD-Agent(Q)**.
3. The first run downloads qlib CN market data (~200 MB, persisted on the `/data` volume) and builds
   the factor dataset — expect a slow start.
4. When the loop asks for an **overall instruction**, a paper-faithful example is already filled in —
   just press **SUBMIT**.
5. Watch the live monitor on the page, then open the run in the **dashboard** (`/#/Playground`) for
   hypotheses, generated factor/model code, the qlib backtest chart and metrics.

> A run that stops immediately with **"config: null"** means the LLM backend is not configured —
> set the DashScope secrets above.
