import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';
const built = await build({entryPoints:[fileURLToPath(new URL('../src/state/researchStore.ts',import.meta.url))],bundle:true,write:false,platform:'node',format:'cjs',logLevel:'silent'});
const module={exports:{}};new Function('module','exports',built.outputFiles[0].text)(module,module.exports);
const {researchReducer,initialResearchSession}=module.exports;
const source={id:'S1',url:'https://synthetic.invalid/doc',content:'Original full source text',title:'Synthetic'};
const snapshot={sources:[{...source,content:undefined}],findings:[],evidence:[],conflicts:[],verifications:[],research_gaps:[]};
test('public snapshots preserve source text for saving and follow-up chat',()=>{
  const state={...initialResearchSession,sources:[source]};
  const updated=researchReducer(state,{type:'complete',data:{state:snapshot,report:'Report'}});
  assert.equal(updated.sources[0].content,source.content);
  assert.equal(updated.snapshot.sources[0].content,source.content);
  assert.equal(snapshot.sources[0].content,undefined);
});
test('source-text preservation cannot cross a reset or a different source URL',()=>{
  const reset=researchReducer({...initialResearchSession,sources:[source]},{type:'reset'});
  assert.equal(researchReducer(reset,{type:'complete',data:{state:snapshot,report:'New'}}).sources[0].content,undefined);
  const other={...snapshot,sources:[{...snapshot.sources[0],url:'https://different.invalid/doc'}]};
  assert.equal(researchReducer({...initialResearchSession,sources:[source]},{type:'complete',data:{state:other,report:'Other'}}).sources[0].content,undefined);
});
