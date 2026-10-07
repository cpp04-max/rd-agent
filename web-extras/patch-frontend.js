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

// Show live progress + ETA inside the "User Interaction Required" waiting state so a
// long (but healthy) wait is transparent and it never looks like a dead spinner.
const waitingOld =
  "          <div class=\"interaction-waiting\">\n" +
  "            <span class=\"interaction-waiting-spinner\" aria-hidden=\"true\"></span>\n" +
  "            <span>R&amp;D-Agent is generating hypothesis</span>\n" +
  "          </div>\n";
const waitingNew =
  "          <div class=\"interaction-waiting\">\n" +
  "            <span class=\"interaction-waiting-spinner\" aria-hidden=\"true\"></span>\n" +
  "            <span>R&amp;D-Agent is working — {{ activityPhase }}</span>\n" +
  "          </div>\n" +
  "          <div class=\"interaction-waiting-prog\">\n" +
  "            <div class=\"live-prog-row\">\n" +
  "              <span class=\"live-prog-label\">Loop {{ wfLoop }} · stage {{ wfStepIndex + 1 }}/{{ wfTotal }} · {{ wfStepName }}</span>\n" +
  "              <span class=\"live-prog-time\">elapsed {{ fmtDur(wfElapsedSec) }} · est. left {{ fmtDur(wfRemainingSec) }}</span>\n" +
  "            </div>\n" +
  "            <div class=\"live-bar\"><div class=\"live-bar-fill\" :style=\"{ width: wfPct + '%' }\"></div></div>\n" +
  "          </div>\n";
// Hide the interaction dialog entirely once the run process is dead: a crash logs no
// END on the path the dialog watches, so the waiting state would otherwise spin forever.
const dialogBoxOld = "<div class=\"dialog-box\" v-if=\"userInteractionVisible && !userInteractionMinimized\">";
const dialogBoxNew = "<div class=\"dialog-box\" v-if=\"userInteractionVisible && !userInteractionMinimized && activityRunning\">";
if (s3.includes(dialogBoxOld)) {
  s3 = s3.replace(dialogBoxOld, dialogBoxNew);
} else {
  console.warn("[patch-frontend] WARN: dialog-box v-if drifted; alive-gate skipped.");
}
if (s3.includes(waitingOld)) {
  s3 = s3.replace(waitingOld, waitingNew);
} else {
  console.warn("[patch-frontend] WARN: interaction-waiting block drifted; progress-in-dialog skipped.");
}

const activityCode =
  "const activityText = ref(\"\");\n" +
  "const activityPhase = ref(\"starting…\");\n" +
  "const activityCollapsed = ref(false);\n" +
  "const activityRunning = ref(true);\n" +
  "const activityLogEl = ref(null);\n" +
  "let activityOffset = 0;\n" +
  "let activityTimer = null;\n" +
  "let activityLastTraceId = \"\";\n" +
  "let activityDeadPolls = 0;\n" +
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
  "    activityDeadPolls = 0;\n" +
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
  "        activityDeadPolls += 1;\n" +
  "        if (activityDeadPolls < 8) {\n" +
  "          if (!activityText.value) activityPhase.value = \"waiting for run output…\";\n" +
  "          activityTimer = setTimeout(progressPoll, 3000);\n" +
  "          return;\n" +
  "        }\n" +
  "        activityRunning.value = false;\n" +
  "        userInteractionWaitingHypothesis.value = false;\n" +
  "        userInteractionVisible.value = false;\n" +
  "        activityPhase.value = activityText.value ? \"run ended\" : \"run finished (no captured output)\";\n" +
  "        return;\n" +
  "      }\n" +
  "      activityDeadPolls = 0;\n" +
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
  ".interaction-waiting-prog { padding: 4px 0 8px; }\n" +
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

// -------------------------------------- tolerant RESULT-tab metric mapping (P35)
// The qlib backtest may report with_cost keys (and as few as 3 of them); the old
// parser only understood the 4 without_cost keys when the dict had >4 entries, so
// successful runs rendered an empty RESULT tab. Accept both variants, any size.
const p5 = "/src/web/src/views/PlaygroundPage.vue";
let s5 = fs.readFileSync(p5, "utf8");
const metricOld = "      if (Object.keys(metricResult).length > 4) {\n        onePollDataObj.feedbackMetric = {\n          IC: metricResult[\"IC\"],\n          \"1day.excess_return_without_cost.annualized_return\":\n            metricResult[\"1day.excess_return_without_cost.annualized_return\"],\n          \"1day.excess_return_without_cost.information_ratio\":\n            metricResult[\"1day.excess_return_without_cost.information_ratio\"],\n          \"1day.excess_return_without_cost.max_drawdown\":\n            metricResult[\"1day.excess_return_without_cost.max_drawdown\"],\n        };\n      } else {\n        onePollDataObj.feedbackMetric = metricResult;\n      }\n";
const metricNew = "      const pickMetric = (obj, names) => {\n        for (const n of names) {\n          if (obj && obj[n] !== undefined && obj[n] !== null) return obj[n];\n        }\n        return undefined;\n      };\n      onePollDataObj.feedbackMetric = {\n        IC: pickMetric(metricResult, [\"IC\", \"Rank IC\"]),\n        \"1day.excess_return_without_cost.annualized_return\": pickMetric(metricResult, [\n          \"1day.excess_return_without_cost.annualized_return\",\n          \"1day.excess_return_with_cost.annualized_return\",\n        ]),\n        \"1day.excess_return_without_cost.information_ratio\": pickMetric(metricResult, [\n          \"1day.excess_return_without_cost.information_ratio\",\n          \"1day.excess_return_with_cost.information_ratio\",\n        ]),\n        \"1day.excess_return_without_cost.max_drawdown\": pickMetric(metricResult, [\n          \"1day.excess_return_without_cost.max_drawdown\",\n          \"1day.excess_return_with_cost.max_drawdown\",\n        ]),\n      };\n";
if (!s5.includes(metricOld)) {
  console.error("[patch-frontend] FAILED: feedback.metric parser anchor drifted.");
  process.exit(1);
}
s5 = s5.replace(metricOld, metricNew);
fs.writeFileSync(p5, s5);
console.log("[patch-frontend] tolerant RESULT metric mapping applied to PlaygroundPage.vue");

// ------------------------- P36: lossless/dynamic RESULT metrics -------------------------
// ResultPage/chartBox iterate Object.keys(feedbackMetric), so keeping EVERY raw qlib
// metric (Rank IC, ICIR, turnover, with_cost.*, ...) makes the Result tab dynamic and
// future-proof, while the canonical four headline keys are still guaranteed present.
const p6 = "/src/web/src/views/PlaygroundPage.vue";
let s6 = fs.readFileSync(p6, "utf8");
const a1o = "      onePollDataObj.feedbackMetric = {\n        IC: pickMetric(metricResult, [\"IC\", \"Rank IC\"]),\n";
const a1n = "      onePollDataObj.feedbackMetric = Object.assign({}, metricResult, {\n        IC: pickMetric(metricResult, [\"IC\", \"Rank IC\"]),\n";
const a2o = "          \"1day.excess_return_with_cost.max_drawdown\",\n        ]),\n      };\n";
const a2n = "          \"1day.excess_return_with_cost.max_drawdown\",\n        ]),\n      });\n      for (const k of Object.keys(onePollDataObj.feedbackMetric)) {\n        if (onePollDataObj.feedbackMetric[k] === undefined) {\n          delete onePollDataObj.feedbackMetric[k];\n        }\n      }\n";
if (!s6.includes(a1o) || !s6.includes(a2o)) {
  console.error("[patch-frontend] FAILED: P36 metric-merge anchors drifted.");
  process.exit(1);
}
s6 = s6.replace(a1o, a1n).replace(a2o, a2n);
fs.writeFileSync(p6, s6);
console.log("[patch-frontend] lossless dynamic RESULT metrics applied to PlaygroundPage.vue");

// ------------------------- P37: make RESULT independent of END + null-safe rendering -------------------------
// A completed/usable loop must be visible in RESULT even if the synthetic END event was
// not persisted/replayed (common after a redeploy). Also make ResultPage tolerant of
// partial historical traces: metrics/feedback should still render when a hypothesis
// event is missing, and missing metric fields must never crash the whole component.
const p7 = "/src/web/src/views/PlaygroundPage.vue";
let s7 = fs.readFileSync(p7, "utf8");

const resultStateAnchor = "const endTagHandled = ref(false);\n";
const resultStateReplacement =
  "const endTagHandled = ref(false);\n" +
  "\n" +
  "const hasStructuredResultPayload = (item) => {\n" +
  "  if (!item || typeof item !== \"object\") return false;\n" +
  "  return Boolean(\n" +
  "    item.researchHypothesis ||\n" +
  "    item.researcTasks ||\n" +
  "    item.feedbackHypothesis ||\n" +
  "    item.feedbackMetric ||\n" +
  "    item.feedbackCharts ||\n" +
  "    (Array.isArray(item.evolvingCodes) && item.evolvingCodes.length) ||\n" +
  "    (Array.isArray(item.evolvingFeedbacks) && item.evolvingFeedbacks.length)\n" +
  "  );\n" +
  "};\n" +
  "\n" +
  "// allData only receives the last loop when END is observed. Historical traces can\n" +
  "// be replayed without END immediately after a redeploy, so include the current\n" +
  "// assembled loop as a RESULT candidate until END has been handled.\n" +
  "const resultData = computed(() => {\n" +
  "  const rows = Array.isArray(allData.value) ? [...allData.value] : [];\n" +
  "  // currentData is a ref updated after every /trace batch; using it here makes\n" +
  "  // this computed reactive even though onePollDataObj itself is a plain object.\n" +
  "  const current =\n" +
  "    currentData.value && typeof currentData.value === \"object\"\n" +
  "      ? currentData.value\n" +
  "      : onePollDataObj;\n" +
  "  if (!endTagHandled.value && hasStructuredResultPayload(current)) {\n" +
  "    rows.push({\n" +
  "      ...current,\n" +
  "      evolvingCodes: Array.isArray(current.evolvingCodes) ? [...current.evolvingCodes] : [],\n" +
  "      evolvingFeedbacks: Array.isArray(current.evolvingFeedbacks) ? [...current.evolvingFeedbacks] : [],\n" +
  "    });\n" +
  "  }\n" +
  "  return rows.filter(hasStructuredResultPayload);\n" +
  "});\n";

if (!s7.includes(resultStateAnchor)) {
  console.error("[patch-frontend] FAILED: P37 result-state anchor drifted.");
  process.exit(1);
}
s7 = s7.replace(resultStateAnchor, resultStateReplacement);

const resultTabOld = '              v-if="allData.length != 0"';
const resultTabNew = '              v-if="resultData.length != 0 || updateEnd"';
const resultLoadingOld = '            <div class="tab-item-btn" v-if="allData.length == 0 && !stopFlag">';
const resultLoadingNew = '            <div class="tab-item-btn" v-if="resultData.length == 0 && !updateEnd && !stopFlag">';
const resultPropOld = '            :currentData="allData"';
const resultPropNew = '            :currentData="resultData"';

for (const [oldText, newText, label] of [
  [resultTabOld, resultTabNew, "RESULT tab visibility"],
  [resultLoadingOld, resultLoadingNew, "RESULT loading visibility"],
  [resultPropOld, resultPropNew, "RESULT data prop"],
]) {
  if (!s7.includes(oldText)) {
    console.error("[patch-frontend] FAILED: P37 " + label + " anchor drifted.");
    process.exit(1);
  }
  s7 = s7.replace(oldText, newText);
}
fs.writeFileSync(p7, s7);
console.log("[patch-frontend] P37 RESULT current-loop fallback applied to PlaygroundPage.vue");

const p8 = "/src/web/src/views/ResultPage.vue";
let s8 = fs.readFileSync(p8, "utf8");
const updateStart = s8.indexOf("const updateData = () => {");
const updateWatch = s8.indexOf("\nwatch(\n  () => [props.currentData", updateStart);
if (updateStart === -1 || updateWatch === -1 || updateWatch <= updateStart) {
  console.error("[patch-frontend] FAILED: P37 ResultPage updateData anchors drifted.");
  process.exit(1);
}

const robustUpdateData = `const updateData = () => {
  const table = [];
  const metric = {};
  const rows = Array.isArray(currentData.value) ? currentData.value : [];

  const addMetric = (name, value, index, description) => {
    if (value === undefined || value === null || value === "") return;
    if (!metric[name]) metric[name] = [];
    metric[name].push({
      name: "Round" + (index + 1),
      value,
      desc: description || "",
    });
  };

  rows.forEach((rawItem, index) => {
    const item = rawItem && typeof rawItem === "object" ? rawItem : {};
    const hypothesis =
      item.researchHypothesis && typeof item.researchHypothesis === "object"
        ? item.researchHypothesis
        : {};
    const feedback =
      item.feedbackHypothesis && typeof item.feedbackHypothesis === "object"
        ? item.feedbackHypothesis
        : {};
    const metrics =
      item.feedbackMetric && typeof item.feedbackMetric === "object"
        ? item.feedbackMetric
        : {};

    const hypothesisText =
      hypothesis.hypothesis ||
      feedback.hypothesis ||
      feedback.new_hypothesis ||
      ("Research loop " + (index + 1));
    const decision = normalizeDecision(feedback.decision);
    const hasStructuredPayload =
      Boolean(item.researchHypothesis) ||
      Boolean(item.feedbackHypothesis) ||
      Object.keys(metrics).length > 0 ||
      Boolean(item.feedbackCharts) ||
      (Array.isArray(item.evolvingCodes) && item.evolvingCodes.length > 0) ||
      (Array.isArray(item.evolvingFeedbacks) && item.evolvingFeedbacks.length > 0);

    if (hasStructuredPayload && (!switchValue.value || decision === true)) {
      table.push({
        num: index,
        hypothesis: hypothesisText,
        component: hypothesis.component || "",
        downloadFiles: getLoopLastEvoFiles(item),
        reason:
          feedback.reason ||
          feedback.hypothesis_evaluation ||
          feedback.feedback ||
          "",
        observations: feedback.observations || "",
        decision: decision === true,
      });
    }

    if (!switchValue.value || decision === true) {
      Object.entries(metrics).forEach(([name, value]) => {
        addMetric(name, value, index, hypothesisText);
      });
    }
  });

  tableData.value = table;
  metricData.value = metric;
};`;

s8 = s8.slice(0, updateStart) + robustUpdateData + s8.slice(updateWatch);

const resultContentAnchor = '      <div class="result-content">\n        <h2>Metrics</h2>';
const resultContentReplacement =
  '      <div class="result-content">\n' +
  '        <div\n' +
  '          v-if="tableData.length === 0 && Object.keys(metricData || {}).length === 0"\n' +
  '          class="result-empty-state"\n' +
  '        >\n' +
  '          No structured result events are available for this trace yet. The raw run log can still be downloaded above.\n' +
  '        </div>\n' +
  '        <h2>Metrics</h2>';
