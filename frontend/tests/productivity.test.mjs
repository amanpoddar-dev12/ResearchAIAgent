import assert from 'node:assert/strict';
import test from 'node:test';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';
import { build } from 'esbuild';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

test('local collections persist without API calls, replace by identity and isolate users', async () => {
  const previous = globalThis.localStorage;
  const entries = new Map();
  globalThis.localStorage = { getItem: key => entries.get(key) ?? null, setItem: (key,value) => entries.set(key,value) };
  globalThis.productivityTestScope = '-synthetic-user-a';
  try {
    let source = await readFile(new URL('../src/storage/productivityStorage.ts', import.meta.url),'utf8');
    source = source.replace(/^import .*;\r?\n/gm,'');
    source = `const cloudEnabled = false; const cloudRequest = () => {throw new Error('Unexpected network call')}; const cloudSave = cloudRequest; const storageScope = async () => globalThis.productivityTestScope;\n` + source;
    const { outputText } = ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2020}});
    const store = await import('data:text/javascript;base64,' + Buffer.from(outputText).toString('base64'));
    await store.saveProductivity('collection',{id:'synthetic',name:'First'});
    await store.saveProductivity('collection',{id:'synthetic',name:'Renamed'});
    assert.deepEqual(await store.listProductivity('collection'),[{id:'synthetic',name:'Renamed'}]);
    globalThis.productivityTestScope = '-synthetic-user-b';
    assert.deepEqual(await store.listProductivity('collection'),[]);
  } finally { globalThis.localStorage = previous; delete globalThis.productivityTestScope; }
});

test('version comparison distinguishes status changes from omitted claims', async () => {
  const built = await build({entryPoints:[fileURLToPath(new URL('../src/components/VersionComparison.tsx',import.meta.url))],bundle:true,write:false,platform:'node',format:'cjs',jsx:'automatic',external:['react','react/jsx-runtime'],logLevel:'silent'});
  const module = {exports:{}};
  new Function('require','module','exports',built.outputFiles[0].text)(createRequire(import.meta.url),module,module.exports);
  const finding = (id,claim,status) => ({id,claim,evidence_status:status});
  const previous = {id:'p',question:'Synthetic previous',savedAt:'2026-01-01',state:{findings:[finding('C1','SYNTHETIC claim','Unverified'),finding('C2','SYNTHETIC old claim','Supported')]}};
  const current = {id:'n',state:{parent_research_id:'p',findings:[finding('C1','synthetic claim','Supported')],gaps:['SYNTHETIC unknown cost']}};
  const html = renderToStaticMarkup(React.createElement(module.exports.VersionComparison,{current,saved:[previous,current]}));
  assert.match(html,/Unverified →/);
  assert.match(html,/Not investigated in this version/);
  assert.match(html,/do not prove a change in the world/);
  assert.match(html,/SYNTHETIC unknown cost/);
});


test('specific feedback reasons preserve the existing API fields and note limit', async () => {
  const previousState = globalThis.feedbackTestState;
  const previousSave = globalThis.feedbackTestSave;
  let saved;
  try {
    let source = await readFile(new URL('../src/components/ReportFeedback.tsx', import.meta.url), 'utf8');
    source = source.replace(/^import .*;\r?\n/gm, '');
    source = 'const useState = globalThis.feedbackTestState; const saveProductivity = globalThis.feedbackTestSave;\n' + source;
    const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX } }).outputText;
    const module = { exports: {} };
    const values = ['analysis', 'Missing information', 'Please explain the limitations.', 'Unclear explanation', '', false];
    let index = 0;
    globalThis.feedbackTestState = () => [values[index++], () => {}];
    globalThis.feedbackTestSave = async (kind, item) => { saved = { kind, item }; };
    new Function('require', 'module', 'exports', compiled)(createRequire(import.meta.url), module, module.exports);
    const walk = node => Array.isArray(node) ? node.flatMap(walk) : node && typeof node === 'object' && node.props ? [node, ...walk(node.props.children)] : [];
    const nodes = walk(module.exports.ReportFeedback({ researchId: 'synthetic-research', sections: [] }));
    const textarea = nodes.find(node => node.type === 'textarea');
    assert.equal(textarea.props.maxLength, 2000 - '[Unclear explanation] '.length);
    assert.ok(nodes.some(node => node.type === 'option' && node.props.children === 'Missed my question'));
    nodes.find(node => node.type === 'button').props.onClick();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(saved.kind, 'feedback');
    assert.equal(saved.item.category, 'Missing information');
    assert.equal(saved.item.researchId, 'synthetic-research');
    assert.equal(saved.item.section, 'analysis');
    assert.equal(saved.item.note, '[Unclear explanation] Please explain the limitations.');
  } finally {
    globalThis.feedbackTestState = previousState;
    globalThis.feedbackTestSave = previousSave;
  }
});
