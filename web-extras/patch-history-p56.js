const fs = require("fs");

const lines = (items) => items.join("\n");

// P56: structured history API helpers.
const apiPath = "/src/web/src/utils/api.js";
let api = fs.readFileSync(apiPath, "utf8");
const apiAnchor = lines([
  "export function getHistoryTraceIds() {",
  "    return request({",
  '        url: url + "traces",',
  "        method: 'get'",
  "    })",
  "}",
  "",
]);
const apiReplacement = apiAnchor + lines([
  "export function getHistoryExperiments() {",
  "    return request({",
  '        url: url + "history/experiments",',
  '        method: "get"',
  "    })",
  "}",
  "",
  "export function deleteHistoryExperiment(traceId) {",
  "    return request({",
  '        url: url + "history/experiment",',
  '        method: "delete",',
  "        headers: {",
  '            "Content-Type": "application/json"',
  "        },",
  "        data: { id: traceId }",
  "    })",
  "}",
  "",
]);
if (!api.includes(apiAnchor)) {
  console.error("[patch-history-p56] FAILED: history API anchor drifted.");
  process.exit(1);
}
api = api.replace(apiAnchor, apiReplacement);
fs.writeFileSync(apiPath, api);

// P56: timestamp-ranked experiment list + guarded deletion.
const pgPath = "/src/web/src/views/Playground.vue";
let pg = fs.readFileSync(pgPath, "utf8");

const elementImportOld = 'import { ElMessage } from "element-plus";';
const elementImportNew = 'import { ElMessage, ElMessageBox } from "element-plus";';
if (!pg.includes(elementImportOld)) {
  console.error("[patch-history-p56] FAILED: Element Plus import anchor drifted.");
  process.exit(1);
}
pg = pg.replace(elementImportOld, elementImportNew);

const apiImportOld =
  'import { getHistoryTraceIds, uploadFile, getResumeOptions, resumeTrace } from "../utils/api";';
const apiImportNew =
  'import { getHistoryExperiments, deleteHistoryExperiment, uploadFile, getResumeOptions, resumeTrace } from "../utils/api";';
if (!pg.includes(apiImportOld)) {
  console.error("[patch-history-p56] FAILED: Playground API import anchor drifted.");
  process.exit(1);
}
pg = pg.replace(apiImportOld, apiImportNew);

const selectOld = lines([
  "const selectLastHistoryTrace = (scenario, scenarioIndex = -1) => {",
  "  const traceList = Array.isArray(scenario?.children) ? scenario.children : [];",
  "  const lastTraceIndex = traceList.length - 1;",
  "",
  "  historyScenarioChecked.value = scenario || null;",
  "  historyScenarioCheckedIndex.value = scenarioIndex;",
  "  historyTraceList.value = traceList;",
  "  historyTraceCheckedIndex.value = lastTraceIndex;",
  "  historyTraceChecked.value = lastTraceIndex >= 0 ? traceList[lastTraceIndex] : null;",
  "};",
]);
const selectNew = lines([
  "const selectLastHistoryTrace = (scenario, scenarioIndex = -1) => {",
  "  const traceList = Array.isArray(scenario?.children) ? scenario.children : [];",
  "  const newestTraceIndex = traceList.length > 0 ? 0 : -1;",
  "",
  "  historyScenarioChecked.value = scenario || null;",
  "  historyScenarioCheckedIndex.value = scenarioIndex;",
  "  historyTraceList.value = traceList;",
  "  historyTraceCheckedIndex.value = newestTraceIndex;",
  "  historyTraceChecked.value =",
  "    newestTraceIndex >= 0 ? traceList[newestTraceIndex] : null;",
  "};",
]);
if (!pg.includes(selectOld)) {
  console.error("[patch-history-p56] FAILED: default trace selection anchor drifted.");
  process.exit(1);
}
pg = pg.replace(selectOld, selectNew);

const stateOld = lines([
  'const historyListError = ref("");',
  "const historyResumeLoopOptions = computed(() =>",
]);
const stateNew = lines([
  'const historyListError = ref("");',
  'const historyDeletingId = ref("");',
  "const historyResumeLoopOptions = computed(() =>",
]);
if (!pg.includes(stateOld)) {
  console.error("[patch-history-p56] FAILED: history state anchor drifted.");
  process.exit(1);
}
pg = pg.replace(stateOld, stateNew);