if (!s8.includes(resultContentAnchor)) {
  console.error("[patch-frontend] FAILED: P37 ResultPage empty-state anchor drifted.");
  process.exit(1);
}
s8 = s8.replace(resultContentAnchor, resultContentReplacement);

const styleAnchor = ".result-component {\n  height: 100%;";
const styleReplacement =
  ".result-component {\n" +
  "  height: 100%;\n" +
  "  .result-empty-state {\n" +
  "    margin: 0 0 1em;\n" +
  "    padding: 0.8em 1em;\n" +
  "    border: 1px solid #d7e1ff;\n" +
  "    border-radius: 12px;\n" +
  "    background: #f7f9ff;\n" +
  "    color: #5d6780;\n" +
  "    font-size: 0.9em;\n" +
  "  }";
if (!s8.includes(styleAnchor)) {
  console.error("[patch-frontend] FAILED: P37 ResultPage style anchor drifted.");
  process.exit(1);
}
s8 = s8.replace(styleAnchor, styleReplacement);

fs.writeFileSync(p8, s8);
console.log("[patch-frontend] P37 null-safe RESULT rendering applied to ResultPage.vue");

// ------------------------- P42: Continue / Branch experiment UI -------------------------
const apiPathP42 = "/src/web/src/utils/api.js";
let apiP42 = fs.readFileSync(apiPathP42, "utf8");
const apiP42Anchor = `export function getStdoutDownloadUrl(traceId) {
    const query = new URLSearchParams({ id: traceId });
    return url + "stdout?" + query.toString();
}
`;
const apiP42New = apiP42Anchor + `
export function getResumeOptions(traceId) {
    const query = new URLSearchParams({ id: traceId });
    return request({
        url: url + "resume/options?" + query.toString(),
        method: "get"
    });
}

export function resumeTrace(data) {
    return request({
        url: url + "resume",
        method: "post",
        headers: {
            "Content-Type": "application/json"
        },
        data: data
    });
}
`;
if (!apiP42.includes(apiP42Anchor)) {
  console.error("[patch-frontend] FAILED: P42 api.js anchor drifted.");
  process.exit(1);
}
apiP42 = apiP42.replace(apiP42Anchor, apiP42New);
fs.writeFileSync(apiPathP42, apiP42);
console.log("[patch-frontend] P42 resume API helpers applied to api.js");

const resultP42 = "/src/web/src/views/ResultPage.vue";
let resultS42 = fs.readFileSync(resultP42, "utf8");

const importP42Old = 'import { getStdoutDownloadUrl } from "../utils/api";';
const importP42New =
  'import { getStdoutDownloadUrl, getResumeOptions, resumeTrace } from "../utils/api";';
if (!resultS42.includes(importP42Old)) {
  console.error("[patch-frontend] FAILED: P42 ResultPage import anchor drifted.");
  process.exit(1);
}
resultS42 = resultS42.replace(importP42Old, importP42New);

const toolbarP42Old = `      <div class="download-btn-item" @click="downloadAllLoops">
        <span class="download-icon"></span>
        <span>All loop files</span>
      </div>
    </div>
`;
const toolbarP42New = `      <div class="download-btn-item" @click="downloadAllLoops">
        <span class="download-icon"></span>
        <span>All loop files</span>
      </div>
      <button
        class="resume-experiment-btn"
        type="button"
        @click="openResumeDialog"
        :disabled="resumeLoading || resumeSubmitting"
      >
        {{ resumeLoading ? "CHECKING…" : "CONTINUE / BRANCH" }}
      </button>
    </div>
`;
if (!resultS42.includes(toolbarP42Old)) {
  console.error("[patch-frontend] FAILED: P42 ResultPage toolbar anchor drifted.");
  process.exit(1);
}
resultS42 = resultS42.replace(toolbarP42Old, toolbarP42New);

const bgP42Anchor = '    <div class="bg-content">';
const dialogP42 = `    <div class="resume-overlay" v-if="resumeDialogVisible">
      <div class="resume-card">
        <div class="resume-card-head">
          <div>
            <h2>Continue or branch this experiment</h2>
            <p>
              The source trace is never overwritten. A new trace is created from the
              selected checkpoint.
            </p>
          </div>
          <button class="resume-close" type="button" @click="closeResumeDialog">×</button>
        </div>

        <div v-if="resumeError" class="resume-error">{{ resumeError }}</div>

        <template v-if="resumeInfo && resumeInfo.resumable">
          <label class="resume-field">
            <span>Resume from</span>
            <select v-model="resumeCheckpoint">
              <option value="latest">
                Latest state · Loop {{ resumeInfo.latest?.loop_number || "?" }} ·
                after {{ resumeInfo.latest?.step_name || "checkpoint" }}
              </option>
              <option
                v-for="checkpoint in resumeInfo.checkpoints"
                :key="checkpoint.key"
                :value="checkpoint.key"
              >
                {{ checkpoint.label }}
              </option>
            </select>
          </label>

          <div class="resume-grid">
            <label class="resume-field">
              <span>Additional loops</span>
              <input
                type="number"
                min="1"
                max="100"
                v-model.number="resumeAdditionalLoops"
              />
            </label>
            <label class="resume-field">
              <span>New time budget (hours)</span>
              <input
                type="number"
                min="0.25"
                max="72"
                step="0.25"
                v-model.number="resumeHours"
              />
            </label>
          </div>

          <label class="resume-field">
            <span>New research instruction (optional)</span>
            <textarea
              rows="5"
              v-model="resumeInstruction"
              placeholder="Example: Keep the current SOTA architecture. Focus the next experiments on recency bias, loss design and training optimization."
            ></textarea>
          </label>

          <div class="resume-hint">
            <strong>{{ resumeCheckpoint === "latest" ? "Continue" : "Branch" }}:</strong>
            {{
              resumeCheckpoint === "latest"
                ? "preserves the latest research state, including failed loops as negative evidence."
                : "starts a new research branch from the selected historical checkpoint."
            }}
          </div>

          <div class="resume-actions">
            <button type="button" class="resume-secondary" @click="closeResumeDialog">
              Cancel
            </button>
            <button
              type="button"
              class="resume-primary"
              @click="startResume"
              :disabled="resumeSubmitting"
            >
              {{ resumeSubmitting ? "STARTING…" : (resumeCheckpoint === "latest" ? "CONTINUE" : "CREATE BRANCH") }}
            </button>
          </div>
        </template>

        <div
          v-else-if="resumeInfo && !resumeInfo.resumable"
          class="resume-unavailable"
        >
          {{ resumeInfo.message || "This trace does not contain durable session checkpoints." }}
          <div class="resume-small">
            New runs created after the resume feature is deployed will be resumable.
          </div>
        </div>
      </div>
    </div>

`;
if (!resultS42.includes(bgP42Anchor)) {
  console.error("[patch-frontend] FAILED: P42 ResultPage bg-content anchor drifted.");
  process.exit(1);
}
resultS42 = resultS42.replace(bgP42Anchor, dialogP42 + bgP42Anchor);

const stateP42Anchor = "const metricData = ref(null);";
const stateP42New = stateP42Anchor + `
const resumeDialogVisible = ref(false);
const resumeLoading = ref(false);
const resumeSubmitting = ref(false);
const resumeInfo = ref(null);
const resumeError = ref("");
const resumeCheckpoint = ref("latest");
const resumeAdditionalLoops = ref(5);
const resumeHours = ref(6);
const resumeInstruction = ref("");
`;
if (!resultS42.includes(stateP42Anchor)) {
  console.error("[patch-frontend] FAILED: P42 ResultPage state anchor drifted.");
  process.exit(1);
}
resultS42 = resultS42.replace(stateP42Anchor, stateP42New);

const traceFnP42Anchor = "const getTraceId = () => {";
const methodsP42 = `const closeResumeDialog = () => {
  if (resumeSubmitting.value) return;
  resumeDialogVisible.value = false;
};

const openResumeDialog = async () => {
  const traceId = getTraceId();
  if (!traceId) {
    ElMessage.warning("Trace ID is not available.");
    return;
  }

  resumeLoading.value = true;
  resumeError.value = "";
  resumeInfo.value = null;
  try {
    const info = await getResumeOptions(traceId);
    resumeInfo.value = info || {};
    resumeCheckpoint.value = "latest";
    resumeDialogVisible.value = true;
  } catch (error) {
    const message =
      error?.response?.data?.error ||
      error?.message ||
      "Failed to load resume checkpoints.";
    resumeError.value = message;
    ElMessage.error(message);
  } finally {
    resumeLoading.value = false;
  }
};

const startResume = async () => {
  const traceId = getTraceId();
  const loops = Number(resumeAdditionalLoops.value);
  const hours = Number(resumeHours.value);
  if (!Number.isInteger(loops) || loops < 1 || loops > 100) {
    resumeError.value = "Additional loops must be an integer between 1 and 100.";
    return;
  }
  if (!Number.isFinite(hours) || hours <= 0 || hours > 72) {
    resumeError.value = "Time budget must be greater than 0 and at most 72 hours.";
    return;
  }

  resumeSubmitting.value = true;
  resumeError.value = "";
  try {
    const result = await resumeTrace({
      source_id: traceId,
      checkpoint: resumeCheckpoint.value,
      additional_loops: loops,
      all_duration: hours,
      instruction: resumeInstruction.value,
    });
    const newTraceId = result?.id;
    if (!newTraceId) {
      throw new Error("Resume started but no new trace ID was returned.");
    }
    ElMessage.success(
      resumeCheckpoint.value === "latest"
        ? "Continuation started."
        : "Research branch started."
    );
    resumeDialogVisible.value = false;
    window.location.href =
      window.location.origin +
      "/#/Playground?trace=" +
      encodeURIComponent(newTraceId);
  } catch (error) {
    resumeError.value =
      error?.response?.data?.error ||
      error?.message ||
      "Failed to start continuation.";
  } finally {
    resumeSubmitting.value = false;
  }
};

`;
if (!resultS42.includes(traceFnP42Anchor)) {
  console.error("[patch-frontend] FAILED: P42 ResultPage getTraceId anchor drifted.");
  process.exit(1);
}
resultS42 = resultS42.replace(traceFnP42Anchor, methodsP42 + traceFnP42Anchor);

const styleEndP42 = "</style>";
const styleP42 = `
.resume-experiment-btn {
  border: 1px solid #7657ff;
  border-radius: 10px;
  background: #ffffff;
  color: #5a42d6;
  padding: 0.55em 1em;
  font-size: 0.82em;
  font-weight: 800;
  cursor: pointer;
}
.resume-experiment-btn:disabled {
  opacity: 0.55;
  cursor: default;
}
.resume-overlay {
  position: fixed;
  inset: 0;
  z-index: 3000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(20, 24, 40, 0.42);
}
.resume-card {
  width: min(680px, 94vw);
  max-height: 88vh;
  overflow: auto;
  box-sizing: border-box;
  padding: 24px;
  border-radius: 18px;
  background: #fff;
  box-shadow: 0 24px 80px rgba(35, 42, 78, 0.24);
  color: #252938;
}
.resume-card-head {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  align-items: flex-start;
  margin-bottom: 18px;
}
.resume-card-head h2 {
  margin: 0 0 4px;
  font-size: 1.2em;
}
.resume-card-head p,
.resume-small {
  margin: 0;
  color: #727a92;
  font-size: 0.86em;
  line-height: 1.55;
}
.resume-close {
  border: 0;
  background: transparent;
  font-size: 1.6em;
  cursor: pointer;
}
.resume-field {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin: 14px 0;
}
.resume-field > span {
  font-size: 0.86em;
  font-weight: 800;
}
.resume-field select,
.resume-field input,
.resume-field textarea {
  box-sizing: border-box;
  width: 100%;
  border: 1px solid #ccd4e8;
  border-radius: 10px;
  background: #fff;
  padding: 10px 12px;
  color: #2b3040;
  font: inherit;
}
.resume-field textarea {
  resize: vertical;
}
.resume-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.resume-hint,
.resume-unavailable,
.resume-error {
  margin: 14px 0;
  padding: 11px 13px;
  border-radius: 10px;
  font-size: 0.86em;
  line-height: 1.5;
}
.resume-hint {
  background: #f5f7ff;
  color: #525d78;
}
.resume-unavailable {
  background: #f7f8fb;
  color: #50586e;
}
.resume-error {
  background: #fff1f1;
  color: #a73535;
}
.resume-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
}
.resume-primary,
.resume-secondary {
  border-radius: 10px;
  padding: 9px 16px;
  font-weight: 800;
  cursor: pointer;
}
.resume-primary {
  border: 0;
  background: #6848ff;
  color: #fff;
}
.resume-primary:disabled {
  opacity: 0.55;
}
.resume-secondary {
  border: 1px solid #ccd4e8;
  background: #fff;
  color: #4f5870;
}
@media (max-width: 680px) {
  .resume-grid {
    grid-template-columns: 1fr;
    gap: 0;
  }
}

`;
const lastStyle = resultS42.lastIndexOf(styleEndP42);
if (lastStyle === -1) {
  console.error("[patch-frontend] FAILED: P42 ResultPage style end missing.");
  process.exit(1);
}
resultS42 =
  resultS42.slice(0, lastStyle) +
  styleP42 +
  resultS42.slice(lastStyle);

fs.writeFileSync(resultP42, resultS42);
console.log("[patch-frontend] P42 Continue / Branch UI applied to ResultPage.vue");

// ------------------------- P43: select experiment + loop from history -------------------------
const historyP43 = "/src/web/src/views/Playground.vue";
let historyS43 = fs.readFileSync(historyP43, "utf8");

const historyApiOld =
  'import { getHistoryTraceIds, uploadFile } from "../utils/api";';
const historyApiNew =
  'import { getHistoryTraceIds, uploadFile, getResumeOptions, resumeTrace } from "../utils/api";';
if (!historyS43.includes(historyApiOld)) {
  console.error("[patch-frontend] FAILED: P43 Playground api import anchor drifted.");
  process.exit(1);
}
historyS43 = historyS43.replace(historyApiOld, historyApiNew);

const historyPanelOld = `      <div class="main-content" v-show="showPanel == 3">
        <h1 class="h1">
          View traces from previous runs <br />
          and inspect their execution history.
        </h1>
        <div class="main-panel history-panel">
          <div class="title">Trace ID List</div>
          <div class="desc">
            <p>Pick a scenario first, then choose one of its trace names</p>
          </div>
          <div class="history-select-row">
            <div class="history-select-item">
              <div class="title small-config-title">Scenario</div>
              <smSelectComponent
                :scenarioList="historyScenarioList"
                :scenarioIndex="historyScenarioCheckedIndex"
                placeholder="Select a scenario"
                @scenarioCheckedItem="historyScenarioCheckedItem"
              ></smSelectComponent>
            </div>
            <div class="history-select-item">
              <div class="title small-config-title">Trace name</div>
              <smSelectComponent
                :scenarioList="historyTraceList"
                :scenarioIndex="historyTraceCheckedIndex"
                placeholder="Select a trace name"
                @scenarioCheckedItem="historyTraceCheckedItem"
              ></smSelectComponent>
            </div>
          </div>
          <div
            class="btn-main"
            :style="{
              'margin-top':
                scenarioChecked && scenarioChecked.upload ? '3.5em' : '7.5em',
            }"
          >
            <button class="gradient-border back" @click="Back">BACK</button>
            <button
              class="disable"
              :class="{
                active: historyTraceChecked,
                disable: !historyTraceChecked,
              }"
              @click="viewTracePage"
            >
              view trace
            </button>
          </div>
        </div>
      </div>`;

