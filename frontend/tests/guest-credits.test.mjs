import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import ts from "typescript";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
const require = createRequire(import.meta.url);
let serial = 0;
const data = code => "data:text/javascript;base64," + Buffer.from(code + `\n// instance ${serial++}`).toString("base64");
const compile = source => ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText;
const read = name => readFile(new URL(`../src/${name}`, import.meta.url), "utf8");

test("simultaneous tabs and refresh reuse one persisted guest instead of renewing five credits", async () => {
  let session = null, created = 0, tail = Promise.resolve();
  globalThis.__guestFake = { auth: {
    getSession: async () => ({ data: { session }, error: null }),
    signInAnonymously: async () => { created++; await new Promise(resolve => setTimeout(resolve, 10)); session = { user: { id: "same-guest", is_anonymous: true } }; return { data: { session }, error: null }; },
  } };
  const navigatorBefore = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: { locks: { request: (_name, callback) => { const next = tail.then(callback); tail = next.catch(() => {}); return next; } } } });
  const load = async () => {
    let code = compile(await read("services/auth.ts"));
    code = code.replace(/import .* from '@supabase\/supabase-js';/, "const createClient = () => globalThis.__guestFake;");
    code = code.replaceAll("import.meta.env.VITE_SUPABASE_URL", '"https://test.invalid"').replaceAll("import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY", '"public-test-key"');
    return import(data(code));
  };
  try {
    const [tabA, tabB] = await Promise.all([load(), load()]);
    const [a, b] = await Promise.all([tabA.initializeAuth(), tabB.initializeAuth()]);
    assert.equal(created, 1); assert.equal(a.user.id, b.user.id);
    const reloaded = await load(); assert.equal((await reloaded.initializeAuth()).user.id, "same-guest"); assert.equal(created, 1);
    // A same-tab account change must not return a previously cached guest session.
    session = { user: { id: "signed-in-user", is_anonymous: false } };
    assert.equal((await tabA.initializeAuth()).user.id, "signed-in-user");
  } finally { Object.defineProperty(globalThis, "navigator", navigatorBefore); delete globalThis.__guestFake; }
});

test("allowance resync deduplicates requests and does not reset an exhausted workspace on reload", async () => {
  let calls = 0; globalThis.__usageRequest = async () => { calls++; return { guest: true, remaining: 0, limit: 5 }; };
  const load = async () => {
    let code = compile(await read("services/guestUsage.ts"));
    code = code.replace(/from 'react'/, `from "${pathToFileURL(require.resolve("react")).href}"`);
    code = code.replace(/import .* from '.\/auth';/, "const cloudEnabled = true; const initializeAuth = async () => globalThis.__signedInSession || null;").replace(/import .* from '.\/cloud';/, "const cloudRequest = () => globalThis.__usageRequest();");
    return import(data(code));
  };
  const service = await load();
  const [a, b] = await Promise.all([service.refreshGuestUsage(), service.refreshGuestUsage()]);
  assert.equal(calls, 1); assert.equal(a.remaining, 0); assert.deepEqual(a, b);
  const oldWindow = globalThis.window;
  const target = new EventTarget(); let prompts = 0;
  target.addEventListener('research-login-required', () => { prompts++; });
  globalThis.window = target;
  try {
    assert.equal(await service.validateResearchCredits(), false);
    assert.equal(prompts, 1, 'exhausted guests are directed to login before research');
    globalThis.__usageRequest = async () => ({ guest: true, remaining: 1, limit: 5 });
    assert.equal(await service.validateResearchCredits(), true); assert.equal(prompts, 1);
    globalThis.__usageRequest = async () => ({ guest: false, remaining: null, limit: null });
    assert.equal(await service.validateResearchCredits(), true); assert.equal(prompts, 1);
    globalThis.__signedInSession = { user: { is_anonymous: false } };
    globalThis.__usageRequest = async () => { throw new Error("Members should skip allowance request"); };
    assert.equal(await service.validateResearchCredits(), true);
    delete globalThis.__signedInSession;
    globalThis.__usageRequest = async () => ({ guest: true, remaining: 0, limit: 5 });
  } finally { globalThis.window = oldWindow; }
  assert.equal((await (await load()).refreshGuestUsage()).remaining, 0);
  globalThis.__usageRequest = async () => { throw new Error("Unavailable"); };
  await assert.rejects(service.refreshGuestUsage(), /Unavailable/); delete globalThis.__usageRequest;
});

test("exhausted credits show a Google sign-in action without changing report content", async () => {
  globalThis.__creditUsage = { usage: { guest: true, remaining: 0, limit: 5 }, error: "" };
  let code = compile(await read("components/GuestCredits.tsx"));
  for (const name of ["react", "react/jsx-runtime"]) code = code.replaceAll(`from "${name}"`, `from "${pathToFileURL(require.resolve(name)).href}"`).replaceAll(`from '${name}'`, `from "${pathToFileURL(require.resolve(name)).href}"`);
  code = code.replace(/import .* from '..\/services\/auth';/, "const cloudEnabled = true;")
    .replace(/import .* from '..\/services\/cloud';/, "const signInToWorkspace = async () => {};")
    .replace(/import .* from '..\/services\/guestUsage';/, "const useGuestUsage = () => globalThis.__creditUsage;")
    .replace(/import .* from '.\/GoogleIcon';/, "const GoogleIcon = () => null;");
  const { GuestCredits } = await import(data(code));
  const html = renderToStaticMarkup(React.createElement(GuestCredits));
  assert.match(html, /Your 5 free research credits are used up/); assert.match(html, /Sign in with Google/); assert.match(html, /import your guest workspace/);
  globalThis.__creditUsage = { usage: { guest: false, remaining: null, limit: null }, error: "" };
  assert.equal(renderToStaticMarkup(React.createElement(GuestCredits)), ""); delete globalThis.__creditUsage;
});