const listAnchor = lines([
  "          </div>",
  "",
  '          <div v-if="historyTraceChecked" class="history-resume-config">',
]);
const listReplacement = lines([
  "          </div>",
  "",
  '          <div v-if="historyTraceList.length" class="history-experiment-section">',
  '            <div class="history-experiment-heading">',
  "              <span>Experiments</span>",
  "              <span>{{ historyTraceList.length }} total · newest first</span>",
  "            </div>",
  '            <div class="history-experiment-list">',
  "              <div",
  '                v-for="(experiment, index) in historyTraceList"',
  '                :key="experiment.id"',
  '                class="history-experiment-row"',
  "                :class=\"{",
  "                  selected:",
  "                    String(historyTraceChecked?.id || '') ===",
  "                    String(experiment.id || ''),",
  "                }\"",
  '                @click="selectHistoryExperiment(experiment, index)"',
  "              >",
  '                <div class="history-experiment-main">',
  '                  <div class="history-experiment-name-line">',
  "                    <strong>{{ experiment.name }}</strong>",
  '                    <span v-if="experiment.active" class="history-running-badge">',
  "                      RUNNING",
  "                    </span>",
  "                  </div>",
  '                  <div class="history-experiment-time">',
  "                    {{ formatHistoryTimestamp(experiment.timestamp) }}",
  "                  </div>",
  "                </div>",
  "                <button",
  '                  class="history-delete-btn"',
  "                  :disabled=\"",
  "                    experiment.active ||",
  "                    historyDeletingId === String(experiment.id || '')",
  "                  \"",
  "                  :title=\"",
  "                    experiment.active",
  "                      ? 'A running experiment cannot be deleted.'",
  "                      : 'Permanently delete this experiment, its checkpoints/results, and stdout log.'",
  "                  \"",
  '                  @click.stop="deleteHistoryExperimentFromUi(experiment)"',
  "                >",
  "                  {{",
  "                    historyDeletingId === String(experiment.id || '')",
  '                      ? "DELETING…"',
  '                      : "DELETE"',
  "                  }}",
  "                </button>",
  "              </div>",
  "            </div>",
  "          </div>",
  "",
  '          <div v-if="historyTraceChecked" class="history-resume-config">',
]);
if (!pg.includes(listAnchor)) {
  console.error("[patch-history-p56] FAILED: history list UI anchor drifted.");
  process.exit(1);
}
pg = pg.replace(listAnchor, listReplacement);

const selectedOld = lines([
  "                <strong>{{ historyTraceChecked.name }}</strong>",
  '                <span v-if="historyResumeInfo.resume_meta?.source_id" class="history-lineage">',
]);
const selectedNew = lines([
  "                <strong>{{ historyTraceChecked.name }}</strong>",
  '                <span class="history-experiment-selected-time">',
  "                  {{ formatHistoryTimestamp(historyTraceChecked.timestamp) }}",
  "                </span>",
  '                <span v-if="historyResumeInfo.resume_meta?.source_id" class="history-lineage">',
]);
if (!pg.includes(selectedOld)) {
  console.error("[patch-history-p56] FAILED: selected timestamp anchor drifted.");
  process.exit(1);
}
pg = pg.replace(selectedOld, selectedNew);

