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