const historyPanelNew = `      <div class="main-content" v-show="showPanel == 3">
        <h1 class="h1">
          Continue a previous experiment <br />
          from any durable loop checkpoint.
        </h1>
        <div class="main-panel history-panel history-resume-panel">
          <div class="title">Select experiment</div>
          <div class="desc">
            <p>
              Choose a previous experiment, then choose the loop state you want to
              continue from. The original experiment is never modified.
            </p>
          </div>

          <div class="history-select-row">
            <div class="history-select-item">
              <div class="title small-config-title">Scenario</div>
              <smSelectComponent
                :scenarioList="historyScenarioList"
                :scenarioIndex="historyScenarioCheckedIndex"
                placeholder="Select a scenario"
                @scenarioCheckedItem="historyScenarioCheckedItem"
              ></smSelectComponent>
            </div>
            <div class="history-select-item">
              <div class="title small-config-title">Experiment</div>
              <smSelectComponent
                :scenarioList="historyTraceList"
                :scenarioIndex="historyTraceCheckedIndex"
                placeholder="Select an experiment"
                @scenarioCheckedItem="historyTraceCheckedItem"
              ></smSelectComponent>
            </div>
          </div>

          <div v-if="historyTraceChecked" class="history-resume-config">
            <div v-if="historyResumeLoading" class="history-resume-status">
              Loading durable loop checkpoints…
            </div>

            <div v-else-if="historyResumeError" class="history-resume-status error">
              {{ historyResumeError }}
            </div>

            <template v-else-if="historyResumeInfo && historyResumeInfo.resumable">
              <div class="history-resume-source">
                <span class="history-resume-source-label">Source experiment</span>
                <strong>{{ historyTraceChecked.name }}</strong>
                <span v-if="historyResumeInfo.resume_meta?.source_id" class="history-lineage">
                  branched from {{ historyResumeInfo.resume_meta.source_id }}
                </span>
              </div>

              <div class="history-resume-grid">
                <label class="history-resume-field">
                  <span>Continue from loop</span>
                  <select v-model="historyResumeCheckpoint">
                    <option
                      v-for="checkpoint in historyResumeLoopOptions"
                      :key="checkpoint.key"
                      :value="checkpoint.key"
                    >
                      {{ checkpoint.label }}
                    </option>
                  </select>
                </label>

                <label class="history-resume-field">
                  <span>Additional loops</span>
                  <input
                    type="number"
                    min="1"
                    max="100"
                    v-model.number="historyResumeAdditionalLoops"
                  />
                </label>

                <label class="history-resume-field">
                  <span>New time budget (hours)</span>
                  <input
                    type="number"
                    min="0.25"
                    max="72"
                    step="0.25"
                    v-model.number="historyResumeHours"
                  />
                </label>
              </div>

              <label class="history-resume-field history-resume-instruction">
                <span>New input / research instruction (optional)</span>
                <textarea
                  rows="5"
                  v-model="historyResumeInstruction"
                  placeholder="Example: Continue from this loop's SOTA state, but focus the next experiments on recency bias and cost-aware loss. Do not repeat the failed multi-window direction."
                ></textarea>
              </label>

              <div class="history-resume-note">
                The new run inherits the selected loop's research state, SOTA, factors,
                model history and prior evidence. Your new instruction is added as the
                active research direction for the continuation.
              </div>
            </template>

            <div
              v-else-if="historyResumeInfo && !historyResumeInfo.resumable"
              class="history-resume-status unavailable"
            >
              {{
                historyResumeInfo.message ||
                "This experiment does not contain durable resume checkpoints."
              }}
              <div class="history-resume-small">
                You can still view its results. Experiments created after P42/P43 is
                deployed will expose loop checkpoints here.
              </div>
            </div>
          </div>

          <div class="history-resume-actions">
            <button class="gradient-border back" @click="Back">BACK</button>
            <div class="history-resume-actions-right">
              <button
                class="history-secondary-btn"
                :disabled="!historyTraceChecked"
                @click="viewTracePage"
              >
                VIEW RESULT
              </button>
              <button
                class="history-primary-btn"
                :disabled="
                  !historyTraceChecked ||
                  !historyResumeInfo?.resumable ||
                  !historyResumeCheckpoint ||
                  historyResumeSubmitting
                "
                @click="startHistoryResume"
              >
                {{
                  historyResumeSubmitting
                    ? "STARTING…"
                    : "CONTINUE FROM SELECTED LOOP"
                }}
              </button>
            </div>
          </div>
        </div>
      </div>`;

if (!historyS43.includes(historyPanelOld)) {
  console.error("[patch-frontend] FAILED: P43 history panel anchor drifted.");
  process.exit(1);
}
historyS43 = historyS43.replace(historyPanelOld, historyPanelNew);

const historyStateAnchor = `const historyTraceChecked = ref(null);
const selectedFiles = ref([]);`;

const historyStateNew = `const historyTraceChecked = ref(null);
const historyResumeLoading = ref(false);
const historyResumeSubmitting = ref(false);
const historyResumeInfo = ref(null);
const historyResumeError = ref("");
const historyResumeCheckpoint = ref("");
const historyResumeAdditionalLoops = ref(5);
const historyResumeHours = ref(6);
const historyResumeInstruction = ref("");
const historyResumeLoopOptions = computed(() =>
  Array.isArray(historyResumeInfo.value?.loop_checkpoints)
    ? historyResumeInfo.value.loop_checkpoints
    : []
);
const selectedFiles = ref([]);`;

if (!historyS43.includes(historyStateAnchor)) {
  console.error("[patch-frontend] FAILED: P43 history state anchor drifted.");
  process.exit(1);
}
historyS43 = historyS43.replace(historyStateAnchor, historyStateNew);

const historyHandlersOld = `const historyScenarioCheckedItem = (data) => {
  selectLastHistoryTrace(data.scenarioChecked, data.scenarioCheckedIndex);
};

const historyTraceCheckedItem = (data) => {
  historyTraceCheckedIndex.value = data.scenarioCheckedIndex;
  historyTraceChecked.value = data.scenarioChecked;
};`;

const historyHandlersNew = `const resetHistoryResumeState = () => {
  historyResumeLoading.value = false;
  historyResumeInfo.value = null;
  historyResumeError.value = "";
  historyResumeCheckpoint.value = "";
  historyResumeInstruction.value = "";
};

const loadHistoryResumeOptions = async () => {
  resetHistoryResumeState();
  const traceId = String(historyTraceChecked.value?.id || "").trim();
  if (!traceId) return;

  if (!traceId.startsWith("Finance Whole Pipeline/")) {
    historyResumeInfo.value = {
      resumable: false,
      message: "Continuation is supported only for Finance Whole Pipeline experiments.",
    };
    return;
  }

  historyResumeLoading.value = true;
  const requestedTraceId = traceId;
  try {
    const info = await getResumeOptions(traceId);
    if (String(historyTraceChecked.value?.id || "").trim() !== requestedTraceId) {
      return;
    }
    historyResumeInfo.value = info || {};
    const loops = Array.isArray(info?.loop_checkpoints)
      ? info.loop_checkpoints
      : [];
    historyResumeCheckpoint.value = loops.length
      ? loops[loops.length - 1].key
      : info?.latest?.key || "";
  } catch (error) {
    if (String(historyTraceChecked.value?.id || "").trim() !== requestedTraceId) {
      return;
    }
    historyResumeError.value =
      error?.response?.data?.error ||
      error?.message ||
      "Failed to load experiment loop checkpoints.";
  } finally {
    if (String(historyTraceChecked.value?.id || "").trim() === requestedTraceId) {
      historyResumeLoading.value = false;
    }
  }
};

const historyScenarioCheckedItem = (data) => {
  selectLastHistoryTrace(data.scenarioChecked, data.scenarioCheckedIndex);
  void loadHistoryResumeOptions();
};

const historyTraceCheckedItem = (data) => {
  historyTraceCheckedIndex.value = data.scenarioCheckedIndex;
  historyTraceChecked.value = data.scenarioChecked;
  void loadHistoryResumeOptions();
};`;

if (!historyS43.includes(historyHandlersOld)) {
  console.error("[patch-frontend] FAILED: P43 history handler anchor drifted.");
  process.exit(1);
}
historyS43 = historyS43.replace(historyHandlersOld, historyHandlersNew);

const historyBuildOld = `  selectLastHistoryTrace(defaultScenario, defaultScenarioIndex);
}`;

const historyBuildNew = `  selectLastHistoryTrace(defaultScenario, defaultScenarioIndex);
  await loadHistoryResumeOptions();
}`;

if (!historyS43.includes(historyBuildOld)) {
  console.error("[patch-frontend] FAILED: P43 history list anchor drifted.");
  process.exit(1);
}
historyS43 = historyS43.replace(historyBuildOld, historyBuildNew);

const historyStartAnchor = `const viewTracePage = () => {`;

const historyStartMethods = `const startHistoryResume = async () => {
  const sourceId = String(historyTraceChecked.value?.id || "").trim();
  const loops = Number(historyResumeAdditionalLoops.value);
  const hours = Number(historyResumeHours.value);

  if (!sourceId || !historyResumeCheckpoint.value) {
    historyResumeError.value = "Select an experiment and a loop first.";
    return;
  }
  if (!Number.isInteger(loops) || loops < 1 || loops > 100) {
    historyResumeError.value =
      "Additional loops must be an integer between 1 and 100.";
    return;
  }
  if (!Number.isFinite(hours) || hours <= 0 || hours > 72) {
    historyResumeError.value =
      "New time budget must be greater than 0 and at most 72 hours.";
    return;
  }

  historyResumeSubmitting.value = true;
  historyResumeError.value = "";
  try {
    const result = await resumeTrace({
      source_id: sourceId,
      checkpoint: historyResumeCheckpoint.value,
      additional_loops: loops,
      all_duration: hours,
      instruction: historyResumeInstruction.value,
    });

    const newTraceId = String(result?.id || "").trim();
    if (!newTraceId) {
      throw new Error("Continuation started but no new trace ID was returned.");
    }

    applyScenarioConfig(getScenarioConfigByName("Finance Whole Pipeline"));
    id.value = newTraceId;
    showPlayground.value = true;
    ElMessage.success(
      "Continuation started from the selected experiment loop."
    );
  } catch (error) {
    historyResumeError.value =
      error?.response?.data?.error ||
      error?.message ||
      "Failed to continue the selected experiment.";
  } finally {
    historyResumeSubmitting.value = false;
  }
};

`;

if (!historyS43.includes(historyStartAnchor)) {
  console.error("[patch-frontend] FAILED: P43 viewTracePage anchor drifted.");
  process.exit(1);
}
historyS43 = historyS43.replace(
  historyStartAnchor,
  historyStartMethods + historyStartAnchor
);

const historyStyleEnd = "</style>";
const historyStyle = `
.history-resume-panel {
  width: min(980px, 92vw) !important;
  max-width: 980px !important;
}
.history-resume-config {
  margin-top: 1.4em;
  padding-top: 1.2em;
  border-top: 1px solid var(--card-border-color);
}
.history-resume-source {
  display: flex;
  flex-wrap: wrap;
  gap: 0.55em 0.8em;
  align-items: center;
  margin-bottom: 1em;
  padding: 0.75em 0.9em;
  border-radius: 12px;
  background: var(--card-bg-hover-color);
}
.history-resume-source-label,
.history-lineage {
  color: #6f7890;
  font-size: 0.82em;
}
.history-resume-grid {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr;
  gap: 1em;
}
.history-resume-field {
  display: flex;
  flex-direction: column;
  gap: 0.45em;
}
.history-resume-field > span {
  font-size: 0.9em;
  font-weight: 700;
  color: var(--text-color);
}
.history-resume-field select,
.history-resume-field input,
.history-resume-field textarea {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--card-border-color);
  border-radius: 10px;
  padding: 0.72em 0.85em;
  background: var(--bg-white);
  color: var(--text-color);
  font: inherit;
}
.history-resume-instruction {
  margin-top: 1em;
}
.history-resume-field textarea {
  min-height: 7em;
  resize: vertical;
}
.history-resume-note,
.history-resume-status {
  margin-top: 1em;
  padding: 0.8em 0.95em;
  border-radius: 10px;
  background: #f5f7ff;
  color: #5a637c;
  font-size: 0.86em;
  line-height: 1.55;
}
.history-resume-status.error {
  background: #fff1f1;
  color: #a73535;
}
.history-resume-status.unavailable {
  background: #f7f8fb;
}
.history-resume-small {
  margin-top: 0.35em;
  color: #7a8296;
  font-size: 0.92em;
}
.history-resume-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1em;
  margin-top: 1.6em;
}
.history-resume-actions-right {
  display: flex;
  gap: 0.8em;
}
.history-primary-btn,
.history-secondary-btn {
  min-height: 3em;
  border-radius: 999px;
  padding: 0 1.3em;
  font-weight: 800;
  cursor: pointer;
}
.history-primary-btn {
  border: 0;
  background: linear-gradient(90deg, #2667ff 0%, #9d41ff 100%);
  color: white;
}
.history-secondary-btn {
  border: 1px solid var(--card-border-color);
  background: var(--bg-white);
  color: var(--text-color);
}
.history-primary-btn:disabled,
.history-secondary-btn:disabled {
  opacity: 0.45;
  cursor: default;
}
@media (max-width: 900px) {
  .history-resume-grid {
    grid-template-columns: 1fr;
  }
  .history-resume-actions {
    align-items: stretch;
    flex-direction: column;
  }
  .history-resume-actions-right {
    flex-direction: column;
  }
}
`;

const historyStylePos = historyS43.lastIndexOf(historyStyleEnd);
if (historyStylePos === -1) {
  console.error("[patch-frontend] FAILED: P43 Playground style end missing.");
  process.exit(1);
}
historyS43 =
  historyS43.slice(0, historyStylePos) +
  historyStyle +
  historyS43.slice(historyStylePos);

fs.writeFileSync(historyP43, historyS43);
console.log("[patch-frontend] P43 experiment + loop resume selector applied to Playground.vue");

