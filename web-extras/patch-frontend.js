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

