const fs = require("fs");

// P57: ResultPage continuation changes only the hash/query. Playground.vue is
// already mounted, so its onMounted deep-link code does not run again. Watch the
// route query and switch the keyed PlaygroundPage to the newly-created trace.
const pgPath = "/src/web/src/views/Playground.vue";
let pg = fs.readFileSync(pgPath, "utf8");

const mountedOld = [
  "onMounted(() => {",
  "  // Warm only the cheap experiment-name list. Resume checkpoint details are lazy.",
  "  void buildHistoryTraceList({ loadResume: false });",
  "  const deepTrace = String(route.query.trace || \"\").trim();",
  "  if (deepTrace) {",
  "    const separatorIndex = deepTrace.indexOf(\"/\");",
  "    const deepScenario = separatorIndex === -1 ? \"\" : deepTrace.slice(0, separatorIndex);",
  "    applyScenarioConfig(getScenarioConfigByName(deepScenario));",
  "    id.value = deepTrace;",
  "    showPlayground.value = true;",
  "  }",
  "});",
].join("\n");

const mountedNew = [
  "const applyDeepTrace = (traceValue) => {",
  "  const deepTrace = String(traceValue || \"\").trim();",
  "  if (!deepTrace) return;",
  "",
  "  const separatorIndex = deepTrace.indexOf(\"/\");",
  "  const deepScenario =",
  "    separatorIndex === -1 ? \"\" : deepTrace.slice(0, separatorIndex);",
  "",
  "  applyScenarioConfig(getScenarioConfigByName(deepScenario));",
  "",
  "  // P51 keys PlaygroundPage by id, so changing id tears down the old trace",
  "  // pollers and mounts a clean page for the continuation/branch.",
  "  if (String(id.value || \"\").trim() !== deepTrace) {",
  "    id.value = deepTrace;",
  "  }",
  "  showPanel.value = 1;",
  "  showPlayground.value = true;",
  "",
  "  // Keep history warm so the newly-created continuation appears immediately",
  "  // when the user returns to Previous Experiments.",
  "  historyListLoaded.value = false;",
  "  void buildHistoryTraceList({ loadResume: false, force: true });",
  "};",
  "",
  "watch(",
  "  () => route.query.trace,",
  "  (newTrace, oldTrace) => {",
  "    const nextTrace = String(newTrace || \"\").trim();",
  "    const previousTrace = String(oldTrace || \"\").trim();",
  "    if (nextTrace && nextTrace !== previousTrace) {",
  "      applyDeepTrace(nextTrace);",
  "    }",
  "  }",
  ");",
  "",
  "onMounted(() => {",
  "  // Warm only the cheap experiment-name list. Resume checkpoint details are lazy.",
  "  void buildHistoryTraceList({ loadResume: false });",
  "  applyDeepTrace(route.query.trace);",
  "});",
].join("\n");

if (!pg.includes(mountedOld)) {
  console.error("[patch-route-p57] FAILED: deep-trace onMounted anchor drifted.");
  process.exit(1);
}
pg = pg.replace(mountedOld, mountedNew);

fs.writeFileSync(pgPath, pg);
console.log("[patch-route-p57] reactive continuation/branch route switching applied");