// ------------------------- P44: readable grouped metric UI -------------------------
// The upstream chartBox renders every metric in a single flex row with width=100/N,
// which makes long Qlib names unreadable once P36 exposes all metrics. Replace it
// with a responsive card grid, PM-friendly labels, group tabs, latest values, and
// explicit metric direction hints while preserving every raw metric.
const metricBoxP44 = "/src/web/src/components/chartBox.vue";
const metricBoxNewP44 = "<template>\n  <div class=\"metric-panel\">\n    <div class=\"metric-toolbar\" v-if=\"availableTabs.length > 1\">\n      <div class=\"metric-tabs\" role=\"tablist\" aria-label=\"Metric groups\">\n        <button\n          v-for=\"tab in availableTabs\"\n          :key=\"tab.key\"\n          type=\"button\"\n          class=\"metric-tab\"\n          :class=\"{ active: activeTab === tab.key }\"\n          @click=\"activeTab = tab.key\"\n        >\n          <span>{{ tab.label }}</span>\n          <span class=\"metric-tab-count\">{{ tab.count }}</span>\n        </button>\n      </div>\n      <div class=\"metric-help\">\n        <span>↑ higher is better</span>\n        <span>↓ lower is better</span>\n        <span>0↑ closer to zero is better</span>\n      </div>\n    </div>\n\n    <div class=\"chart-box\">\n      <div\n        class=\"chart-item\"\n        v-for=\"(item, index) in visibleMetrics\"\n        :key=\"item.key\"\n        :title=\"item.key\"\n      >\n        <div class=\"metric-card-top\">\n          <div>\n            <div class=\"metric-group-label\">{{ item.groupLabel }}</div>\n            <div class=\"metric-latest\">\n              <span class=\"metric-latest-label\">Latest</span>\n              <strong>{{ formatLatest(item) }}</strong>\n            </div>\n          </div>\n          <div\n            v-if=\"item.goal\"\n            class=\"metric-goal\"\n            :class=\"'goal-' + item.goalKind\"\n          >\n            {{ item.goal }}\n          </div>\n        </div>\n\n        <div\n          class=\"zoom\"\n          @click=\"zoom(colors[index % colors.length], metricData[item.key], item.label)\"\n          aria-label=\"Open metric chart\"\n        ></div>\n\n        <lineChart\n          :color=\"colors[index % colors.length]\"\n          :data=\"metricData[item.key]\"\n          :chartName=\"item.label\"\n          :smallSize=\"true\"\n        ></lineChart>\n\n        <div class=\"metric-raw-name\">{{ item.key }}</div>\n      </div>\n\n      <div class=\"metric-empty\" v-if=\"visibleMetrics.length === 0\">\n        No metrics are available in this group.\n      </div>\n    </div>\n\n    <div class=\"dialog-box\" v-if=\"showDialog\">\n      <div class=\"dialog-content gradient-border\">\n        <div class=\"close\" @click=\"close\"></div>\n        <lineChart\n          :color=\"dialogColor\"\n          :data=\"dialogData\"\n          :chartName=\"dialogName\"\n          :smallSize=\"false\"\n        ></lineChart>\n      </div>\n    </div>\n  </div>\n</template>\n\n<script setup>\nimport { computed, defineProps, ref, watch } from \"vue\";\nimport lineChart from \"../components/lineChartOne.vue\";\n\nconst props = defineProps({\n  metricData: Object,\n});\n\nconst metricData = computed(() => props.metricData || {});\nconst colors = [\"red\", \"blue\", \"orange\", \"green\", \"purple\", \"teal\", \"brown\", \"navy\"];\nconst activeTab = ref(\"key\");\nconst showDialog = ref(false);\nconst dialogColor = ref(\"\");\nconst dialogData = ref(null);\nconst dialogName = ref(\"\");\n\nconst preferredHeadlineCandidates = [\n  [\"IC\"],\n  [\"ICIR\"],\n  [\"Rank IC\"],\n  [\"Rank ICIR\"],\n  [\n    \"1day.excess_return_with_cost.annualized_return\",\n    \"1day.excess_return_without_cost.annualized_return\",\n  ],\n  [\n    \"1day.excess_return_with_cost.information_ratio\",\n    \"1day.excess_return_without_cost.information_ratio\",\n  ],\n  [\n    \"1day.excess_return_with_cost.max_drawdown\",\n    \"1day.excess_return_without_cost.max_drawdown\",\n  ],\n];\n\nconst classifyMetric = (key) => {\n  const lower = String(key || \"\").toLowerCase();\n\n  if (\n    lower === \"ic\" ||\n    lower === \"icir\" ||\n    lower === \"rank ic\" ||\n    lower === \"rank icir\" ||\n    lower.includes(\"rank_ic\")\n  ) {\n    return \"prediction\";\n  }\n\n  if (\n    lower.startsWith(\"1day.\") ||\n    lower.includes(\"excess_return\") ||\n    lower.includes(\"annualized_return\") ||\n    lower.includes(\"information_ratio\") ||\n    lower.includes(\"max_drawdown\") ||\n    lower.includes(\"turnover\") ||\n    lower.includes(\"sharpe\")\n  ) {\n    return \"portfolio\";\n  }\n\n  if (\n    lower.startsWith(\"l2.\") ||\n    lower.includes(\"loss\") ||\n    lower.includes(\"train.\") ||\n    lower.includes(\"valid.\") ||\n    lower.includes(\"validation\")\n  ) {\n    return \"training\";\n  }\n\n  return \"other\";\n};\n\nconst groupLabel = (group) => {\n  if (group === \"prediction\") return \"Prediction\";\n  if (group === \"portfolio\") return \"Portfolio\";\n  if (group === \"training\") return \"Training\";\n  return \"Other\";\n};\n\nconst metricLabel = (key) => {\n  const exact = {\n    IC: \"IC\",\n    ICIR: \"ICIR\",\n    \"Rank IC\": \"Rank IC\",\n    \"Rank ICIR\": \"Rank ICIR\",\n    \"1day.excess_return_with_cost.annualized_return\": \"Net Ann. Excess Return\",\n    \"1day.excess_return_with_cost.information_ratio\": \"Net Information Ratio\",\n    \"1day.excess_return_with_cost.max_drawdown\": \"Net Max Drawdown\",\n    \"1day.excess_return_without_cost.annualized_return\": \"Gross Ann. Excess Return\",\n    \"1day.excess_return_without_cost.information_ratio\": \"Gross Information Ratio\",\n    \"1day.excess_return_without_cost.max_drawdown\": \"Gross Max Drawdown\",\n    \"l2.train\": \"Train L2 Loss\",\n    \"l2.valid\": \"Validation L2 Loss\",\n  };\n\n  if (exact[key]) return exact[key];\n\n  let label = String(key || \"\")\n    .replace(/^1day\\./, \"\")\n    .replace(/excess_return_with_cost/gi, \"net excess return\")\n    .replace(/excess_return_without_cost/gi, \"gross excess return\")\n    .replace(/annualized_return/gi, \"annualized return\")\n    .replace(/information_ratio/gi, \"information ratio\")\n    .replace(/max_drawdown/gi, \"max drawdown\")\n    .replace(/[._]+/g, \" \")\n    .replace(/\\s+/g, \" \")\n    .trim();\n\n  if (!label) return key;\n  return label.replace(/\\b\\w/g, (char) => char.toUpperCase());\n};\n\nconst metricGoal = (key) => {\n  const lower = String(key || \"\").toLowerCase();\n\n  if (lower.includes(\"max_drawdown\")) {\n    return { text: \"0↑ Closer to zero\", kind: \"zero\" };\n  }\n\n  if (\n    lower.startsWith(\"l2.\") ||\n    lower.includes(\"loss\") ||\n    lower.includes(\"turnover\")\n  ) {\n    return { text: \"↓ Lower\", kind: \"lower\" };\n  }\n\n  if (\n    lower === \"ic\" ||\n    lower === \"icir\" ||\n    lower === \"rank ic\" ||\n    lower === \"rank icir\" ||\n    lower.includes(\"annualized_return\") ||\n    lower.includes(\"information_ratio\") ||\n    lower.includes(\"sharpe\")\n  ) {\n    return { text: \"↑ Higher\", kind: \"higher\" };\n  }\n\n  return { text: \"\", kind: \"neutral\" };\n};\n\nconst metricSortRank = (key) => {\n  const headlineFlat = preferredHeadlineCandidates.flat();\n  const headlineIndex = headlineFlat.indexOf(key);\n  if (headlineIndex >= 0) return headlineIndex;\n\n  const group = classifyMetric(key);\n  if (group === \"prediction\") return 100;\n  if (group === \"portfolio\") return 200;\n  if (group === \"training\") return 300;\n  return 400;\n};\n\nconst allMetrics = computed(() =>\n  Object.keys(metricData.value)\n    .map((key) => {\n      const group = classifyMetric(key);\n      const goal = metricGoal(key);\n      return {\n        key,\n        label: metricLabel(key),\n        group,\n        groupLabel: groupLabel(group),\n        goal: goal.text,\n        goalKind: goal.kind,\n      };\n    })\n    .sort((a, b) => {\n      const rankDiff = metricSortRank(a.key) - metricSortRank(b.key);\n      return rankDiff || a.label.localeCompare(b.label);\n    })\n);\n\nconst headlineMetrics = computed(() => {\n  const byKey = new Map(allMetrics.value.map((item) => [item.key, item]));\n  const selected = [];\n\n  preferredHeadlineCandidates.forEach((candidates) => {\n    const found = candidates.find((key) => byKey.has(key));\n    if (found) selected.push(byKey.get(found));\n  });\n\n  return selected;\n});\n\nconst metricsByGroup = (group) =>\n  allMetrics.value.filter((item) => item.group === group);\n\nconst tabDefinitions = computed(() => [\n  { key: \"key\", label: \"Key metrics\", count: headlineMetrics.value.length },\n  {\n    key: \"prediction\",\n    label: \"Prediction\",\n    count: metricsByGroup(\"prediction\").length,\n  },\n  {\n    key: \"portfolio\",\n    label: \"Portfolio\",\n    count: metricsByGroup(\"portfolio\").length,\n  },\n  {\n    key: \"training\",\n    label: \"Training\",\n    count: metricsByGroup(\"training\").length,\n  },\n  { key: \"other\", label: \"Other\", count: metricsByGroup(\"other\").length },\n  { key: \"all\", label: \"All\", count: allMetrics.value.length },\n]);\n\nconst availableTabs = computed(() =>\n  tabDefinitions.value.filter(\n    (tab) => tab.key === \"all\" || tab.count > 0\n  )\n);\n\nconst visibleMetrics = computed(() => {\n  if (activeTab.value === \"key\") return headlineMetrics.value;\n  if (activeTab.value === \"all\") return allMetrics.value;\n  return metricsByGroup(activeTab.value);\n});\n\nconst latestNumericValue = (item) => {\n  const data = metricData.value[item.key];\n  if (!Array.isArray(data)) return null;\n\n  for (let index = data.length - 1; index >= 0; index -= 1) {\n    const value = data[index]?.value;\n    if (typeof value === \"number\" && Number.isFinite(value)) return value;\n  }\n  return null;\n};\n\nconst formatLatest = (item) => {\n  const value = latestNumericValue(item);\n  if (value == null) return \"—\";\n\n  const lower = item.key.toLowerCase();\n  if (\n    lower.includes(\"annualized_return\") ||\n    lower.includes(\"max_drawdown\")\n  ) {\n    return (value * 100).toFixed(2) + \"%\";\n  }\n\n  if (Math.abs(value) >= 100) return value.toFixed(1);\n  if (Math.abs(value) >= 1) return value.toFixed(3);\n  return value.toFixed(4);\n};\n\nconst zoom = (color, data, name) => {\n  dialogColor.value = color;\n  dialogData.value = data;\n  dialogName.value = name;\n  showDialog.value = true;\n};\n\nconst close = () => {\n  showDialog.value = false;\n  dialogColor.value = \"\";\n  dialogData.value = null;\n  dialogName.value = \"\";\n};\n\nwatch(\n  availableTabs,\n  (tabs) => {\n    if (!tabs.some((tab) => tab.key === activeTab.value)) {\n      activeTab.value = tabs.some((tab) => tab.key === \"key\") ? \"key\" : \"all\";\n    }\n  },\n  { immediate: true }\n);\n</script>\n\n<style scoped lang=\"scss\">\n.metric-panel {\n  width: 100%;\n}\n\n.metric-toolbar {\n  display: flex;\n  align-items: flex-start;\n  justify-content: space-between;\n  gap: 1em;\n  margin: 0 0 1.15em;\n}\n\n.metric-tabs {\n  display: flex;\n  flex-wrap: wrap;\n  gap: 0.55em;\n}\n\n.metric-tab {\n  display: inline-flex;\n  align-items: center;\n  gap: 0.5em;\n  border: 1px solid #d8deec;\n  border-radius: 999px;\n  background: var(--bg-white);\n  color: var(--text-color);\n  padding: 0.5em 0.85em;\n  font-size: 0.85em;\n  font-weight: 700;\n  cursor: pointer;\n  transition: 0.18s ease;\n}\n\n.metric-tab:hover {\n  border-color: #8d79ff;\n  transform: translateY(-1px);\n}\n\n.metric-tab.active {\n  border-color: #7657ff;\n  background: #f4f1ff;\n  color: #5a42d6;\n}\n\n.metric-tab-count {\n  min-width: 1.6em;\n  padding: 0.08em 0.42em;\n  border-radius: 999px;\n  background: rgba(105, 75, 255, 0.1);\n  text-align: center;\n  font-size: 0.86em;\n}\n\n.metric-help {\n  display: flex;\n  flex-wrap: wrap;\n  justify-content: flex-end;\n  gap: 0.4em 0.8em;\n  color: #7a8296;\n  font-size: 0.75em;\n  line-height: 1.5;\n}\n\n.chart-box {\n  display: grid;\n  grid-template-columns: repeat(auto-fit, minmax(290px, 1fr));\n  gap: 1.25em;\n  margin-bottom: 1.8em;\n}\n\n.chart-item {\n  min-width: 0;\n  border-radius: 22px;\n  position: relative;\n  overflow: hidden;\n  background-color: var(--bg-white);\n  box-shadow: 1px 1px 2px 0 rgba(255, 255, 255, 0.3) inset,\n    -1px -1px 2px 0 rgba(221, 221, 221, 0.5) inset,\n    -8px 8px 18px 0 rgba(221, 221, 221, 0.16),\n    8px -8px 18px 0 rgba(221, 221, 221, 0.16),\n    8px 8px 22px 0 rgba(221, 221, 221, 0.55);\n}\n\n.metric-card-top {\n  display: flex;\n  align-items: flex-start;\n  justify-content: space-between;\n  gap: 0.75em;\n  min-height: 2.7em;\n  padding: 0.8em 3.1em 0.15em 1em;\n}\n\n.metric-group-label {\n  margin-bottom: 0.15em;\n  color: #8a92a7;\n  font-size: 0.68em;\n  font-weight: 800;\n  letter-spacing: 0.07em;\n  text-transform: uppercase;\n}\n\n.metric-latest {\n  display: flex;\n  align-items: baseline;\n  gap: 0.42em;\n  color: var(--text-color);\n}\n\n.metric-latest-label {\n  color: #858da2;\n  font-size: 0.72em;\n}\n\n.metric-latest strong {\n  font-size: 0.95em;\n}\n\n.metric-goal {\n  white-space: nowrap;\n  border-radius: 999px;\n  padding: 0.32em 0.58em;\n  font-size: 0.68em;\n  font-weight: 800;\n}\n\n.goal-higher {\n  background: #eef8f1;\n  color: #39774b;\n}\n\n.goal-lower {\n  background: #fff6e9;\n  color: #9b6416;\n}\n\n.goal-zero {\n  background: #f1f4ff;\n  color: #4d62a5;\n}\n\n.zoom {\n  position: absolute;\n  right: 1em;\n  top: 0.9em;\n  width: 1.05em;\n  height: 1.05em;\n  background: url(@/assets/playground-images/zoom.svg) no-repeat;\n  background-size: contain;\n  cursor: pointer;\n  z-index: 2;\n}\n\n.zoom:hover {\n  opacity: 0.55;\n}\n\n.metric-raw-name {\n  min-height: 2.6em;\n  margin: -0.2em 1em 0.9em;\n  padding-top: 0.65em;\n  border-top: 1px solid #edf0f6;\n  color: #7e879b;\n  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;\n  font-size: 0.64em;\n  line-height: 1.35;\n  overflow-wrap: anywhere;\n}\n\n.metric-empty {\n  grid-column: 1 / -1;\n  padding: 2em;\n  border: 1px dashed #d7ddea;\n  border-radius: 16px;\n  color: #7b8498;\n  text-align: center;\n}\n\n.dialog-box {\n  width: 100vw;\n  height: 100vh;\n  position: fixed;\n  left: 0;\n  top: 0;\n  background: rgba(255, 255, 255, 0.29);\n  backdrop-filter: blur(4.6px);\n  z-index: 999999;\n  display: flex;\n  align-items: center;\n  justify-content: center;\n}\n\n.dialog-content {\n  width: min(900px, 82vw);\n  height: 498px;\n  background-color: #fff;\n  border-radius: 18px;\n  --border-radius: 20px;\n  --border-width: 2px;\n  padding-bottom: 2em;\n  margin-top: -4em;\n  position: relative;\n}\n\n.close {\n  position: absolute;\n  right: 1.35em;\n  top: 0.9em;\n  width: 1.125em;\n  height: 1.125em;\n  background: url(@/assets/playground-images/close.svg) no-repeat;\n  background-size: contain;\n  cursor: pointer;\n  z-index: 2;\n}\n\n.close:hover {\n  opacity: 0.5;\n}\n\n@media (max-width: 900px) {\n  .metric-toolbar {\n    flex-direction: column;\n  }\n\n  .metric-help {\n    justify-content: flex-start;\n  }\n\n  .chart-box {\n    grid-template-columns: 1fr;\n  }\n\n  .dialog-content {\n    width: 94vw;\n  }\n}\n</style>\n";
if (!fs.existsSync(metricBoxP44)) {
  console.error("[patch-frontend] FAILED: P44 chartBox.vue missing.");
  process.exit(1);
}
fs.writeFileSync(metricBoxP44, metricBoxNewP44);
console.log("[patch-frontend] P44 readable grouped metric UI applied to chartBox.vue");

