// Patches the upstream RD-Agent Vue frontend before it is built:
// 1) adds ?trace= deep-link support to the Playground page so that links like
//    /#/Playground?trace=<Scenario>/<trace_name>
//    open that specific run directly instead of the landing page.
// 2) pre-fills the "overall instruction" user-interaction dialog with a
//    scenario-appropriate example instruction, so users can just press SUBMIT.
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