// Replace the final P52 history loader with metadata-aware newest-first loading.
const buildStart = pg.indexOf("async function buildHistoryTraceList({");
const buildEndMarker = "\n\nconst generate = () => {";
const buildEnd = pg.indexOf(buildEndMarker, buildStart);
if (buildStart === -1 || buildEnd === -1) {
  console.error("[patch-history-p56] FAILED: final history loader not found.");
  process.exit(1);
}
const newBuild = lines([
  "async function buildHistoryTraceList({",
  "  loadResume = true,",
  "  force = false,",
  "} = {}) {",
  "  if (historyListLoaded.value && !force) {",
  "    if (loadResume) void loadHistoryResumeOptions();",
  "    return;",
  "  }",
  "",
  "  historyListLoading.value = true;",
  '  historyListError.value = "";',
  "  const completedIdList = getCompletedIdList();",
  "",
  "  let backendExperiments = [];",
  "  let backendHistoryAvailable = false;",
  "  try {",
  "    const response = await getHistoryExperiments();",
  "    backendHistoryAvailable = true;",
  "    backendExperiments = Array.isArray(response)",
  "      ? response",
  "          .map((item) => {",
  '            const id = String(item?.id || "").trim();',
  "            if (!id) return null;",
  "            const timestamp = String(",
  '              item?.timestamp || item?.updated_at || ""',
  "            ).trim();",
  "            const timestampMsRaw = Number(item?.timestamp_ms);",
  "            const parsedTimestampMs = timestamp ? Date.parse(timestamp) : 0;",
  "            const timestampMs = Number.isFinite(timestampMsRaw)",
  "              ? timestampMsRaw",
  "              : Number.isFinite(parsedTimestampMs)",
  "                ? parsedTimestampMs",
  "                : 0;",
  "            return {",
  "              id,",
  "              name:",
  '                String(item?.name || "").trim() ||',
  "                getTraceNameFromId(id),",
  "              scenario:",
  '                String(item?.scenario || "").trim() ||',
  '                id.split("/")[0] ||',
  '                "",',
  "              timestamp,",
  "              timestampMs,",
  "              active: Boolean(item?.active),",
  "            };",
  "          })",
  "          .filter(Boolean)",
  "          .sort(",
  "            (a, b) =>",
  "              b.timestampMs - a.timestampMs ||",
  "              String(b.id).localeCompare(String(a.id))",
  "          )",
  "      : [];",
  "  } catch (error) {",
  "    backendHistoryAvailable = false;",
  "    if (!completedIdList.length) {",
  "      historyListError.value =",
  "        error?.response?.data?.error ||",
  "        error?.message ||",
  '        "Failed to load previous experiments.";',
  "    }",
  "  }",
  "",
  "  const experiments = backendHistoryAvailable",
  "    ? backendExperiments",
  "    : [...new Set(completedIdList)]",
  "        .reverse()",
  "        .map((traceId) => {",
  '          const id = String(traceId || "").trim();',
  "          return {",
  "            id,",
  "            name: getTraceNameFromId(id),",
  '            scenario: id.includes("/") ? id.slice(0, id.indexOf("/")) : id,',
  '            timestamp: "",',
  "            timestampMs: 0,",
  "            active: false,",
  "          };",
  "        })",
  "        .filter((item) => item.id);",
  "",
  "  if (backendHistoryAvailable) {",
  "    const backendSet = new Set(backendExperiments.map((item) => item.id));",
  "    const prunedCompletedIds = completedIdList.filter((traceId) =>",
  '      backendSet.has(String(traceId || "").trim())',
  "    );",
  "    if (prunedCompletedIds.length !== completedIdList.length) {",
  "      localStorage.setItem(",
  "        completedTraceStorageKey,",
  "        JSON.stringify(prunedCompletedIds)",
  "      );",
  "    }",
  "  }",
  "",
  "  const groupedTraceMap = new Map();",
  "  experiments.forEach((experiment) => {",
  '    const scenario = String(experiment.scenario || "").trim();',
  '    const traceName = String(experiment.name || "").trim();',
  "    if (!scenario || !traceName) return;",
  "    if (!groupedTraceMap.has(scenario)) {",
  "      groupedTraceMap.set(scenario, new Map());",
  "    }",
  "    groupedTraceMap.get(scenario).set(traceName, experiment);",
  "  });",
  "",
  "  historyScenarioList.value = Array.from(groupedTraceMap.entries()).map(",
  "    ([scenario, traceMap]) => ({",
  "      name: scenario,",
  "      children: Array.from(traceMap.values()).sort(",
  "        (a, b) =>",
  "          Number(b.timestampMs || 0) - Number(a.timestampMs || 0) ||",
  "          String(b.id).localeCompare(String(a.id))",
  "      ),",
  "    })",
  "  );",
  "",
  "  const preferredExperiment = experiments[0] || null;",
  "  const preferredScenarioName = String(",
  '    preferredExperiment?.scenario || ""',
  "  ).trim();",
  "  let defaultScenarioIndex = historyScenarioList.value.findIndex(",
  "    (scenario) => scenario.name === preferredScenarioName",
  "  );",
  "  if (defaultScenarioIndex < 0 && historyScenarioList.value.length > 0) {",
  "    defaultScenarioIndex = 0;",
  "  }",
  "  const defaultScenario =",
  "    defaultScenarioIndex >= 0",
  "      ? historyScenarioList.value[defaultScenarioIndex]",
  "      : null;",
  "",
  "  selectLastHistoryTrace(defaultScenario, defaultScenarioIndex);",
  "",
  "  if (defaultScenario && preferredExperiment?.id) {",
  "    const preferredTraceIndex = historyTraceList.value.findIndex(",
  "      (item) =>",
  '        String(item?.id || "").trim() ===',
  '        String(preferredExperiment.id || "").trim()',
  "    );",
  "    if (preferredTraceIndex >= 0) {",
  "      historyTraceCheckedIndex.value = preferredTraceIndex;",
  "      historyTraceChecked.value =",
  "        historyTraceList.value[preferredTraceIndex];",
  "    }",
  "  }",
  "",
  "  historyListLoaded.value = true;",
  "  historyListLoading.value = false;",
  "  if (loadResume) void loadHistoryResumeOptions();",
  "}",
]);
pg = pg.slice(0, buildStart) + newBuild + pg.slice(buildEnd);