// ------------------------- P45: metric definitions + formulas -------------------------
// Keep the P44 cards compact. Definitions/formulas live behind a per-card info button
// and a global Metric Guide so users can understand Qlib semantics without clutter.
const metricGuideP45 = "/src/web/src/components/chartBox.vue";
let metricGuideS45 = fs.readFileSync(metricGuideP45, "utf8");

const toolbarP45Old = `      <div class="metric-help">
        <span>↑ higher is better</span>
        <span>↓ lower is better</span>
        <span>0↑ closer to zero is better</span>
      </div>`;
const toolbarP45New = `      <div class="metric-toolbar-side">
        <div class="metric-help">
          <span>↑ higher is better</span>
          <span>↓ lower is better</span>
          <span>0↑ closer to zero is better</span>
        </div>
        <button
          type="button"
          class="metric-guide-btn"
          @click="openMetricGuide()"
        >
          ⓘ Metric guide
        </button>
      </div>`;
if (!metricGuideS45.includes(toolbarP45Old)) {
  console.error("[patch-frontend] FAILED: P45 metric toolbar anchor drifted.");
  process.exit(1);
}
metricGuideS45 = metricGuideS45.replace(toolbarP45Old, toolbarP45New);

const footerP45Old = `        <div class="metric-raw-name">{{ item.key }}</div>`;
const footerP45New = `        <div class="metric-card-footer">
          <div class="metric-raw-name">{{ item.key }}</div>
          <button
            type="button"
            class="metric-info-btn"
            title="Definition and formula"
            @click="openMetricGuide(item)"
          >
            ⓘ
          </button>
        </div>`;
if (!metricGuideS45.includes(footerP45Old)) {
  console.error("[patch-frontend] FAILED: P45 metric card footer anchor drifted.");
  process.exit(1);
}
metricGuideS45 = metricGuideS45.replace(footerP45Old, footerP45New);

const dialogP45Anchor = `    <div class="dialog-box" v-if="showDialog">`;
const guideP45 = `    <div
      class="metric-guide-overlay"
      v-if="showMetricGuide"
      @click.self="closeMetricGuide"
    >
      <div class="metric-guide-card">
        <div class="metric-guide-head">
          <div>
            <div class="metric-guide-kicker">QLIB METRIC REFERENCE</div>
            <h2>{{ selectedGuideMetric ? selectedGuideMetric.label : "Metric Guide" }}</h2>
            <p v-if="selectedGuideMetric" class="metric-guide-raw">
              {{ selectedGuideMetric.key }}
            </p>
            <p v-else>
              Definitions and formulas for the metrics currently present in this experiment.
              Qlib's daily risk metrics use its arithmetic accumulation convention.
            </p>
          </div>
          <button
            type="button"
            class="metric-guide-close"
            aria-label="Close metric guide"
            @click="closeMetricGuide"
          >
            ×
          </button>
        </div>

        <template v-if="selectedGuideMetric">
          <div class="metric-guide-detail">
            <div class="metric-guide-badges">
              <span class="metric-guide-group">{{ selectedGuideMetric.groupLabel }}</span>
              <span
                v-if="selectedGuideMetric.goal"
                class="metric-goal"
                :class="'goal-' + selectedGuideMetric.goalKind"
              >
                {{ selectedGuideMetric.goal }}
              </span>
            </div>

            <section class="metric-guide-section">
              <h3>Definition</h3>
              <p>{{ selectedGuideMetric.guide.definition }}</p>
            </section>

            <section class="metric-guide-section">
              <h3>Formula</h3>
              <code class="metric-formula">{{ selectedGuideMetric.guide.formula }}</code>
            </section>

            <section class="metric-guide-section">
              <h3>How to read it</h3>
              <p>{{ selectedGuideMetric.guide.interpretation }}</p>
            </section>

            <section
              class="metric-guide-section metric-guide-note"
              v-if="selectedGuideMetric.guide.note"
            >
              <h3>Qlib note</h3>
              <p>{{ selectedGuideMetric.guide.note }}</p>
            </section>

            <button
              type="button"
              class="metric-guide-back"
              @click="selectedGuideMetric = null"
            >
              ← All metrics
            </button>
          </div>
        </template>

        <div v-else class="metric-guide-list">
          <button
            v-for="item in guideMetrics"
            :key="item.key"
            type="button"
            class="metric-guide-list-item"
            @click="selectedGuideMetric = item"
          >
            <div class="metric-guide-list-top">
              <div>
                <span class="metric-guide-list-group">{{ item.groupLabel }}</span>
                <strong>{{ item.label }}</strong>
              </div>
              <span
                v-if="item.goal"
                class="metric-goal"
                :class="'goal-' + item.goalKind"
              >
                {{ item.goal }}
              </span>
            </div>
            <p>{{ item.guide.definition }}</p>
            <code>{{ item.guide.formula }}</code>
          </button>
        </div>

        <div class="metric-guide-foot">
          <strong>Notation:</strong>
          ŷ = model score/prediction; y = realized label/return; i = instrument;
          t = date; A = annualization factor. For Qlib daily risk analysis, A = 238.
        </div>
      </div>
    </div>

`;
if (!metricGuideS45.includes(dialogP45Anchor)) {
  console.error("[patch-frontend] FAILED: P45 dialog anchor drifted.");
  process.exit(1);
}
metricGuideS45 = metricGuideS45.replace(dialogP45Anchor, guideP45 + dialogP45Anchor);

const stateP45Anchor = `const dialogName = ref("");`;
const stateP45New = `const dialogName = ref("");
const showMetricGuide = ref(false);
const selectedGuideMetric = ref(null);`;
if (!metricGuideS45.includes(stateP45Anchor)) {
  console.error("[patch-frontend] FAILED: P45 metric guide state anchor drifted.");
  process.exit(1);
}
metricGuideS45 = metricGuideS45.replace(stateP45Anchor, stateP45New);

const metricGoalP45Anchor = `const metricSortRank = (key) => {`;
const metricGuideLogicP45 = `const metricGuideInfo = (key) => {
  const raw = String(key || "");
  const lower = raw.toLowerCase();
  const isWithCost = lower.includes("with_cost");
  const isWithoutCost = lower.includes("without_cost");
  const returnLabel = isWithCost
    ? "net excess return after transaction costs"
    : isWithoutCost
      ? "gross excess return before transaction costs"
      : "return series";

  if (raw === "IC") {
    return {
      definition:
        "Mean daily cross-sectional Pearson correlation between the model score and the realized label.",
      formula:
        "IC_t = Corr_i(ŷ_{i,t}, y_{i,t});   IC = mean_t(IC_t)",
      interpretation:
        "Measures linear predictive alignment across instruments. Positive is desirable; larger positive values imply stronger signal.",
      note:
        "Qlib computes Pearson correlation separately for each date, then reports the mean across dates.",
    };
  }

  if (raw === "ICIR") {
    return {
      definition:
        "Stability of daily IC over time: average daily IC divided by the standard deviation of daily IC.",
      formula:
        "ICIR = mean_t(IC_t) / std_t(IC_t)",
      interpretation:
        "A higher positive ICIR means the predictive relationship is not only positive on average but also more consistent through time.",
      note:
        "Qlib's SigAnaRecord uses mean(IC_t) / std(IC_t) directly; it is not annualized.",
    };
  }

  if (raw === "Rank IC") {
    return {
      definition:
        "Mean daily cross-sectional Spearman rank correlation between model scores and realized labels.",
      formula:
        "RIC_t = Corr_i(rank(ŷ_{i,t}), rank(y_{i,t}));   Rank IC = mean_t(RIC_t)",
      interpretation:
        "Measures whether the model orders instruments correctly, even when the score-to-return relationship is nonlinear.",
      note:
        "Qlib implements this as a per-date Spearman correlation and then averages across dates.",
    };
  }

  if (raw === "Rank ICIR") {
    return {
      definition:
        "Stability of daily Rank IC over time.",
      formula:
        "Rank ICIR = mean_t(RIC_t) / std_t(RIC_t)",
      interpretation:
        "Higher positive values indicate that the model's cross-sectional ranking quality is more stable across dates.",
      note:
        "Like ICIR, Qlib reports a non-annualized mean-to-standard-deviation ratio.",
    };
  }

  if (lower.includes("annualized_return")) {
    return {
      definition:
        "Annualized " + returnLabel + ".",
      formula:
        "Annualized Return = A × mean_t(r_t);   for Qlib daily analysis, A = 238",
      interpretation:
        isWithCost
          ? "This is the most direct economic metric: positive and higher is better after trading costs."
          : "Shows gross economic performance before trading costs. Compare it with the with-cost version to understand cost drag.",
      note:
        "Qlib's default risk_analysis(mode='sum') uses arithmetic accumulation rather than compounded CAGR.",
    };
  }

  if (lower.includes("information_ratio")) {
    return {
      definition:
        "Risk-adjusted " + returnLabel + ": average excess return scaled by its volatility.",
      formula:
        "Information Ratio = mean_t(r_t) / std_t(r_t) × √A;   A = 238 for Qlib daily analysis",
      interpretation:
        "Higher positive values mean the strategy earns more excess return per unit of variability.",
      note:
        "For keys under excess_return_with_cost, r_t includes transaction-cost drag; without_cost excludes it.",
    };
  }

  if (lower.includes("max_drawdown")) {
    return {
      definition:
        "Worst peak-to-trough decline of the cumulative " + returnLabel + " curve.",
      formula:
        "C_t = Σ_{u≤t} r_u;   MDD = min_t(C_t − max_{s≤t} C_s)",
      interpretation:
        "Qlib reports this as a negative number in the default arithmetic mode. A value closer to 0 means a smaller drawdown.",
      note:
        "This follows Qlib's default sum-mode cumulative return curve, not the geometric wealth-curve drawdown formula.",
    };
  }

  if (
    lower.endsWith(".mean") ||
    lower === "mean" ||
    lower.includes(".mean.")
  ) {
    return {
      definition:
        "Average value of the underlying daily " + returnLabel + ".",
      formula:
        "mean = (1/T) × Σ_t r_t",
      interpretation:
        "Useful as the unannualized daily return level; interpret together with volatility and annualized return.",
      note: "",
    };
  }

  if (
    lower.endsWith(".std") ||
    lower === "std" ||
    lower.includes(".std.")
  ) {
    return {
      definition:
        "Sample standard deviation of the underlying daily " + returnLabel + ".",
      formula:
        "std = √[ Σ_t(r_t − mean(r))² / (T − 1) ]",
      interpretation:
        "Measures variability/risk of the daily series. Lower is generally preferable for the same level of return.",
      note: "",
    };
  }

  if (raw === "l2.train" || raw === "l2.valid") {
    const split = raw === "l2.train" ? "training" : "validation";
    return {
      definition:
        "L2 / mean-squared prediction loss on the " + split + " sample.",
      formula:
        "L2 = (1/N) × Σ_j (ŷ_j − y_j)²",
      interpretation:
        raw === "l2.train"
          ? "Lower means a better fit to the training sample, but very low training loss alone can indicate overfitting."
          : "Lower validation loss usually indicates better generalization. Rising validation loss while train loss falls is an overfitting warning.",
      note:
        "This is a model-fit metric, not a trading metric; prioritize IC and after-cost portfolio metrics for research decisions.",
    };
  }

  if (lower.includes("turnover")) {
    return {
      definition:
        "How much of the portfolio is replaced/rebalanced over time.",
      formula:
        "Typical form: Turnover_t ≈ ½ × Σ_i |w_{i,t} − w^{drift}_{i,t−1}|",
      interpretation:
        "Lower turnover usually means lower transaction-cost pressure, but the exact desirable level depends on signal horizon and strategy.",
      note:
        "Exact turnover aggregation can depend on the Qlib strategy/recorder that produced this raw key.",
    };
  }

  if (lower.includes("sharpe")) {
    return {
      definition:
        "Annualized average return divided by return volatility.",
      formula:
        "Sharpe ≈ mean_t(r_t) / std_t(r_t) × √A",
      interpretation:
        "Higher positive values indicate better return per unit of volatility.",
      note:
        "Whether r_t is total return or excess return depends on the raw metric key.",
    };
  }

  return {
    definition:
      "Raw metric emitted by the Qlib experiment/backtest. Its exact meaning is recorder-specific.",
    formula:
      "Recorder-specific — inspect the raw metric key or Qlib recorder that produced it.",
    interpretation:
      "Use this as an advanced diagnostic unless it is one of the documented headline metrics.",
    note:
      "The UI preserves every raw metric from the experiment, so future Qlib metrics can appear here without being dropped.",
  };
};

`;
if (!metricGuideS45.includes(metricGoalP45Anchor)) {
  console.error("[patch-frontend] FAILED: P45 metric guide logic anchor drifted.");
  process.exit(1);
}
metricGuideS45 = metricGuideS45.replace(
  metricGoalP45Anchor,
  metricGuideLogicP45 + metricGoalP45Anchor
);

