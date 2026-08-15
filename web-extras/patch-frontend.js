// Patches the upstream RD-Agent Vue frontend before it is built:
// 1) adds ?trace= deep-link support to the Playground page so that links like
//    /#/Playground?trace=<Scenario>/<trace_name>
//    open that specific run directly instead of the landing page.
// 2) pre-fills the "overall instruction" user-interaction dialog with a
//    scenario-appropriate example instruction, so users can just press SUBMIT.
// 3) installs the collapsible "Live activity" panel on the trace detail page,
//    streaming the run's stdout via /progress.
const fs = require("fs");

// ---------------------------------------------------------------- deep link
const p = "/src/web/src/views/Playground.vue";
let s = fs.readFileSync(p, "utf8");

const imp = 'import { useRouter } from "vue-router";';
const mount = "onMounted(() => {\n  void buildHistoryTraceList();\n});";

if (!s.includes(imp) || !s.includes(mount)) {
  console.warn("[patch-frontend] WARN: upstream Playground.vue changed; deep-link patch skipped.");
} else {
  s = s.replace(imp, 'import { useRouter, useRoute } from "vue-router";');
  s = s.replace(
    "const router = useRouter();",
    "const router = useRouter();\nconst route = useRoute();"
  );
  s = s.replace(
    mount,
    "onMounted(() => {\n" +
    "  void buildHistoryTraceList();\n" +
    "  const deepTrace = String(route.query.trace || \"\").trim();\n" +
    "  if (deepTrace) {\n" +
    "    const separatorIndex = deepTrace.indexOf(\"/\");\n" +
    "    const deepScenario = separatorIndex === -1 ? \"\" : deepTrace.slice(0, separatorIndex);\n" +
    "    applyScenarioConfig(getScenarioConfigByName(deepScenario));\n" +
    "    id.value = deepTrace;\n" +
    "    showPlayground.value = true;\n" +
    "  }\n" +
    "});"
  );
  fs.writeFileSync(p, s);
  console.log("[patch-frontend] deep-link patch applied to Playground.vue");
}

// --------------------------------------- example instruction pre-fill
const p2 = "/src/web/src/views/PlaygroundPage.vue";
let s2 = fs.readFileSync(p2, "utf8");

const anchorA = 'const userInstructionPlaceholder = "Example: 使用中文来生成假设";';
const anchorB =
  "        : key === \"decision\"\n" +
  "          ? false\n" +
  "          : \"\",\n" +
  "  }));";

if (!s2.includes(anchorA) || !s2.includes(anchorB) || s2.indexOf(anchorB) !== s2.lastIndexOf(anchorB)) {
  console.error("[patch-frontend] FAILED: PlaygroundPage.vue anchors drifted; cannot install example instructions.");
  process.exit(1);
}

const defaults =
  "const DEFAULT_USER_INSTRUCTIONS = {\n" +
  "  \"Finance Data Building\":\n" +
  "    \"Research and iteratively implement alpha factors for stock selection in the CSI300 universe using daily OHLCV data. Start with volume/price momentum style factors (e.g. volume-weighted momentum over the past 20 trading days). Evaluate each factor by IC/RankIC and a qlib backtest, and keep refining until the factor is stable and profitable.\",\n" +
  "  \"Finance Data Building (Reports)\":\n" +
  "    \"Implement the alpha factor(s) described in the uploaded research report (e.g. volume-weighted momentum, VWMOM) for the CSI300 universe. Validate them with qlib backtests and iteratively improve IC/RankIC.\",\n" +
  "  \"Finance Model Implementation\":\n" +
  "    \"Implement a stock price prediction model for the CSI300 universe using the provided base factors as features and next-day return as the label. Start with a LightGBM baseline, evaluate with annualized excess return and information ratio from the qlib backtest, and iteratively improve the model.\",\n" +
  "  \"Finance Whole Pipeline\":\n" +
  "    \"Run the full quant R&D pipeline on the CSI300 universe: alternate between alpha factor engineering and prediction model implementation based on backtest feedback, optimizing annualized excess return and information ratio.\",\n" +
  "  \"Data Science\":\n" +
  "    \"Analyze the dataset, perform feature engineering, train and evaluate a predictive model for the target, and iteratively improve the evaluation metric. Start with a simple baseline before trying more complex models.\",\n" +
  "  \"General Model Implementation\":\n" +
  "    \"Implement the model described in the uploaded report/documentation. Start with a faithful baseline implementation, evaluate it against the stated metrics, and iteratively improve performance.\",\n" +
  "  _default:\n" +
  "    \"Please carry out the R&D task step by step: start with a simple baseline, evaluate the results, and iteratively improve based on the feedback.\",\n" +
  "};\n" +
  "const defaultUserInstructionFor = (name) => {\n" +
  "  const key = String(name || \"\").trim();\n" +
  "  return DEFAULT_USER_INSTRUCTIONS[key] || DEFAULT_USER_INSTRUCTIONS._default;\n" +
  "};";

