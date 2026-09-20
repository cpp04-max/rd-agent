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
  "  \"Finance Whole Pipeline\":\n" +
  "    \"Reproduce RD-Agent(Q) (arXiv:2505.15155): jointly optimize alpha factors and the return-forecasting model on the CSI300 universe. Each round, form a hypothesis from quant domain priors, implement factor and model code with Co-STEER, run a qlib backtest, and use the feedback (IC/RankIC, annualized excess return, information ratio, max drawdown) to choose the next research direction. Alternate factor engineering and model improvement, targeting higher annualized return from fewer, higher-quality factors.\",\n" +
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
  "        <div class=\"live-prog\">\n" +
  "          <div class=\"live-prog-row\">\n" +
  "            <span class=\"live-prog-label\">Loop {{ wfLoop }} · stage {{ wfStepIndex + 1 }}/{{ wfTotal }}</span>\n" +
  "            <span class=\"live-prog-name\">{{ wfStepName }}</span>\n" +
  "            <span class=\"live-prog-time\">elapsed {{ fmtDur(wfElapsedSec) }} · stage {{ fmtDur(stageSec(wfStepName)) }} · est. left this loop {{ fmtDur(wfRemainingSec) }}</span>\n" +
  "          </div>\n" +
  "          <div class=\"live-bar\"><div class=\"live-bar-fill\" :style=\"{ width: wfPct + '%' }\"></div></div>\n" +
  "          <div class=\"live-stages\">\n" +
  "            <div v-for=\"(st, i) in wfStages\" :key=\"st\" class=\"live-stage\" :class=\"stageClass(i)\">\n" +
  "              <span class=\"live-stage-name\">{{ st }}</span>\n" +
  "              <span class=\"live-stage-t\">{{ fmtDur(stageSec(st)) }}</span>\n" +
  "            </div>\n" +
  "          </div>\n" +
  "          <div class=\"live-prog-note\">≈ {{ fmtDur(wfPerLoopSec) }} per loop · multiply by your loop count for a rough total</div>\n" +
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
  "// ---- workflow progress / ETA state (parsed from the backend tqdm lines) ----\n" +
  "const wfStages = [\"direct_exp_gen\", \"coding\", \"running\", \"feedback\", \"record\"];\n" +
  "const wfLoop = ref(0);\n" +
  "const wfStepIndex = ref(0);\n" +
  "const wfTotal = ref(wfStages.length);\n" +
  "const wfStepName = ref(wfStages[0]);\n" +
  "const wfPct = ref(0);\n" +
  "const wfElapsedSec = ref(0);\n" +
  "const wfRemainingSec = ref(0);\n" +
  "const wfPerLoopSec = ref(0);\n" +
  "const wfStageStart = {};\n" +
  "const wfStageDone = {};\n" +
  "let wfCurStage = \"\";\n" +
  "let wfCurLoop = -1;\n" +
  "\n" +
  "const parseDur = (s) => {\n" +
  "  const p = String(s).split(\":\").map(Number);\n" +
  "  if (p.length === 3) return p[0] * 3600 + p[1] * 60 + p[2];\n" +
  "  if (p.length === 2) return p[0] * 60 + p[1];\n" +
  "  return p[0] || 0;\n" +
  "};\n" +
  "const fmtDur = (sec) => {\n" +
  "  sec = Math.max(0, Math.round(sec || 0));\n" +
  "  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s2 = sec % 60;\n" +
  "  return (h ? h + \":\" + String(m).padStart(2, \"0\") : String(m)) + \":\" + String(s2).padStart(2, \"0\");\n" +
  "};\n" +
  "const stageSec = (st) => {\n" +
  "  if (st === wfCurStage) return Math.max(0, (wfElapsedSec.value || 0) - (wfStageStart[st] || 0));\n" +
  "  return wfStageDone[st] || 0;\n" +
  "};\n" +
  "const stageClass = (i) => {\n" +
  "  const st = wfStages[i];\n" +
  "  if (st === wfCurStage) return \"active\";\n" +
  "  return i < wfStages.indexOf(wfCurStage) ? \"done\" : \"todo\";\n" +
  "};\n" +
  "const resetWf = () => {\n" +
  "  wfCurLoop = -1; wfCurStage = \"\";\n" +
  "  for (const k of Object.keys(wfStageStart)) delete wfStageStart[k];\n" +
  "  for (const k of Object.keys(wfStageDone)) delete wfStageDone[k];\n" +
  "  wfLoop.value = 0; wfStepIndex.value = 0; wfTotal.value = wfStages.length;\n" +
  "  wfStepName.value = wfStages[0]; wfPct.value = 0;\n" +
  "  wfElapsedSec.value = 0; wfRemainingSec.value = 0; wfPerLoopSec.value = 0;\n" +
  "};\n" +
  "const WF_RE = /Workflow Progress:\\s*(\\d+)%\\|[^|]*\\|\\s*(\\d+)\\/(\\d+)\\s*\\[([0-9:]+)<([0-9:]+),\\s*[^,]+,\\s*loop_index=(\\d+),\\s*step_index=(\\d+),\\s*step_name=([^\\],]+)/;\n" +
  "const ingestProgress = (text) => {\n" +
  "  for (const ln of String(text || \"\").split(\"\\n\")) {\n" +
  "    const m = WF_RE.exec(ln);\n" +
  "    if (!m) continue;\n" +
  "    const pct = +m[1], total = +m[3], el = parseDur(m[4]), rem = parseDur(m[5]);\n" +
  "    const loop = +m[6], sidx = +m[7], sname = m[8].trim();\n" +
  "    if (loop !== wfCurLoop) {\n" +
  "      wfCurLoop = loop; wfCurStage = \"\";\n" +
  "      for (const k of Object.keys(wfStageStart)) delete wfStageStart[k];\n" +
  "      for (const k of Object.keys(wfStageDone)) delete wfStageDone[k];\n" +
  "    }\n" +
  "    if (sname !== wfCurStage) {\n" +
  "      if (wfCurStage) wfStageDone[wfCurStage] = Math.max(0, el - (wfStageStart[wfCurStage] || 0));\n" +
  "      wfCurStage = sname; wfStageStart[sname] = el;\n" +
  "    }\n" +
  "    wfLoop.value = loop; wfStepIndex.value = sidx; wfTotal.value = total; wfStepName.value = sname;\n" +
  "    wfPct.value = pct; wfElapsedSec.value = el; wfRemainingSec.value = rem;\n" +
  "    if (loop > 0) wfPerLoopSec.value = el / loop;\n" +
  "  }\n" +
  "};\n" +
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
  "    resetWf();\n" +
  "  }\n" +
  "  fetch(`/progress?id=${encodeURIComponent(activityTraceId)}&offset=${activityOffset}`)\n" +
  "    .then((r) => (r.ok ? r.json() : null))\n" +
  "    .then((j) => {\n" +
  "      if (!j) throw new Error(\"bad response\");\n" +
  "      if (typeof j.offset === \"number\") activityOffset = j.offset;\n" +
  "      if (j.text) {\n" +
  "        activityText.value += j.text;\n" +
  "        ingestProgress(j.text);\n" +
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
  ".live-prog { padding: 8px 12px 10px; border-bottom: 1px solid #e6edf7; background: #fff; }\n" +
  ".live-prog-row { display: flex; gap: 10px; align-items: baseline; font-size: 12px; color: #334155; flex-wrap: wrap; }\n" +
  ".live-prog-label { font-weight: 600; }\n" +
  ".live-prog-name { color: #1677ff; font-weight: 600; }\n" +
  ".live-prog-time { color: #64748b; margin-left: auto; font-variant-numeric: tabular-nums; }\n" +
  ".live-bar { height: 8px; background: #e6edf7; border-radius: 999px; overflow: hidden; margin: 6px 0 8px; }\n" +
  ".live-bar-fill { height: 100%; background: linear-gradient(90deg, #1677ff, #4f9cff); width: 0%; transition: width .4s ease; }\n" +
  ".live-stages { display: flex; gap: 6px; flex-wrap: wrap; }\n" +
  ".live-stage { border: 1px solid #e2e8f0; border-radius: 8px; padding: 3px 8px; font-size: 11px; color: #64748b; background: #f8fafc; display: flex; gap: 6px; align-items: center; }\n" +
  ".live-stage .live-stage-t { font-variant-numeric: tabular-nums; color: #94a3b8; }\n" +
  ".live-stage.done { background: #eefaf1; border-color: #bbe7c8; color: #15803d; }\n" +
  ".live-stage.done .live-stage-t { color: #15803d; }\n" +
  ".live-stage.active { background: #eef4ff; border-color: #bcd4ff; color: #123a6d; font-weight: 600; }\n" +
  ".live-stage.active .live-stage-t { color: #123a6d; }\n" +
  ".live-prog-note { margin-top: 6px; font-size: 11px; color: #94a3b8; }\n" +
  ".live-log { margin: 0; padding: 8px 12px; max-height: 190px; overflow: auto; background: #0f172a; color: #c8e6c9; font: 11px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; white-space: pre-wrap; word-break: break-word; }\n" +
  "</style>\n";

