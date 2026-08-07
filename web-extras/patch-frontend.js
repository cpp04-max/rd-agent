// Patches the upstream RD-Agent Vue frontend before it is built:
// adds ?trace= deep-link support to the Playground page so that links like
//   /#/Playground?trace=<Scenario>/<trace_name>
// open that specific run directly instead of the landing page.
const fs = require("fs");

const p = "/src/web/src/views/Playground.vue";
let s = fs.readFileSync(p, "utf8");

const imp = 'import { useRouter } from "vue-router";';
const mount = "onMounted(() => {\n  void buildHistoryTraceList();\n});";

if (!s.includes(imp) || !s.includes(mount)) {
  console.warn("[patch-frontend] WARN: upstream Playground.vue changed; deep-link patch skipped.");
  process.exit(0);
}

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
