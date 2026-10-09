import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';
const source = await readFile(new URL('../src/ui/entryRoute.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } });
const { entryPage } = await import('data:text/javascript;base64,' + Buffer.from(outputText).toString('base64'));
test('first and guest visits show landing; persisted signed-in visits show research', () => {
  for (const path of ['/', '/landing', '/landing/']) {
    assert.equal(entryPage(path, false), 'landing');
    assert.equal(entryPage(path, true), 'research');
  }
});
test('the explicit app route keeps guest research available', () => {
  assert.equal(entryPage('/app', false), 'research');
  assert.equal(entryPage('/app', true), 'research');
});