s3 = s3 + activityStyle;

fs.writeFileSync(p2, s3);
console.log("[patch-frontend] live activity panel applied to PlaygroundPage.vue");

// ------------------------------- single-scenario dropdown (RD-Agent(Q) only)
// The deployment is scope-locked to "Finance Whole Pipeline" at /upload, so rewrite
// the SOURCE scenario lists (not just runtime arrays) so the built bundle's
// Playground dropdown genuinely contains only that one scenario on both tabs.
const p4 = "/src/web/src/views/Playground.vue";
let s4 = fs.readFileSync(p4, "utf8");

const filterOld =
  "const visibleContinuousScenarioList = continuousScenarioList.filter(\n" +
  '  (scenario) => scenario.name !== "Data Science"\n' +
  ");";
const filterNew =
  "const visibleContinuousScenarioList = continuousScenarioList.filter(\n" +
  '  (scenario) => scenario.name === "Finance Whole Pipeline"\n' +
  ");";
if (!s4.includes(filterOld)) {
  console.error("[patch-frontend] FAILED: visibleContinuousScenarioList filter anchor drifted.");
  process.exit(1);
}
s4 = s4.replace(filterOld, filterNew);

// Replace the whole guidedScenarioList literal with a copy of the (now single-entry)
// continuous list, so the second tab shows the same one scenario.
const gStart = s4.indexOf("const guidedScenarioList = [");
const sRef = s4.indexOf("const scenarioList = ref(visibleContinuousScenarioList);");
if (gStart === -1 || sRef === -1 || gStart > sRef) {
  console.error("[patch-frontend] FAILED: guidedScenarioList/scenarioList anchors drifted.");
  process.exit(1);
}
s4 =
  s4.slice(0, gStart) +
  "const guidedScenarioList = [...visibleContinuousScenarioList];\n\n" +
  s4.slice(sRef);

fs.writeFileSync(p4, s4);
console.log("[patch-frontend] single-scenario dropdown (source-level) applied to Playground.vue");
