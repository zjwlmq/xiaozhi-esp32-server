import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const componentSource = await readFile(
  new URL('../src/components/TtsModel.vue', import.meta.url),
  'utf8',
);
const apiSource = await readFile(
  new URL('../src/apis/module/timbre.js', import.meta.url),
  'utf8',
);

test('voice manager exposes manual Volcengine sync with both clone versions', () => {
  assert.match(componentSource, /syncUpstreamVoices/);
  assert.match(componentSource, /cloneVersion1/);
  assert.match(componentSource, /cloneVersion2/);
  assert.match(componentSource, /value="1\.0"/);
  assert.match(componentSource, /value="2\.0"/);
  assert.match(componentSource, /importUpstreamVoices/);
  assert.match(componentSource, /row\.imported/);
});

test('browser only calls manager-api and never receives OpenAPI credentials', () => {
  assert.match(apiSource, /\/ttsVoice\/upstream\/volcengine\/list/);
  assert.match(apiSource, /\/ttsVoice\/upstream\/volcengine\/import/);
  assert.doesNotMatch(componentSource, /access_key_id|access_key_secret/i);
  assert.doesNotMatch(apiSource, /open\.volcengineapi\.com/);
  assert.doesNotMatch(componentSource, /fetch\s*\(|axios\./);
});

test('only completed non-imported voices are selectable', () => {
  assert.match(componentSource, /!row\.imported\s*&&\s*\(state === 'success' \|\| state === 'active'\)/);
});
