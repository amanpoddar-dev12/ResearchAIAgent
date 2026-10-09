import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
const source = await readFile(new URL('../src/ui/researchPresentation.ts', import.meta.url), 'utf8');
const {outputText} = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2020}});
const {gapLabel, usefulIdea, modeHelp} = await import('data:text/javascript;base64,' + Buffer.from(outputText).toString('base64'));
test('gap actions explain the missing evidence without exposing internal IDs', () => {
  assert.equal(gapLabel({description:'Q1: sub-question has no verified evidence'}), 'Find supporting evidence');
  assert.equal(gapLabel({description:'C2: lacks independent corroboration'}), 'Find independent corroboration');
  assert.equal(gapLabel({description:'C3: conflicting evidence'}), 'Investigate a disagreement');
});
test('suggestions reject generic publisher pages and all modes have guidance', () => {
  assert.equal(usefulIdea('What does the evidence say about Science | AAAS?'), false);
  assert.equal(usefulIdea('What does the evidence say about Artificial Intelligence | Department of Energy?'), false);
  assert.equal(usefulIdea('What does recent evidence show about battery storage and renewable grids?'), true);
  assert.equal(Object.keys(modeHelp).length, 7);
});
