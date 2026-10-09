import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

async function authenticatedApi() {
  const source = (await readFile(new URL('../src/services/api.ts', import.meta.url), 'utf8'))
    .replace("import { authHeaders, cloudEnabled } from './auth';", "const cloudEnabled = true; const authHeaders = async () => ({ Authorization: 'Bearer synthetic-token' });")
    .replaceAll('import.meta.env', '{ DEV: true }')
    .replace("window.dispatchEvent(new Event('research-usage-changed'));", '');
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } });
  return import('data:text/javascript;base64,' + Buffer.from(outputText).toString('base64'));
}

test('authenticated research SSE sends credentials in headers and handles split frames', async (context) => {
  let requested;
  context.mock.method(globalThis, 'fetch', async (url, init) => {
    requested = { url, init };
    const frame = `data: ${JSON.stringify({ type:'complete', message:'Saved', timestamp:'2026-10-09', research_id:'owned-session', sequence:1, data:{report:'Test'} })}\n\n`;
    const encoder = new TextEncoder();
    return { ok:true, body:new ReadableStream({ start(controller) {
      controller.enqueue(encoder.encode(frame.slice(0, 19)));
      controller.enqueue(encoder.encode(frame.slice(19))); controller.close();
    } }) };
  });
  const api = await authenticatedApi();
  const terminal = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('No terminal event')), 1000);
    api.streamResearch('owned-session', (event) => { clearTimeout(timer); resolve(event); }, reject);
  });
  assert.equal(terminal.type, 'complete');
  assert.equal(requested.init.headers.Authorization, 'Bearer synthetic-token');
  assert.equal(requested.url, '/api/research/owned-session/stream');
  assert.equal(requested.url.includes('token'), false);
});

test('guest quota denial surfaces the sign-in instruction without creating a stream', async (context) => {
  context.mock.method(globalThis, 'fetch', async () => ({ ok:false, json:async () => ({ detail:'Your five guest research runs are used. Sign in with Google to continue.' }) }));
  const api = await authenticatedApi();
  await assert.rejects(api.startResearch({ question:'Test research', depth:'quick', max_sources:5 }), /Sign in with Google/);
});

test('continuing research sends the parent ID while preserving the start response', async (context) => {
  let payload;
  context.mock.method(globalThis, 'fetch', async (_url, init) => {
    payload = JSON.parse(init.body);
    return { ok:true, json:async () => ({research_id:'new-version'}) };
  });
  const api = await authenticatedApi();
  assert.equal(await api.startResearch({question:'Synthetic follow-up', depth:'quick', max_sources:5, parent_research_id:'original'}), 'new-version');
  assert.equal(payload.parent_research_id, 'original');
});