const actionAnchor = "const viewTracePage = () => {";
if (!pg.includes(actionAnchor)) {
  console.error("[patch-history-p56] FAILED: history action anchor drifted.");
  process.exit(1);
}
const actions = lines([
  "const formatHistoryTimestamp = (value) => {",
  '  const raw = String(value || "").trim();',
  '  if (!raw) return "Timestamp unavailable";',
  "  const date = new Date(raw);",
  "  if (Number.isNaN(date.getTime())) return raw;",
  "  return new Intl.DateTimeFormat(undefined, {",
  '    year: "numeric",',
  '    month: "short",',
  '    day: "2-digit",',
  '    hour: "2-digit",',
  '    minute: "2-digit",',
  '    second: "2-digit",',
  '    timeZoneName: "short",',
  "  }).format(date);",
  "};",
  "",
  "const selectHistoryExperiment = (experiment, index) => {",
  "  historyTraceCheckedIndex.value = index;",
  "  historyTraceChecked.value = experiment;",
  "  void loadHistoryResumeOptions();",
  "};",
  "",
  "const deleteHistoryExperimentFromUi = async (experiment) => {",
  '  const traceId = String(experiment?.id || "").trim();',
  "  if (!traceId) return;",
  "",
  "  if (experiment?.active) {",
  "    ElMessage.warning(",
  '      "This experiment is still running and cannot be deleted."',
  "    );",
  "    return;",
  "  }",
  "",
  "  try {",
  "    await ElMessageBox.confirm(",
  '      \'Permanently delete "\' +',
  "        (experiment?.name || traceId) +",
  '        \'"? This removes its trace data, durable loop checkpoints, result/feedback records, resume metadata, and stdout log. This cannot be undone.\',',
  '      "Delete experiment",',
  "      {",
  '        confirmButtonText: "Delete",',
  '        cancelButtonText: "Cancel",',
  '        type: "warning",',
  '        confirmButtonClass: "history-delete-confirm",',
  "      }",
  "    );",
  "  } catch {",
  "    return;",
  "  }",
  "",
  "  historyDeletingId.value = traceId;",
  '  historyListError.value = "";',
  "  try {",
  "    await deleteHistoryExperiment(traceId);",
  "    const remainingCompletedIds = getCompletedIdList().filter(",
  '      (item) => String(item || "").trim() !== traceId',
  "    );",
  "    localStorage.setItem(",
  "      completedTraceStorageKey,",
  "      JSON.stringify(remainingCompletedIds)",
  "    );",
  "",
  '    if (String(id.value || "").trim() === traceId) {',
  '      id.value = "";',
  "      showPlayground.value = false;",
  "    }",
  "",
  "    historyListLoaded.value = false;",
  "    resetHistoryResumeState();",
  "    await buildHistoryTraceList({ loadResume: true, force: true });",
  '    ElMessage.success("Experiment and its stored trace/log data were deleted.");',
  "  } catch (error) {",
  "    const message =",
  "      error?.response?.data?.error ||",
  "      error?.message ||",
  '      "Failed to delete the selected experiment.";',
  "    historyListError.value = message;",
  "    ElMessage.error(message);",
  "  } finally {",
  '    historyDeletingId.value = "";',
  "  }",
  "};",
  "",
]);
pg = pg.replace(actionAnchor, actions + actionAnchor);