s2 = s2.replace(anchorA, anchorA + "\n" + defaults);

const prefill =
  anchorB +
  "\n  entries.forEach((entry) => {\n" +
  "    if (\n" +
  "      entry.key === \"user_instruction\" &&\n" +
  "      !String(entry.value || \"\").trim()\n" +
  "    ) {\n" +
  "      entry.value = defaultUserInstructionFor(scenarioName.value);\n" +
  "    }\n" +
  "  });";

s2 = s2.replace(anchorB, prefill);

fs.writeFileSync(p2, s2);
console.log("[patch-frontend] example-instruction pre-fill applied to PlaygroundPage.vue");

// --------------------------------------------- live "thinking flow" panel
// PlaygroundPage.vue was already rewritten above; re-read the patched file.
let s3 = fs.readFileSync(p2, "utf8");

const anchorC = "      <div class=\"main-content\">";
const anchorD = "onMounted(() => {\n  firstTrace();\n});";
const anchorE = "onUnmounted(() => {});";

if (
  !s3.includes(anchorC) ||
  !s3.includes(anchorD) ||
  !s3.includes(anchorE) ||
  s3.indexOf(anchorC) !== s3.lastIndexOf(anchorC) ||
  s3.indexOf(anchorD) !== s3.lastIndexOf(anchorD) ||
  s3.indexOf(anchorE) !== s3.lastIndexOf(anchorE)
) {
  console.error("[patch-frontend] FAILED: PlaygroundPage.vue anchors drifted; cannot install live activity panel.");
  process.exit(1);
}

const panel =
  "      <div class=\"live-activity\" v-if=\"props.id && String(props.id).trim()\">\n" +
  "        <div class=\"live-activity-head\" @click=\"activityCollapsed = !activityCollapsed\">\n" +
  "          <span class=\"live-dot\" :class=\"activityRunning ? 'on' : 'off'\"></span>\n" +
  "          <span class=\"live-title\">Live activity</span>\n" +
  "          <span class=\"live-phase\">{{ activityPhase }}</span>\n" +
  "          <span class=\"live-toggle\">{{ activityCollapsed ? '▸ show thinking flow' : '▾ hide thinking flow' }}</span>\n" +
  "        </div>\n" +
  "        <pre class=\"live-log\" v-show=\"!activityCollapsed\" ref=\"activityLogEl\">{{ activityText }}</pre>\n" +
  "      </div>\n";

s3 = s3.replace(anchorC, anchorC + "\n" + panel);

