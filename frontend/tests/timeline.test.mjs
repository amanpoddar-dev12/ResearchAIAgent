import assert from 'node:assert/strict';
import test from 'node:test';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const built = await build({ entryPoints: [fileURLToPath(new URL('../src/components/ResearchTimeline.tsx', import.meta.url))], bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic', external: ['react', 'react/jsx-runtime'], logLevel: 'silent' });
const module = { exports: {} };
new Function('require', 'module', 'exports', built.outputFiles[0].text)(createRequire(import.meta.url), module, module.exports);
const render = (status, types) => renderToStaticMarkup(React.createElement(module.exports.ResearchTimeline, { status, events: types.map(type => ({ type, message: type, timestamp: '2026-10-10T12:00:00Z' })) }));
test('timeline distinguishes pending, running, completed and failed stages', () => {
  assert.equal((render('idle', []).match(/>pending</g) || []).length, 4);
  const running = render('researching', ['planning_started', 'search_started']);
  assert.equal((running.match(/>done</g) || []).length, 1);
  assert.equal((running.match(/>running</g) || []).length, 1);
  assert.match(running, /aria-current="step"/);
  assert.match(render('error', ['search_started', 'research_failed']), />failed</);
  assert.equal((render('completed', ['research_completed']).match(/>done</g) || []).length, 4);
});
