const fs = require("fs");
function read(path) {
  if (!fs.existsSync(path)) throw new Error("missing expected file: " + path);
  return fs.readFileSync(path, "utf8");
}
const playground = read("/src/web/src/views/Playground.vue");
const playgroundPage = read("/src/web/src/views/PlaygroundPage.vue");
const result = read("/src/web/src/views/ResultPage.vue");
const api = read("/src/web/src/utils/api.js");
const checks = {
  keyedPlaygroundPage: playground.includes(':key="id"'),
  reactiveContinuationRoute: playground.includes("route.query.trace") && playground.includes("applyDeepTrace"),
  resultUsesComputedData: playgroundPage.includes(':currentData="resultData"'),
  liveResultPolling: result.includes("getLiveResults") && result.includes("pollLiveResults"),
  terminalFailureCard: result.includes("liveResultFailure") && result.includes("execution-failure-summary"),
  inheritedContinuationResults: result.includes("liveResultInheritedCount") && result.includes("inherited from source experiment"),
  terminalAwarePolling: result.includes("if (!liveResultTerminal.value)"),
  resumeApiErrorNormalization: api.includes("Number(response.status) >= 400") && api.includes("error.response = response") && api.includes("return response.data"),
  liveResultApiErrorNormalization: api.includes("Live RESULT request failed with HTTP") && api.includes("Live RESULT response is missing a loops array"),
  monotonicLiveResultRows: result.includes("mergeLiveResultRows") && result.includes("mergeLiveResultRows(liveResultRows.value, snapshot.loops)"),
  controlApiErrorNormalization: api.includes("Control request failed with HTTP"),
  confirmedStopOnly: playgroundPage.includes('await controlBtn("stop")') && playgroundPage.includes('response?.status !== "stopped"') && playgroundPage.includes('title: "Stop failed"'),
  datasetCatalogApi: api.includes("getDatasetCatalog") && api.includes("data/catalog"),
  datasetSelectorUi: playground.includes("Modern CSI300") && playground.includes("dataset-config-card"),
  datasetSubsetSubmission: playground.includes('"dataset_config"') && playground.includes("resolvedDatasetFamilies"),
  datasetRequiredFamilies: playground.includes(":disabled=\"family.required\""),
  datasetPresets: playground.includes("Recommended") && playground.includes("Select all"),
  datasetCatalogLoadedOnMount: playground.includes("void loadDatasetCatalog();"),
  datasetPermissionHints: playground.includes("family.permission") && playground.includes("Tushare points"),
  datasetPreviewApi: api.includes("getDatasetPreview") && api.includes("data/preview"),
  datasetInspectorUi: playground.includes("dataset-preview-card") && playground.includes("Latest sample") && playground.includes("Refresh sample"),
  datasetInspectorOnSelection: playground.includes('@click="inspectDatasetFamily(family.id)"'),
  datasetInspectorFields: playground.includes("Fields available to RD-Agent") && playground.includes("point_in_time_note"),
};
const failed = Object.entries(checks).filter((item) => !item[1]).map((item) => item[0]);
for (const item of Object.entries(checks)) {
  console.log("[frontend-regression] " + item[0] + ": " + (item[1] ? "OK" : "FAIL"));
}
if (failed.length) throw new Error("frontend regression checks failed: " + failed.join(", "));
console.log("[frontend-regression] all checks passed");
