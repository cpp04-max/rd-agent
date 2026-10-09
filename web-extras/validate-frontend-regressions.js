const fs = require("fs");
function read(path) {
  if (!fs.existsSync(path)) throw new Error("missing expected file: " + path);
  return fs.readFileSync(path, "utf8");
}
const playground = read("/src/web/src/views/Playground.vue");
const playgroundPage = read("/src/web/src/views/PlaygroundPage.vue");
const result = read("/src/web/src/views/ResultPage.vue");
const checks = {
  keyedPlaygroundPage: playground.includes(':key="id"'),
  reactiveContinuationRoute: playground.includes("route.query.trace") && playground.includes("applyDeepTrace"),
  resultUsesComputedData: playgroundPage.includes(':currentData="resultData"'),
  liveResultPolling: result.includes("getLiveResults") && result.includes("pollLiveResults"),
  terminalFailureCard: result.includes("liveResultFailure") && result.includes("execution-failure-summary"),
  inheritedContinuationResults: result.includes("liveResultInheritedCount") && result.includes("inherited from source experiment"),
  terminalAwarePolling: result.includes("if (!liveResultTerminal.value)"),
};
const failed = Object.entries(checks).filter((item) => !item[1]).map((item) => item[0]);
for (const item of Object.entries(checks)) {
  console.log("[frontend-regression] " + item[0] + ": " + (item[1] ? "OK" : "FAIL"));
}
if (failed.length) throw new Error("frontend regression checks failed: " + failed.join(", "));
console.log("[frontend-regression] all checks passed");
