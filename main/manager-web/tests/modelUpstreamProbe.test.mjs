import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const dialogSource = await readFile(
  new URL('../src/components/ModelEditDialog.vue', import.meta.url),
  'utf8',
);
const apiSource = await readFile(
  new URL('../src/apis/module/model.js', import.meta.url),
  'utf8',
);

test('model editor exposes server-side model discovery and connection testing', () => {
  assert.match(dialogSource, /fetchUpstreamModels\(true\)/);
  assert.match(dialogSource, /openAndTest/);
  assert.match(dialogSource, /probeModel/);
  assert.match(dialogSource, /probePrompt:\s*"hi"/);
  assert.match(dialogSource, /modelId:\s*this\.modelData\.duplicateMode \? null/);
  assert.match(dialogSource, /configJson:\s*\{ \.\.\.this\.form\.configJson \}/);
});

test('upstream API calls go through manager-api and never directly to the configured base URL', () => {
  assert.match(apiSource, /\/models\/upstream\/models/);
  assert.match(apiSource, /\/models\/upstream\/test/);
  assert.doesNotMatch(dialogSource, /fetch\s*\(/);
  assert.doesNotMatch(dialogSource, /axios\./);
});
