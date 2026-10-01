import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

// Run the actual API module with synthetic build-time env and offline browser transports.
const source = await readFile(new URL("../src/services/api.ts", import.meta.url), "utf8");
async function loadApi(env) {
  const { outputText } = ts.transpileModule(source.replaceAll("import.meta.env", JSON.stringify(env)), {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
  });
  return import("data:text/javascript;base64," + Buffer.from(outputText).toString("base64"));
}

for (const { label, env, base } of [
  { label: "development ignores a production URL and uses the proxy", env: { DEV: true, VITE_API_URL: "https://frontend.synthetic.invalid", VITE_BACKEND_URL: "https://backend.synthetic.invalid" }, base: "" },
  { label: "development defaults to the proxy without env URLs", env: { DEV: true }, base: "" },
  { label: "production honors the explicit API URL", env: { DEV: false, VITE_API_URL: "https://api.synthetic.invalid/", VITE_BACKEND_URL: "https://fallback.synthetic.invalid" }, base: "https://api.synthetic.invalid" },
  { label: "production keeps the legacy backend URL fallback", env: { DEV: false, VITE_BACKEND_URL: "https://backend.synthetic.invalid/" }, base: "https://backend.synthetic.invalid" },
  { label: "production supports a same-origin backend", env: { DEV: false }, base: "" },
]) {
  test(label, async (context) => {
    let requestedUrl;
    context.mock.method(globalThis, "fetch", async (url, init) => {
      requestedUrl = url;
      assert.equal(init.method, "POST");
      return { ok: true, json: async () => ({ research_id: "synthetic-session" }) };
    });
    const originalEventSource = Object.getOwnPropertyDescriptor(globalThis, "EventSource");
    const streams = [];
    globalThis.EventSource = class {
      constructor(url) { this.url = url; this.closed = false; streams.push(this); }
      close() { this.closed = true; }
    };
    context.after(() => {
      if (originalEventSource) Object.defineProperty(globalThis, "EventSource", originalEventSource);
      else delete globalThis.EventSource;
    });
    const api = await loadApi(env);
    const id = await api.startResearch({ question: "SYNTHETIC TEST ONLY", depth: "quick", max_sources: 5 });
    assert.equal(requestedUrl, base + "/api/research");
    const stop = api.streamResearch(id, () => {}, (error) => { throw error; });
    assert.equal(streams[0].url, base + "/api/research/synthetic-session/stream");
    stop();
    assert.equal(streams[0].closed, true);
  });
}

function streamHarness(context, fetchResult) {
  context.mock.method(globalThis, "fetch", fetchResult);
  const original = Object.getOwnPropertyDescriptor(globalThis, "EventSource");
  let stream;
  globalThis.EventSource = class {
    constructor() { this.closed = false; stream = this; }
    close() { this.closed = true; }
  };
  context.after(() => {
    if (original) Object.defineProperty(globalThis, "EventSource", original);
    else delete globalThis.EventSource;
  });
  return () => stream;
}

const syntheticResult = { status: "complete", final_report: "# SYNTHETIC TEST REPORT — NOT REAL RESEARCH", sources: [], findings: [], conflicts: [] };
const sendEvent = (stream, type, data) => stream.onmessage({ data: JSON.stringify({ type, data, message: "Synthetic test event", timestamp: "2026-01-01T00:00:00Z" }) });
const nextTurn = () => new Promise((resolve) => setImmediate(resolve));

test("recovers the completed report when the legacy stream omits complete", async (context) => {
  const requests = [];
  const getStream = streamHarness(context, async (url, init) => {
    requests.push({ url, method: init?.method || "GET" });
    return { ok: true, json: async () => syntheticResult };
  });
  const api = await loadApi({ DEV: true });
  const events = [], errors = [];
  api.streamResearch("synthetic-session", (event) => events.push(event), (error) => errors.push(error));
  sendEvent(getStream(), "research_completed", { searches_used: 1 });
  getStream().onerror(); // The same EOF that previously replaced a successful report with an error.
  await nextTurn();
  assert.deepEqual(events.map((event) => event.type), ["research_completed", "complete"]);
  assert.equal(events[1].data.report, syntheticResult.final_report);
  assert.equal(events[1].progress, 100);
  assert.deepEqual(errors, []);
  assert.deepEqual(requests, [{ url: "/api/research/synthetic-session", method: "GET" }]);
  assert.equal(getStream().closed, true);
});