const metricMapP45Old = `        goal: goal.text,
        goalKind: goal.kind,
      };`;
const metricMapP45New = `        goal: goal.text,
        goalKind: goal.kind,
        guide: metricGuideInfo(key),
      };`;
if (!metricGuideS45.includes(metricMapP45Old)) {
  console.error("[patch-frontend] FAILED: P45 allMetrics mapping anchor drifted.");
  process.exit(1);
}
metricGuideS45 = metricGuideS45.replace(metricMapP45Old, metricMapP45New);

const visibleP45Anchor = `const latestNumericValue = (item) => {`;
const guideComputedP45 = `const guideMetrics = computed(() => allMetrics.value);

`;
if (!metricGuideS45.includes(visibleP45Anchor)) {
  console.error("[patch-frontend] FAILED: P45 guideMetrics anchor drifted.");
  process.exit(1);
}
metricGuideS45 = metricGuideS45.replace(
  visibleP45Anchor,
  guideComputedP45 + visibleP45Anchor
);

const closeP45Anchor = `const close = () => {`;
const guideMethodsP45 = `const openMetricGuide = (item = null) => {
  selectedGuideMetric.value = item;
  showMetricGuide.value = true;
};

const closeMetricGuide = () => {
  showMetricGuide.value = false;
  selectedGuideMetric.value = null;
};

`;
if (!metricGuideS45.includes(closeP45Anchor)) {
  console.error("[patch-frontend] FAILED: P45 guide methods anchor drifted.");
  process.exit(1);
}
metricGuideS45 = metricGuideS45.replace(
  closeP45Anchor,
  guideMethodsP45 + closeP45Anchor
);

const styleP45Anchor = `.metric-help {
  display: flex;`;
const styleP45New = `.metric-toolbar-side {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 0.65em 0.85em;
}

.metric-help {
  display: flex;`;
if (!metricGuideS45.includes(styleP45Anchor)) {
  console.error("[patch-frontend] FAILED: P45 metric-help style anchor drifted.");
  process.exit(1);
}
metricGuideS45 = metricGuideS45.replace(styleP45Anchor, styleP45New);

const rawStyleP45Old = `.metric-raw-name {
  min-height: 2.6em;
  margin: -0.2em 1em 0.9em;
  padding-top: 0.65em;
  border-top: 1px solid #edf0f6;
  color: #7e879b;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.64em;
  line-height: 1.35;
  overflow-wrap: anywhere;
}`;
const rawStyleP45New = `.metric-card-footer {
  display: flex;
  align-items: flex-start;
  gap: 0.6em;
  margin: -0.2em 1em 0.9em;
  padding-top: 0.65em;
  border-top: 1px solid #edf0f6;
}

.metric-raw-name {
  flex: 1;
  min-width: 0;
  color: #7e879b;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.64em;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.metric-info-btn,
.metric-guide-btn {
  border: 1px solid #d9deeb;
  background: var(--bg-white);
  color: #5e6780;
  cursor: pointer;
  transition: 0.16s ease;
}

.metric-info-btn {
  width: 1.9em;
  height: 1.9em;
  flex: 0 0 1.9em;
  border-radius: 50%;
  padding: 0;
  font-size: 0.78em;
  font-weight: 800;
}

.metric-guide-btn {
  border-radius: 999px;
  padding: 0.48em 0.8em;
  font-size: 0.76em;
  font-weight: 800;
  white-space: nowrap;
}

.metric-info-btn:hover,
.metric-guide-btn:hover {
  border-color: #846aff;
  color: #5a42d6;
  background: #f6f3ff;
}

.metric-guide-overlay {
  width: 100vw;
  height: 100vh;
  position: fixed;
  inset: 0;
  z-index: 1000000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 2em;
  box-sizing: border-box;
  background: rgba(33, 38, 52, 0.28);
  backdrop-filter: blur(5px);
}

.metric-guide-card {
  width: min(980px, 94vw);
  max-height: 86vh;
  overflow: auto;
  box-sizing: border-box;
  border: 1px solid #e1e5ef;
  border-radius: 20px;
  padding: 1.35em 1.45em 1.1em;
  background: #fff;
  box-shadow: 0 24px 70px rgba(39, 45, 67, 0.22);
}

.metric-guide-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1em;
  padding-bottom: 1em;
  border-bottom: 1px solid #edf0f6;
}

.metric-guide-head h2 {
  margin: 0.12em 0 0.18em;
  font-size: 1.45em;
  color: #252b3b;
}

.metric-guide-head p {
  margin: 0;
  max-width: 760px;
  color: #6f7890;
  line-height: 1.5;
  font-size: 0.9em;
}

.metric-guide-kicker,
.metric-guide-list-group {
  color: #8a72e7;
  font-size: 0.68em;
  font-weight: 900;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.metric-guide-raw {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  overflow-wrap: anywhere;
}

.metric-guide-close {
  width: 2.15em;
  height: 2.15em;
  flex: 0 0 2.15em;
  border: 0;
  border-radius: 50%;
  background: #f2f4f8;
  color: #616a80;
  font-size: 1.15em;
  cursor: pointer;
}

.metric-guide-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0.9em;
  padding: 1.1em 0;
}

.metric-guide-list-item {
  display: block;
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #e4e8f1;
  border-radius: 14px;
  padding: 0.9em 1em;
  background: #fff;
  color: #31384a;
  text-align: left;
  cursor: pointer;
}

.metric-guide-list-item:hover {
  border-color: #9b87ef;
  background: #fbfaff;
}

.metric-guide-list-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.7em;
}

.metric-guide-list-top strong {
  display: block;
  margin-top: 0.16em;
  font-size: 0.96em;
}

.metric-guide-list-item p {
  margin: 0.6em 0;
  color: #606a80;
  font-size: 0.82em;
  line-height: 1.48;
}

.metric-guide-list-item code,
.metric-formula {
  display: block;
  white-space: normal;
  overflow-wrap: anywhere;
  border-radius: 9px;
  padding: 0.55em 0.65em;
  background: #f6f7fa;
  color: #414a60;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 0.76em;
  line-height: 1.45;
}

.metric-guide-detail {
  padding: 1.05em 0 0.25em;
}

.metric-guide-badges {
  display: flex;
  gap: 0.55em;
  align-items: center;
  margin-bottom: 0.8em;
}

.metric-guide-group {
  border-radius: 999px;
  padding: 0.32em 0.58em;
  background: #f2f4f8;
  color: #687189;
  font-size: 0.7em;
  font-weight: 800;
}

.metric-guide-section {
  margin: 0.95em 0;
}

.metric-guide-section h3 {
  margin: 0 0 0.35em;
  color: #32394b;
  font-size: 0.84em;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.metric-guide-section p {
  margin: 0;
  color: #5b657b;
  line-height: 1.62;
  font-size: 0.92em;
}

.metric-guide-note {
  border-left: 3px solid #b7a8f3;
  padding-left: 0.9em;
}

.metric-guide-back {
  margin-top: 0.4em;
  border: 0;
  border-radius: 999px;
  padding: 0.55em 0.9em;
  background: #f2efff;
  color: #5a42d6;
  font-weight: 800;
  cursor: pointer;
}

.metric-guide-foot {
  margin-top: 0.8em;
  padding-top: 0.8em;
  border-top: 1px solid #edf0f6;
  color: #858da0;
  font-size: 0.72em;
  line-height: 1.55;
}`;
if (!metricGuideS45.includes(rawStyleP45Old)) {
  console.error("[patch-frontend] FAILED: P45 raw-name style anchor drifted.");
  process.exit(1);
}
metricGuideS45 = metricGuideS45.replace(rawStyleP45Old, rawStyleP45New);

const mobileP45Old = `  .metric-help {
    justify-content: flex-start;
  }

  .chart-box {`;
const mobileP45New = `  .metric-toolbar-side,
  .metric-help {
    justify-content: flex-start;
  }

  .metric-guide-list {
    grid-template-columns: 1fr;
  }

  .metric-guide-overlay {
    padding: 0.7em;
  }

  .metric-guide-card {
    width: 100%;
    max-height: 92vh;
    padding: 1em;
  }

  .chart-box {`;
if (!metricGuideS45.includes(mobileP45Old)) {
  console.error("[patch-frontend] FAILED: P45 mobile style anchor drifted.");
  process.exit(1);
}
metricGuideS45 = metricGuideS45.replace(mobileP45Old, mobileP45New);

fs.writeFileSync(metricGuideP45, metricGuideS45);
console.log("[patch-frontend] P45 metric definitions/formulas guide applied to chartBox.vue");


// ------------------------- P46: execution-failure aware Result UI -------------------------
// Runtime/backtest failures are not research failures. Show the actual reason,
// classify the status, and keep older traces readable from observations/exception.
const resultP46 = "/src/web/src/views/ResultPage.vue";
let resultS46 = fs.readFileSync(resultP46, "utf8");
const helperP46Anchor = "const updateData = () => {";
const helperP46New = "const isExecutionFailureFeedback = (feedback) => {\n  if (!feedback || typeof feedback !== \"object\") return false;\n  const text = [feedback.reason, feedback.observations, feedback.exception]\n    .filter(Boolean)\n    .map((value) => String(value))\n    .join(\"\\n\")\n    .toLowerCase();\n\n  return (\n    text.includes(\"execution failed:\") ||\n    text.includes(\"failed to run this experiment\") ||\n    (text.includes(\"failed to run \") && text.includes(\" model, because \")) ||\n    text.includes(\"qrun_exit_code=\") ||\n    text.includes(\"no result file found\") ||\n    text.includes(\"process was killed\") ||\n    text.includes(\"\\nkilled\") ||\n    text.includes(\"qrun timed out\") ||\n    text.includes(\"running time exceeds\")\n  );\n};\n\nconst getFeedbackDisplayReason = (feedback) => {\n  if (!feedback || typeof feedback !== \"object\") return \"\";\n  if (feedback.reason) return String(feedback.reason);\n\n  if (isExecutionFailureFeedback(feedback)) {\n    const raw = [feedback.observations, feedback.exception]\n      .filter(Boolean)\n      .map((value) => String(value))\n      .join(\"\\n\");\n    const lower = raw.toLowerCase();\n    if (\n      lower.includes(\"qrun_exit_code=137\") ||\n      lower.includes(\"qrun_exit_code=-9\") ||\n      lower.includes(\"\\nkilled\") ||\n      lower.includes(\"process was killed\")\n    ) {\n      return \"Execution failed: the Qlib process was killed before producing a complete backtest result. Check memory/container limits, then retry this same loop.\";\n    }\n    if (\n      lower.includes(\"qrun_exit_code=124\") ||\n      lower.includes(\"timed out\") ||\n      lower.includes(\"running time exceeds\")\n    ) {\n      return \"Execution failed: the Qlib run timed out before producing a complete backtest result. Fix the runtime issue, then retry this same loop.\";\n    }\n    return \"Execution failed: Qlib did not produce a valid backtest result. This is not evidence that the research hypothesis is bad.\";\n  }\n\n  return String(\n    feedback.hypothesis_evaluation ||\n      feedback.feedback ||\n      feedback.observations ||\n      feedback.exception ||\n      \"\"\n  );\n};\n\nconst updateData = () => {";
if (!resultS46.includes(helperP46Anchor)) { console.error("[patch-frontend] FAILED: P46 helper anchor drifted."); process.exit(1); }
resultS46 = resultS46.replace(helperP46Anchor, helperP46New);
const decisionP46Old = "    const decision = normalizeDecision(feedback.decision);\n    const hasStructuredPayload =";
const decisionP46New = "    const decision = normalizeDecision(feedback.decision);\n    const executionFailed = isExecutionFailureFeedback(feedback);\n    const rowStatus = executionFailed\n      ? \"execution_failed\"\n      : decision === true\n        ? \"success\"\n        : decision === false\n          ? \"research_failed\"\n          : \"incomplete\";\n    const hasStructuredPayload =";
if (!resultS46.includes(decisionP46Old)) { console.error("[patch-frontend] FAILED: P46 decision anchor drifted."); process.exit(1); }
resultS46 = resultS46.replace(decisionP46Old, decisionP46New);
const rowP46Old = "        reason:\n          feedback.reason ||\n          feedback.hypothesis_evaluation ||\n          feedback.feedback ||\n          \"\",\n        observations: feedback.observations || \"\",\n        decision: decision === true,";
const rowP46New = "        reason: getFeedbackDisplayReason(feedback),\n        observations: feedback.observations || \"\",\n        exception: feedback.exception || \"\",\n        decision: decision === true,\n        status: rowStatus,";
if (!resultS46.includes(rowP46Old)) { console.error("[patch-frontend] FAILED: P46 row anchor drifted."); process.exit(1); }
resultS46 = resultS46.replace(rowP46Old, rowP46New);
const statusP46Old = "              <template #default=\"scope\">\n                <span v-if=\"scope.row.decision\" class=\"success\">Success</span>\n                <span v-if=\"!scope.row.decision\" class=\"fail\">Failed</span>\n              </template>";
const statusP46New = "              <template #default=\"scope\">\n                <span v-if=\"scope.row.status === 'success'\" class=\"success\">Success</span>\n                <span\n                  v-else-if=\"scope.row.status === 'execution_failed'\"\n                  class=\"fail\"\n                  title=\"The experiment did not complete; this is not a research rejection.\"\n                >Execution Failed</span>\n                <span v-else-if=\"scope.row.status === 'research_failed'\" class=\"fail\">Research Failed</span>\n                <span v-else class=\"fail\">Incomplete</span>\n              </template>";
if (!resultS46.includes(statusP46Old)) { console.error("[patch-frontend] FAILED: P46 status anchor drifted."); process.exit(1); }
resultS46 = resultS46.replace(statusP46Old, statusP46New);
const feedbackP46Old = "                {{\n                  scope.row.reason ||\n                  \"No reason generated due to some errors happened in previous steps\"\n                }}";
const feedbackP46New = "                {{\n                  scope.row.reason ||\n                  scope.row.observations ||\n                  scope.row.exception ||\n                  \"No feedback was generated for this loop.\"\n                }}";
if (!resultS46.includes(feedbackP46Old)) { console.error("[patch-frontend] FAILED: P46 feedback anchor drifted."); process.exit(1); }
resultS46 = resultS46.replace(feedbackP46Old, feedbackP46New);
const detailStatusP46Old = "                      <span v-if=\"props.row.decision\" class=\"success\"\n                        >Success</span\n                      >\n                      <span v-if=\"!props.row.decision\" class=\"fail\"\n                        >Failed</span\n                      >";
const detailStatusP46New = "                      <span v-if=\"props.row.status === 'success'\" class=\"success\"\n                        >Success</span\n                      >\n                      <span v-else-if=\"props.row.status === 'execution_failed'\" class=\"fail\"\n                        >Execution Failed</span\n                      >\n                      <span v-else-if=\"props.row.status === 'research_failed'\" class=\"fail\"\n                        >Research Failed</span\n                      >\n                      <span v-else class=\"fail\">Incomplete</span>";
if (!resultS46.includes(detailStatusP46Old)) { console.error("[patch-frontend] FAILED: P46 detail status anchor drifted."); process.exit(1); }
resultS46 = resultS46.replace(detailStatusP46Old, detailStatusP46New);
fs.writeFileSync(resultP46, resultS46);
console.log("[patch-frontend] P46 execution-failure status/reason UI applied to ResultPage.vue");