const styleEnd = pg.lastIndexOf("</style>");
if (styleEnd === -1) {
  console.error("[patch-history-p56] FAILED: Playground style end missing.");
  process.exit(1);
}
const style = lines([
  "",
  ".history-experiment-section {",
  "  margin-top: 1.2em;",
  "  border-top: 1px solid var(--card-border-color);",
  "  padding-top: 1em;",
  "}",
  "",
  ".history-experiment-heading {",
  "  display: flex;",
  "  align-items: center;",
  "  justify-content: space-between;",
  "  gap: 1em;",
  "  margin-bottom: 0.65em;",
  "  font-size: 0.88em;",
  "  color: #6f7890;",
  "}",
  "",
  ".history-experiment-heading > span:first-child {",
  "  color: var(--text-color);",
  "  font-weight: 700;",
  "  font-size: 1.05em;",
  "}",
  "",
  ".history-experiment-list {",
  "  max-height: 18em;",
  "  overflow-y: auto;",
  "  border: 1px solid var(--card-border-color);",
  "  border-radius: 12px;",
  "  background: var(--bg-white);",
  "}",
  "",
  ".history-experiment-row {",
  "  display: flex;",
  "  align-items: center;",
  "  justify-content: space-between;",
  "  gap: 1em;",
  "  padding: 0.8em 0.9em;",
  "  cursor: pointer;",
  "  border-bottom: 1px solid var(--card-border-color);",
  "}",
  "",
  ".history-experiment-row:last-child { border-bottom: none; }",
  ".history-experiment-row:hover,",
  ".history-experiment-row.selected { background: var(--card-bg-hover-color); }",
  "",
  ".history-experiment-main { min-width: 0; flex: 1; }",
  ".history-experiment-name-line {",
  "  display: flex;",
  "  align-items: center;",
  "  gap: 0.55em;",
  "  min-width: 0;",
  "}",
  ".history-experiment-name-line strong {",
  "  min-width: 0;",
  "  overflow: hidden;",
  "  white-space: nowrap;",
  "  text-overflow: ellipsis;",
  "}",
  ".history-experiment-time,",
  ".history-experiment-selected-time {",
  "  color: #6f7890;",
  "  font-size: 0.82em;",
  "}",
  ".history-experiment-time { margin-top: 0.24em; }",
  ".history-experiment-selected-time { white-space: nowrap; }",
  "",
  ".history-running-badge {",
  "  flex: 0 0 auto;",
  "  border-radius: 999px;",
  "  padding: 0.16em 0.48em;",
  "  background: #eaf8ef;",
  "  color: #18743b;",
  "  font-size: 0.69em;",
  "  font-weight: 800;",
  "}",
  "",
  ".history-delete-btn {",
  "  flex: 0 0 auto;",
  "  border: 1px solid #e3a4a4;",
  "  background: transparent;",
  "  color: #a73535;",
  "  border-radius: 8px;",
  "  padding: 0.45em 0.7em;",
  "  font-size: 0.76em;",
  "  font-weight: 700;",
  "  cursor: pointer;",
  "}",
  ".history-delete-btn:hover:not(:disabled) { background: #fff1f1; }",
  ".history-delete-btn:disabled { opacity: 0.45; cursor: not-allowed; }",
  "",
]);
pg = pg.slice(0, styleEnd) + style + pg.slice(styleEnd);

fs.writeFileSync(pgPath, pg);
console.log("[patch-history-p56] timestamp-ranked history and delete UI applied");