const activityCode =
  "const activityText = ref(\"\");\n" +
  "const activityPhase = ref(\"starting…\");\n" +
  "const activityCollapsed = ref(false);\n" +
  "const activityRunning = ref(true);\n" +
  "const activityLogEl = ref(null);\n" +
  "let activityOffset = 0;\n" +
  "let activityTimer = null;\n" +
  "let activityLastTraceId = \"\";\n" +
  "\n" +
  "const activityPhaseFromLine = (line) => {\n" +
  "  const t = String(line || \"\");\n" +
  "  if (/waiting for user interaction/i.test(t)) return \"waiting for user input…\";\n" +
  "  if (/hypothesis/i.test(t)) return \"generating hypothesis (LLM)…\";\n" +
  "  if (/evolv|costeer/i.test(t)) return \"evolving code (CoSTEER)…\";\n" +
  "  if (/localenv logs begin|running time|entry_exit_code/i.test(t)) return \"running experiment…\";\n" +
  "  if (/feedback|metric/i.test(t)) return \"collecting feedback & metrics…\";\n" +
  "  if (/qlib-data|qlib_data/i.test(t)) return \"preparing qlib data…\";\n" +
  "  if (/traceback|error/i.test(t)) return \"error in run (see log)\";\n" +
  "  const short = t.trim();\n" +
  "  return short.length > 90 ? short.slice(0, 90) + \"…\" : short || \"running…\";\n" +
  "};\n" +
  "\n" +
  "const progressPoll = () => {\n" +
  "  if (activityTimer) {\n" +
  "    clearTimeout(activityTimer);\n" +
  "    activityTimer = null;\n" +
  "  }\n" +
  "  const activityTraceId = String(props.id || \"\").trim();\n" +
  "  if (!activityTraceId) {\n" +
  "    activityTimer = setTimeout(progressPoll, 3000);\n" +
  "    return;\n" +
  "  }\n" +
  "  if (activityTraceId !== activityLastTraceId) {\n" +
  "    activityLastTraceId = activityTraceId;\n" +
  "    activityText.value = \"\";\n" +
  "    activityOffset = 0;\n" +
  "    activityRunning.value = true;\n" +
  "    activityPhase.value = \"starting…\";\n" +
  "  }\n" +
  "  fetch(`/progress?id=${encodeURIComponent(activityTraceId)}&offset=${activityOffset}`)\n" +
  "    .then((r) => (r.ok ? r.json() : null))\n" +
  "    .then((j) => {\n" +
  "      if (!j) throw new Error(\"bad response\");\n" +
  "      if (typeof j.offset === \"number\") activityOffset = j.offset;\n" +
  "      if (j.text) {\n" +
  "        activityText.value += j.text;\n" +
  "        const lines = activityText.value.split(\"\\n\");\n" +
  "        if (lines.length > 400) {\n" +
  "          activityText.value = lines.slice(-400).join(\"\\n\");\n" +
  "        }\n" +
  "        const nonEmpty = lines.filter((l) => l.trim());\n" +
  "        if (nonEmpty.length) {\n" +
  "          activityPhase.value = activityPhaseFromLine(nonEmpty[nonEmpty.length - 1]);\n" +
  "        }\n" +
  "        requestAnimationFrame(() => {\n" +
  "          const el = activityLogEl.value;\n" +
  "          if (el && !activityCollapsed.value) el.scrollTop = el.scrollHeight;\n" +
  "        });\n" +
  "      }\n" +
  "      if (j.alive === false) {\n" +
  "        activityRunning.value = false;\n" +
  "        if (!activityText.value) activityPhase.value = \"run finished (no captured output)\";\n" +
  "        return;\n" +
  "      }\n" +
  "      activityRunning.value = true;\n" +
  "      activityTimer = setTimeout(progressPoll, 3000);\n" +
  "    })\n" +
  "    .catch(() => {\n" +
  "      activityTimer = setTimeout(progressPoll, 6000);\n" +
  "    });\n" +
  "};\n" +
  "\n";

s3 = s3.replace(anchorD, activityCode + "onMounted(() => {\n  firstTrace();\n  progressPoll();\n});");
s3 = s3.replace(anchorE, "onUnmounted(() => {\n  if (activityTimer) clearTimeout(activityTimer);\n});");

const activityStyle =
  "\n<style scoped>\n" +
  ".live-activity { margin: 8px 12px 0; border: 1px solid #d9e2f0; border-radius: 10px; background: #fbfdff; overflow: hidden; }\n" +
  ".live-activity-head { display: flex; align-items: center; gap: 8px; padding: 7px 12px; cursor: pointer; user-select: none; background: #f2f6fc; font-size: 12.5px; color: #334155; }\n" +
  ".live-dot { width: 9px; height: 9px; border-radius: 50%; background: #9aa4b2; flex: 0 0 auto; }\n" +
  ".live-dot.on { background: #22c55e; animation: livepulse 1.6s infinite; }\n" +
  ".live-dot.off { background: #9aa4b2; }\n" +
  "@keyframes livepulse { 0% { box-shadow: 0 0 0 0 rgba(34,197,94,.45); } 70% { box-shadow: 0 0 0 7px rgba(34,197,94,0); } 100% { box-shadow: 0 0 0 0 rgba(34,197,94,0); } }\n" +
  ".live-title { font-weight: 600; flex: 0 0 auto; }\n" +
  ".live-phase { color: #475569; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1 1 auto; }\n" +
  ".live-toggle { color: #1677ff; flex: 0 0 auto; font-size: 12px; }\n" +
  ".live-log { margin: 0; padding: 8px 12px; max-height: 190px; overflow: auto; background: #0f172a; color: #c8e6c9; font: 11px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; white-space: pre-wrap; word-break: break-word; }\n" +
  "</style>\n";

s3 = s3 + activityStyle;

fs.writeFileSync(p2, s3);
console.log("[patch-frontend] live activity panel applied to PlaygroundPage.vue");