// ------------------------- P48: live RESULT while the run is still active -------------------------
const apiP48Path = "/src/web/src/utils/api.js";
let apiS48 = fs.readFileSync(apiP48Path, "utf8");
const apiP48Anchor = `export function getResumeOptions(traceId) {`;
const apiP48Insert = `export function getLiveResults(traceId) {
    const query = new URLSearchParams({ id: traceId });
    return request({
        url: url + "result/live?" + query.toString(),
        method: "get"
    });
}

export function getResumeOptions(traceId) {`;
if (!apiS48.includes(apiP48Anchor)) {
  console.error("[patch-frontend] FAILED: P48 api anchor drifted.");
  process.exit(1);
}
apiS48 = apiS48.replace(apiP48Anchor, apiP48Insert);
fs.writeFileSync(apiP48Path, apiS48);
console.log("[patch-frontend] P48 live-result API helper applied to api.js");

const pgP48 = "/src/web/src/views/PlaygroundPage.vue";
let pgS48 = fs.readFileSync(pgP48, "utf8");
const loadingResultP48Old =
  '<div class="tab-item-btn" v-if="resultData.length == 0 && !updateEnd && !stopFlag">';
const loadingResultP48New =
  '<div class="tab-item-btn" v-if="resultData.length == 0 && !updateEnd && !stopFlag" @click="tabIndex = 1" :class="{ active: tabIndex == 1 }">';
if (!pgS48.includes(loadingResultP48Old)) {
  console.error("[patch-frontend] FAILED: P48 RESULT loading-tab anchor drifted.");
  process.exit(1);
}
pgS48 = pgS48.replace(loadingResultP48Old, loadingResultP48New);
fs.writeFileSync(pgP48, pgS48);
console.log("[patch-frontend] P48 RESULT tab is clickable before the first loop completes");

const resultP48 = "/src/web/src/views/ResultPage.vue";
let resultS48 = fs.readFileSync(resultP48, "utf8");

const vueImportP48Old =
  'import { ref, watch, computed, defineProps, onMounted, nextTick } from "vue";';
const vueImportP48New =
  'import { ref, watch, computed, defineProps, onMounted, onUnmounted, nextTick } from "vue";';
if (!resultS48.includes(vueImportP48Old)) {
  console.error("[patch-frontend] FAILED: P48 Vue import anchor drifted.");
  process.exit(1);
}
resultS48 = resultS48.replace(vueImportP48Old, vueImportP48New);

const apiImportP48Old =
  'import { getStdoutDownloadUrl, getResumeOptions, resumeTrace } from "../utils/api";';
const apiImportP48New =
  'import { getStdoutDownloadUrl, getResumeOptions, resumeTrace, getLiveResults } from "../utils/api";';
if (!resultS48.includes(apiImportP48Old)) {
  console.error("[patch-frontend] FAILED: P48 ResultPage API import anchor drifted.");
  process.exit(1);
}
resultS48 = resultS48.replace(apiImportP48Old, apiImportP48New);

const stateP48Anchor = "const metricData = ref(null);";
const stateP48New = `const metricData = ref(null);
const liveResultRows = ref([]);
const liveResultAlive = ref(false);
const liveResultLastUpdated = ref("");
let liveResultTimer = null;
let liveResultRequestInFlight = false;`;
if (!resultS48.includes(stateP48Anchor)) {
  console.error("[patch-frontend] FAILED: P48 live state anchor drifted.");
  process.exit(1);
}
resultS48 = resultS48.replace(stateP48Anchor, stateP48New);

const rowsP48Old =
  "  const rows = Array.isArray(currentData.value) ? currentData.value : [];";
const rowsP48New = `  const propRows = Array.isArray(currentData.value) ? currentData.value : [];
  const liveRows = Array.isArray(liveResultRows.value) ? liveResultRows.value : [];
  const liveByLoop = new Map(
    liveRows
      .filter((item) => item && Number.isInteger(Number(item.loop_id)))
      .map((item) => [Number(item.loop_id), item])
  );
  const maxLoopId = liveRows.reduce((maxValue, item) => {
    const loopId = Number(item?.loop_id);
    return Number.isInteger(loopId) ? Math.max(maxValue, loopId) : maxValue;
  }, -1);
  const rowCount = Math.max(propRows.length, maxLoopId + 1);
  const rows = Array.from({ length: rowCount }, (_, index) => {
    const base =
      propRows[index] && typeof propRows[index] === "object"
        ? propRows[index]
        : {};
    const live = liveByLoop.get(index);
    if (!live) return base;

    return {
      ...base,
      researchHypothesis:
        live.researchHypothesis || base.researchHypothesis || null,
      feedbackMetric:
        live.feedbackMetric || base.feedbackMetric || null,
      feedbackHypothesis:
        live.feedbackHypothesis || base.feedbackHypothesis || null,
      _liveLoopId: index,
      _liveComplete: Boolean(live.complete),
    };
  });`;
if (!resultS48.includes(rowsP48Old)) {
  console.error("[patch-frontend] FAILED: P48 rows merge anchor drifted.");
  process.exit(1);
}
resultS48 = resultS48.replace(rowsP48Old, rowsP48New);

const statusP48Old = `    const rowStatus = executionFailed
      ? "execution_failed"
      : decision === true
        ? "success"
        : decision === false
          ? "research_failed"
          : "incomplete";`;
const statusP48New = `    const hasFeedback = Object.keys(feedback).length > 0;
    const isLatestRow = index === rows.length - 1;
    const rowStatus = executionFailed
      ? "execution_failed"
      : decision === true
        ? "success"
        : decision === false
          ? "research_failed"
          : (!hasFeedback && liveResultAlive.value && isLatestRow)
            ? "running"
            : "incomplete";`;
if (!resultS48.includes(statusP48Old)) {
  console.error("[patch-frontend] FAILED: P48 row-status anchor drifted.");
  process.exit(1);
}
resultS48 = resultS48.replace(statusP48Old, statusP48New);

const mainStatusP48Old =
  '<span v-else-if="scope.row.status === \'research_failed\'" class="fail">Research Failed</span>\n                <span v-else class="fail">Incomplete</span>';
const mainStatusP48New =
  '<span v-else-if="scope.row.status === \'research_failed\'" class="fail">Research Failed</span>\n                <span v-else-if="scope.row.status === \'running\'" class="running-status">Running</span>\n                <span v-else class="fail">Incomplete</span>';
if (!resultS48.includes(mainStatusP48Old)) {
  console.error("[patch-frontend] FAILED: P48 main Running status anchor drifted.");
  process.exit(1);
}
resultS48 = resultS48.replace(mainStatusP48Old, mainStatusP48New);

const detailStatusP48Old =
  '<span v-else-if="props.row.status === \'research_failed\'" class="fail"\n                        >Research Failed</span\n                      >\n                      <span v-else class="fail">Incomplete</span>';
const detailStatusP48New =
  '<span v-else-if="props.row.status === \'research_failed\'" class="fail"\n                        >Research Failed</span\n                      >\n                      <span v-else-if="props.row.status === \'running\'" class="running-status"\n                        >Running</span\n                      >\n                      <span v-else class="fail">Incomplete</span>';
if (!resultS48.includes(detailStatusP48Old)) {
  console.error("[patch-frontend] FAILED: P48 detail Running status anchor drifted.");
  process.exit(1);
}
resultS48 = resultS48.replace(detailStatusP48Old, detailStatusP48New);

const emptyP48Old =
  "          No structured result events are available for this trace yet. The raw run log can still be downloaded above.";
const emptyP48New =
  '          {{ liveResultAlive ? "Run is in progress. Results will appear here as soon as each loop writes metrics or feedback." : "No structured result events are available for this trace yet. The raw run log can still be downloaded above." }}';
if (!resultS48.includes(emptyP48Old)) {
  console.error("[patch-frontend] FAILED: P48 empty-state anchor drifted.");
  process.exit(1);
}
resultS48 = resultS48.replace(emptyP48Old, emptyP48New);

const metricsTitleP48Old = "        <h2>Metrics</h2>";
const metricsTitleP48New = `        <div class="live-result-strip">
          <span class="live-result-dot" :class="{ active: liveResultAlive }"></span>
          <strong>{{ liveResultAlive ? "LIVE RESULTS" : "RESULT SNAPSHOT" }}</strong>
          <span>
            {{ liveResultRows.length }}
            {{ liveResultRows.length === 1 ? "loop" : "loops" }} available
          </span>
          <span v-if="liveResultAlive" class="live-result-note">
            updates automatically while the experiment is running
          </span>
        </div>
        <h2>Metrics</h2>`;
if (!resultS48.includes(metricsTitleP48Old)) {
  console.error("[patch-frontend] FAILED: P48 Metrics title anchor drifted.");
  process.exit(1);
}
resultS48 = resultS48.replace(metricsTitleP48Old, metricsTitleP48New);

const downloadAnchorP48 = "const downloadLogs = async () => {";
const pollingP48 = `const scheduleLiveResultPoll = (delay = 3500) => {
  if (liveResultTimer) clearTimeout(liveResultTimer);
  liveResultTimer = setTimeout(pollLiveResults, delay);
};

const pollLiveResults = async () => {
  if (liveResultRequestInFlight) return;
  const traceId = getTraceId();
  if (!traceId) return;

  liveResultRequestInFlight = true;
  try {
    const snapshot = await getLiveResults(traceId);
    liveResultRows.value = Array.isArray(snapshot?.loops) ? snapshot.loops : [];
    liveResultAlive.value = Boolean(snapshot?.alive);
    liveResultLastUpdated.value = snapshot?.updated_at || "";
    updateData();

    if (liveResultAlive.value) {
      scheduleLiveResultPoll(3500);
    }
  } catch (error) {
    // The trace can briefly be unavailable while a new run is being created.
    // Keep retrying without interrupting the normal /trace UI stream.
    scheduleLiveResultPoll(6000);
  } finally {
    liveResultRequestInFlight = false;
  }
};

`;
if (!resultS48.includes(downloadAnchorP48)) {
  console.error("[patch-frontend] FAILED: P48 polling method anchor drifted.");
  process.exit(1);
}
resultS48 = resultS48.replace(downloadAnchorP48, pollingP48 + downloadAnchorP48);

const mountedP48Old = `onMounted(() => {
  if (currentData.value) {
    updateData();
  }
});`;
const mountedP48New = `onMounted(() => {
  if (currentData.value) {
    updateData();
  }
  pollLiveResults();
});`;
if (!resultS48.includes(mountedP48Old)) {
  console.error("[patch-frontend] FAILED: P48 onMounted anchor drifted.");
  process.exit(1);
}
resultS48 = resultS48.replace(mountedP48Old, mountedP48New);

const traceWatchP48Old = `watch(
  () => props.traceName,
  (newValue) => {
    traceName.value = newValue;
  }
);`;
const traceWatchP48New = `watch(
  () => props.traceName,
  (newValue) => {
    traceName.value = newValue;
    liveResultRows.value = [];
    liveResultAlive.value = false;
    liveResultLastUpdated.value = "";
    pollLiveResults();
  }
);

onUnmounted(() => {
  if (liveResultTimer) {
    clearTimeout(liveResultTimer);
    liveResultTimer = null;
  }
});`;
if (!resultS48.includes(traceWatchP48Old)) {
  console.error("[patch-frontend] FAILED: P48 trace watcher anchor drifted.");
  process.exit(1);
}
resultS48 = resultS48.replace(traceWatchP48Old, traceWatchP48New);

const styleEndP48 = "</style>";
const styleP48 = `
.live-result-strip {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.55em;
  margin: 0 0 1em;
  padding: 0.65em 0.85em;
  border: 1px solid #dde4f2;
  border-radius: 12px;
  background: #fbfcff;
  color: #667087;
  font-size: 0.78em;
}

.live-result-strip strong {
  color: #3f485c;
  letter-spacing: 0.04em;
}

.live-result-dot {
  width: 0.62em;
  height: 0.62em;
  border-radius: 50%;
  background: #a8afbd;
}

.live-result-dot.active {
  background: #27a45d;
  box-shadow: 0 0 0 4px rgba(39, 164, 93, 0.12);
}

.live-result-note {
  color: #81899b;
}

.running-status {
  color: #376fcb;
  font-weight: 700;
}
`;
const styleIndexP48 = resultS48.lastIndexOf(styleEndP48);
if (styleIndexP48 === -1) {
  console.error("[patch-frontend] FAILED: P48 style end missing.");
  process.exit(1);
}
resultS48 =
  resultS48.slice(0, styleIndexP48) +
  styleP48 +
  resultS48.slice(styleIndexP48);

fs.writeFileSync(resultP48, resultS48);
console.log("[patch-frontend] P48 live RESULT polling/rendering applied to ResultPage.vue");


// ------------------------- P49: honest Feedback state for unfinished/stopped loops -------------------------
const feedbackP49 = "/src/web/src/components/feedback.vue";
let feedbackS49 = fs.readFileSync(feedbackP49, "utf8");

const hypEmptyP49Old = `        <div class="deduction-content" v-else>
          <p>
            No feedback generated due to some errors happened in previous steps.
          </p>
        </div>`;
const hypEmptyP49New = `        <div class="deduction-content feedback-pending" v-else>
          <h3>{{ updateEnd ? "Feedback not reached" : "Feedback pending" }}</h3>
          <p v-if="!updateEnd">
            This loop has not reached the feedback step yet. It may still be running.
          </p>
          <p v-else>
            This loop ended before feedback was generated, so it was not evaluated as
            a research success or failure. Check the run log for the stop reason.
          </p>
        </div>`;
if (!feedbackS49.includes(hypEmptyP49Old)) {
  console.error("[patch-frontend] FAILED: P49 hypothesis feedback-empty anchor drifted.");
  process.exit(1);
}
feedbackS49 = feedbackS49.replace(hypEmptyP49Old, hypEmptyP49New);

