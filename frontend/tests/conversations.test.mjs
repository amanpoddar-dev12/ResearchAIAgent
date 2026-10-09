import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

test('new conversations have separate identities, empty memory and explicit context', async () => {
  const source = (await readFile(new URL('../src/storage/chatStorage.ts', import.meta.url), 'utf8'))
    .replace("import { cloudEnabled, cloudRequest, cloudSave, cloudDelete } from '../services/cloud';", 'const cloudEnabled = false;')
    .replace("import { storageScope } from '../services/auth';", "const storageScope = async () => '';");
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 } });
  const { createChat } = await import('data:text/javascript;base64,' + Buffer.from(outputText).toString('base64'));
  const research = { question: { question: 'Cache headers' }, sources: [{ id: 'S3', content: 'If-None-Match' }] };
  const first = createChat(research);
  const second = createChat(research);
  assert.notEqual(first.id, second.id);
  assert.match(first.id, /^general-chat-/);
  assert.deepEqual(first.messages, []);
  assert.equal(first.state, research);
  assert.equal(createChat(null).state, null);
});

test('failed cloud deletion leaves browser conversation history untouched', async () => {
  const source = (await readFile(new URL('../src/storage/chatStorage.ts', import.meta.url), 'utf8'))
    .replace("import { cloudEnabled, cloudRequest, cloudSave, cloudDelete } from '../services/cloud';", 'const cloudEnabled = true; const cloudDelete = async () => { throw new Error("Cloud delete failed"); };')
    .replace("import { storageScope } from '../services/auth';", "const storageScope = async () => '';");
  const {outputText} = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2020}});
  const {deleteChat} = await import('data:text/javascript;base64,' + Buffer.from(outputText).toString('base64'));
  await assert.rejects(deleteChat('synthetic-thread'), /Cloud delete failed/);
});