test("a disconnected stream recovers an already completed result", async (context) => {
  const getStream = streamHarness(context, async () => ({ ok: true, json: async () => syntheticResult }));
  const api = await loadApi({ DEV: true });
  const events = [], errors = [];
  api.streamResearch("synthetic-session", (event) => events.push(event), (error) => errors.push(error));
  getStream().onerror();
  await nextTurn();
  assert.equal(events[0].type, "complete");
  assert.deepEqual(errors, []);
});

test("normal terminal events do not trigger recovery or subsequent errors", async (context) => {
  const getStream = streamHarness(context, async () => assert.fail("A terminal event must not fetch the result"));
  const api = await loadApi({ DEV: true });
  for (const type of ["complete", "research_failed"]) {
    const events = [], errors = [];
    api.streamResearch("synthetic-session", (event) => events.push(event), (error) => errors.push(error));
    sendEvent(getStream(), type, {});
    getStream().onerror();
    await nextTurn();
    assert.deepEqual(events.map((event) => event.type), [type]);
    assert.deepEqual(errors, []);
    assert.equal(getStream().closed, true);
  }
});

test("recovery waits briefly for the final result to be stored", async (context) => {
  let attempts = 0;
  const getStream = streamHarness(context, async () => ++attempts === 1 ? { ok: false, status: 404 } : { ok: true, json: async () => syntheticResult });
  const api = await loadApi({ DEV: true });
  const completed = new Promise((resolve, reject) => {
    api.streamResearch("synthetic-session", (event) => { if (event.type === "complete") resolve(event); }, reject);
  });
  sendEvent(getStream(), "research_completed", {});
  assert.equal((await completed).data.report, syntheticResult.final_report);
  assert.equal(attempts, 2);
});

test("a real interruption without a completed result still reports failure", async (context) => {
  let attempts = 0;
  const getStream = streamHarness(context, async () => { attempts++; return { ok: false, status: 404 }; });
  const api = await loadApi({ DEV: true });
  const failed = new Promise((resolve) => api.streamResearch("synthetic-session", () => assert.fail("No completed report exists"), resolve));
  getStream().onerror();
  assert.match((await failed).message, /before a completed report could be retrieved/);
  assert.equal(attempts, 3);
  assert.equal(getStream().closed, true);
});

test("reset and a normal complete event both suppress an in-flight recovery", async (context) => {
  const pending = [];
  const getStream = streamHarness(context, (_url, init) => new Promise((resolve) => pending.push({ resolve, signal: init.signal })));
  const api = await loadApi({ DEV: true });
  for (const terminal of ["reset", "complete"]) {
    const events = [], errors = [];
    const stop = api.streamResearch("synthetic-session", (event) => events.push(event), (error) => errors.push(error));
    getStream().onerror();
    if (terminal === "reset") stop();
    else sendEvent(getStream(), "complete", { state: syntheticResult, report: syntheticResult.final_report });
    const request = pending.shift();
    assert.equal(request.signal.aborted, true);
    request.resolve({ ok: true, json: async () => syntheticResult });
    await nextTurn();
    assert.equal(events.length, terminal === "reset" ? 0 : 1);
    assert.deepEqual(errors, []);
  }
});

test("session budgets and additive graph snapshots preserve the existing transport", async (context) => {
  const budgets = { max_searches: 4, max_sources: 6, max_iterations: 2, max_parallel_tasks: 2, max_wall_seconds: 30 };
  const getStream = streamHarness(context, async (_url, init) => {
    assert.deepEqual(JSON.parse(init.body).budgets, budgets);
    return { ok: true, json: async () => ({ research_id: "synthetic-session" }) };
  });
  const api = await loadApi({ DEV: true });
  const id = await api.startResearch({ question: "SYNTHETIC TEST", depth: "quick", max_sources: 6, budgets });
  const events = [];
  const stop = api.streamResearch(id, (event) => events.push(event), (error) => assert.fail(error.message));
  const state = { ...syntheticResult, graph: { nodes: [], edges: [] }, audit_log: [] };
  sendEvent(getStream(), "question_refined", { question: "SYNTHETIC TEST", assumptions: [] });
  sendEvent(getStream(), "research_snapshot", state);
  sendEvent(getStream(), "finding_updated", { id: "C1", evidence_status: "Unverified" });
  assert.deepEqual(events.map((event) => event.type), ["question_refined", "research_snapshot", "finding_updated"]);
  assert.deepEqual(events[1].data, state);
  stop();
});