const chartEmptyP49Old = `        <div class="deduction-chart" v-else>
          <p style="padding-left: 1.875em">
            No feedback generated due to some errors happened in previous steps.
          </p>
        </div>`;
const chartEmptyP49New = `        <div class="deduction-chart feedback-pending" v-else>
          <p style="padding-left: 1.875em">
            {{
              updateEnd
                ? "No return chart was produced because this loop ended before backtest feedback completed."
                : "Return chart is not available yet. It will appear after the running/backtest step completes."
            }}
          </p>
        </div>`;
if (!feedbackS49.includes(chartEmptyP49Old)) {
  console.error("[patch-frontend] FAILED: P49 return-chart empty anchor drifted.");
  process.exit(1);
}
feedbackS49 = feedbackS49.replace(chartEmptyP49Old, chartEmptyP49New);

const configEmptyP49Old = `        <div v-else>
          <p style="padding-left: 1.875em">
            No feedback generated due to some errors happened in previous steps.
          </p>
        </div>`;
const configEmptyP49New = `        <div v-else>
          <p style="padding-left: 1.875em">
            Configuration is not available for this loop yet.
          </p>
        </div>`;
if (!feedbackS49.includes(configEmptyP49Old)) {
  console.error("[patch-frontend] FAILED: P49 feedback-config empty anchor drifted.");
  process.exit(1);
}
feedbackS49 = feedbackS49.replace(configEmptyP49Old, configEmptyP49New);

const feedbackStyleEndP49 = "</style>";
const feedbackStyleP49 = `
.feedback-pending {
  color: #687189;
}

.feedback-pending h3 {
  color: #3f485c;
}
`;
const feedbackStyleIndexP49 = feedbackS49.lastIndexOf(feedbackStyleEndP49);
if (feedbackStyleIndexP49 === -1) {
  console.error("[patch-frontend] FAILED: P49 feedback style end missing.");
  process.exit(1);
}
feedbackS49 =
  feedbackS49.slice(0, feedbackStyleIndexP49) +
  feedbackStyleP49 +
  feedbackS49.slice(feedbackStyleIndexP49);

fs.writeFileSync(feedbackP49, feedbackS49);
console.log("[patch-frontend] P49 unfinished-loop Feedback messaging applied");


// P49: an unfinished loop is neutral/incomplete in the left rail, not a red research failure.
const loopRailP49 = "/src/web/src/components/loop-component.vue";
let loopRailS49 = fs.readFileSync(loopRailP49, "utf8");

const loopStatusMapP49Old = `  statusList.value = currentData.value.map((item) => {
    return item.feedbackHypothesis ? item.feedbackHypothesis.decision : false;
  });`;
const loopStatusMapP49New = `  statusList.value = currentData.value.map((item) => {
    if (!item || !item.feedbackHypothesis) return null;
    return item.feedbackHypothesis.decision === true;
  });`;
if (!loopRailS49.includes(loopStatusMapP49Old)) {
  console.error("[patch-frontend] FAILED: P49 loop status-map anchor drifted.");
  process.exit(1);
}
loopRailS49 = loopRailS49.replace(loopStatusMapP49Old, loopStatusMapP49New);

const loopIconsP49Old = `              <img
                v-if="statusList[index - 1]"
                src="@/assets/playground-images/loop-Sucess.svg"
                alt="loading"
              />
              <img
                v-else
                src="@/assets/playground-images/loop-error.svg"
                alt="loading"
              />`;
const loopIconsP49New = `              <img
                v-if="statusList[index - 1] === true"
                src="@/assets/playground-images/loop-Sucess.svg"
                alt="success"
              />
              <img
                v-else-if="statusList[index - 1] === false"
                src="@/assets/playground-images/loop-error.svg"
                alt="failed"
              />
              <img
                v-else
                src="@/assets/playground-images/loop-default.svg"
                alt="incomplete"
              />`;
if (!loopRailS49.includes(loopIconsP49Old)) {
  console.error("[patch-frontend] FAILED: P49 loop icon anchor drifted.");
  process.exit(1);
}
loopRailS49 = loopRailS49.replace(loopIconsP49Old, loopIconsP49New);

fs.writeFileSync(loopRailP49, loopRailS49);
console.log("[patch-frontend] P49 neutral incomplete-loop status applied to loop rail");


// ------------------------- P50: make the active resume loop explicit -------------------------
const resumeUiP50 = "/src/web/src/views/Playground.vue";
let resumeUiS50 = fs.readFileSync(resumeUiP50, "utf8");
const resumeToastP50Old = `    ElMessage.success(
      "Continuation started from the selected experiment loop."
    );`;
const resumeToastP50New = `    const activeLoopNumber = Number(result?.resume_start_loop_number);
    ElMessage.success(
      Number.isFinite(activeLoopNumber)
        ? \`Continuation started at Loop \${activeLoopNumber}. Earlier loops are retained only as history.\`
        : "Continuation started from the selected experiment loop."
    );`;
if (!resumeUiS50.includes(resumeToastP50Old)) {
  console.error("[patch-frontend] FAILED: P50 continuation toast anchor drifted.");
  process.exit(1);
}
resumeUiS50 = resumeUiS50.replace(resumeToastP50Old, resumeToastP50New);
fs.writeFileSync(resumeUiP50, resumeUiS50);
console.log("[patch-frontend] P50 active resume-loop message applied to Playground.vue");


// ------------------------- P51: previous-experiment history consistency -------------------------
const historyUiP51 = "/src/web/src/views/Playground.vue";
let historyUiS51 = fs.readFileSync(historyUiP51, "utf8");

const historyBuildP51Old = `async function buildHistoryTraceList() {
  const groupedTraceMap = new Map();
  const completedIdList = getCompletedIdList();
  const backendTraceIds = await getHistoryTraceIds().then((response) =>
    Array.isArray(response) ? response : []
  ).catch(() => []);

  const traceIdList = [...new Set([...completedIdList, ...backendTraceIds])];
  traceIdList.forEach((traceId) => appendTraceId(groupedTraceMap, traceId));

  historyScenarioList.value = Array.from(groupedTraceMap.entries()).map(
    ([scenario, traceMap]) => ({
      name: scenario,
      children: Array.from(traceMap.values()),
    })
  );

  const lastCompletedTraceId = String(
    completedIdList[completedIdList.length - 1] || ""
  ).trim();
  const separatorIndex = lastCompletedTraceId.indexOf("/");
  const lastScenarioName =
    separatorIndex === -1 ? "" : lastCompletedTraceId.slice(0, separatorIndex);
  const defaultScenarioIndex = historyScenarioList.value.findIndex(
    (scenario) => scenario.name === lastScenarioName
  );
  const defaultScenario =
    defaultScenarioIndex >= 0
      ? historyScenarioList.value[defaultScenarioIndex]
      : historyScenarioList.value[historyScenarioList.value.length - 1] || null;

  selectLastHistoryTrace(defaultScenario, defaultScenarioIndex);
  await loadHistoryResumeOptions();
}`;

const historyBuildP51New = `async function buildHistoryTraceList() {
  const groupedTraceMap = new Map();
  const completedIdList = getCompletedIdList();

  // The backend /traces endpoint reflects what actually exists on persistent
  // storage. localStorage is only a fallback for a temporary backend failure.
  let backendTraceIds = [];
  let backendHistoryAvailable = false;
  try {
    const response = await getHistoryTraceIds();
    backendHistoryAvailable = true;
    backendTraceIds = Array.isArray(response)
      ? response.map((item) => String(item || "").trim()).filter(Boolean)
      : [];
  } catch {
    backendHistoryAvailable = false;
  }

  const traceIdList = backendHistoryAvailable
    ? [...new Set(backendTraceIds)]
    : [...new Set(completedIdList)];

  // Prune browser-only stale IDs after trace cleanup so deleted experiments do
  // not remain selectable forever.
  if (backendHistoryAvailable) {
    const backendSet = new Set(backendTraceIds);
    const prunedCompletedIds = completedIdList.filter((traceId) =>
      backendSet.has(String(traceId || "").trim())
    );
    if (prunedCompletedIds.length !== completedIdList.length) {
      localStorage.setItem(
        completedTraceStorageKey,
        JSON.stringify(prunedCompletedIds)
      );
    }
  }

  traceIdList.forEach((traceId) => appendTraceId(groupedTraceMap, traceId));

  historyScenarioList.value = Array.from(groupedTraceMap.entries()).map(
    ([scenario, traceMap]) => ({
      name: scenario,
      children: Array.from(traceMap.values()),
    })
  );

  // Backend returns oldest -> newest, so its last trace is the most recent durable
  // experiment. If the backend is unavailable, fall back to the browser's last ID.
  const preferredTraceId = String(
    (backendHistoryAvailable
      ? backendTraceIds[backendTraceIds.length - 1]
      : completedIdList[completedIdList.length - 1]) || ""
  ).trim();
  const separatorIndex = preferredTraceId.indexOf("/");
  const preferredScenarioName =
    separatorIndex === -1 ? "" : preferredTraceId.slice(0, separatorIndex);

  let defaultScenarioIndex = historyScenarioList.value.findIndex(
    (scenario) => scenario.name === preferredScenarioName
  );
  if (defaultScenarioIndex < 0 && historyScenarioList.value.length > 0) {
    defaultScenarioIndex = historyScenarioList.value.length - 1;
  }

  const defaultScenario =
    defaultScenarioIndex >= 0
      ? historyScenarioList.value[defaultScenarioIndex]
      : null;

  selectLastHistoryTrace(defaultScenario, defaultScenarioIndex);

  // Select the exact preferred trace when it exists instead of merely the last
  // item in the scenario. This keeps the dropdown and internal state aligned.
  if (defaultScenario && preferredTraceId) {
    const preferredTraceIndex = historyTraceList.value.findIndex(
      (item) => String(item?.id || "").trim() === preferredTraceId
    );
    if (preferredTraceIndex >= 0) {
      historyTraceCheckedIndex.value = preferredTraceIndex;
      historyTraceChecked.value = historyTraceList.value[preferredTraceIndex];
    }
  }

  await loadHistoryResumeOptions();
}`;

if (!historyUiS51.includes(historyBuildP51Old)) {
  console.error("[patch-frontend] FAILED: P51 history build anchor drifted.");
  process.exit(1);
}
historyUiS51 = historyUiS51.replace(historyBuildP51Old, historyBuildP51New);

const playgroundKeyP51Old = `      <playgroundPage
        :id="id"`;
const playgroundKeyP51New = `      <playgroundPage
        :key="id"
        :id="id"`;
if (!historyUiS51.includes(playgroundKeyP51Old)) {
  console.error("[patch-frontend] FAILED: P51 PlaygroundPage key anchor drifted.");
  process.exit(1);
}
historyUiS51 = historyUiS51.replace(playgroundKeyP51Old, playgroundKeyP51New);

fs.writeFileSync(historyUiP51, historyUiS51);
console.log("[patch-frontend] P51 authoritative previous-experiment list applied");

const pollUiP51 = "/src/web/src/views/PlaygroundPage.vue";
let pollUiS51 = fs.readFileSync(pollUiP51, "utf8");

const pollStateP51Old = `let transitionTimer = undefined;
const tabIndex = ref(0);`;
const pollStateP51New = `let transitionTimer = undefined;
let tracePollTimer = undefined;
let tracePollDisposed = false;
const tabIndex = ref(0);`;
if (!pollUiS51.includes(pollStateP51Old)) {
  console.error("[patch-frontend] FAILED: P51 trace-poll state anchor drifted.");
  process.exit(1);
}
pollUiS51 = pollUiS51.replace(pollStateP51Old, pollStateP51New);

const firstTraceThenP51Old = `  trace(data).then((response) => {
    if (response && response.length > 0) {`;
const firstTraceThenP51New = `  trace(data).then((response) => {
    if (tracePollDisposed) return;
    if (response && response.length > 0) {`;
if (!pollUiS51.includes(firstTraceThenP51Old)) {
  console.error("[patch-frontend] FAILED: P51 firstTrace response anchor drifted.");
  process.exit(1);
}
pollUiS51 = pollUiS51.replace(firstTraceThenP51Old, firstTraceThenP51New);

const tracePollStartP51Old = `const tracePoll = () => {
  if (stopFlag.value) {
    return;
  }`;
const tracePollStartP51New = `const tracePoll = () => {
  if (tracePollDisposed || stopFlag.value) {
    return;
  }`;
if (!pollUiS51.includes(tracePollStartP51Old)) {
  console.error("[patch-frontend] FAILED: P51 tracePoll start anchor drifted.");
  process.exit(1);
}
pollUiS51 = pollUiS51.replace(tracePollStartP51Old, tracePollStartP51New);

const tracePollThenP51Old = `  trace(data).then((response) => {
    if (response && response.length > 0) {`;
const tracePollThenP51New = `  trace(data).then((response) => {
    if (tracePollDisposed) return;
    if (response && response.length > 0) {`;
if (!pollUiS51.includes(tracePollThenP51Old)) {
  console.error("[patch-frontend] FAILED: P51 tracePoll response anchor drifted.");
  process.exit(1);
}
// first occurrence was already changed in firstTrace; replace the remaining exact occurrence.
pollUiS51 = pollUiS51.replace(tracePollThenP51Old, tracePollThenP51New);

const traceScheduleP51Old = `      setTimeout(tracePoll, 3000);`;
const traceScheduleP51New = `      if (!tracePollDisposed) {
        if (tracePollTimer) clearTimeout(tracePollTimer);
        tracePollTimer = setTimeout(tracePoll, 3000);
      }`;
if (!pollUiS51.includes(traceScheduleP51Old)) {
  console.error("[patch-frontend] FAILED: P51 tracePoll schedule anchor drifted.");
  process.exit(1);
}
pollUiS51 = pollUiS51.replace(traceScheduleP51Old, traceScheduleP51New);

const mountedP51Old = `onMounted(() => {
  firstTrace();
  progressPoll();
});

// 在组件被卸载前移除全局点击事件监听
onUnmounted(() => {
  if (activityTimer) clearTimeout(activityTimer);
});`;
const mountedP51New = `onMounted(() => {
  tracePollDisposed = false;
  firstTrace();
  progressPoll();
});

onUnmounted(() => {
  tracePollDisposed = true;
  if (tracePollTimer) {
    clearTimeout(tracePollTimer);
    tracePollTimer = undefined;
  }
  if (activityTimer) {
    clearTimeout(activityTimer);
    activityTimer = undefined;
  }
  if (transitionTimer) {
    clearTimeout(transitionTimer);
    transitionTimer = undefined;
  }
});`;
if (!pollUiS51.includes(mountedP51Old)) {
  console.error("[patch-frontend] FAILED: P51 lifecycle cleanup anchor drifted.");
  process.exit(1);
}
pollUiS51 = pollUiS51.replace(mountedP51Old, mountedP51New);

fs.writeFileSync(pollUiP51, pollUiS51);
console.log("[patch-frontend] P51 trace polling cleanup applied to PlaygroundPage.vue");
