import assert from 'node:assert/strict';
import test from 'node:test';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
async function component(file, name) {
  const built = await build({ entryPoints: [fileURLToPath(new URL(file, import.meta.url))], bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic', external: ['react', 'react-dom', 'react/jsx-runtime'], logLevel: 'silent' });
  const module = { exports: {} };
  new Function('require', 'module', 'exports', built.outputFiles[0].text)(require, module, module.exports);
  return module.exports[name];
}
const EvidenceExplorer = await component('../src/components/EvidenceExplorer.tsx', 'EvidenceExplorer');
const ResearchReport = await component('../src/components/ResearchReport.tsx', 'ResearchReport');

test('evidence links reject executable URLs and retain HTTPS sources', () => {
  const render = (url) => renderToStaticMarkup(React.createElement(EvidenceExplorer, { evidence: [{ id: 'E1', source_id: 'S1', excerpt: 'Synthetic evidence', relation: 'supports', strength: 'direct' }], findings: [], sources: [{ id: 'S1', url, title: 'Synthetic', domain: 'example.invalid' }], onPreview() {} }));
  for (const url of ['javascript:alert(1)', 'data:text/html,unsafe', '//example.invalid']) assert.doesNotMatch(render(url), /href=/);
  assert.match(render('https://example.invalid'), /href="https:\/\/example.invalid"/);
});

test('report and interpretation notes do not automatically load remote images', () => {
  const html = renderToStaticMarkup(React.createElement(ResearchReport, { markdown: '# Synthetic\n## Analysis\n![tracking](https://attacker.invalid/private)\n\nInterpretive boundary: ![tracking](https://attacker.invalid/notes)\n', sources: [], onPreview() {} }));
  assert.doesNotMatch(html, /<img/);
});
