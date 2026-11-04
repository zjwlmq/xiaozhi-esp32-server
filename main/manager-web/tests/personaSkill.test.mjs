import assert from 'node:assert/strict';
import { File } from 'node:buffer';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import test from 'node:test';
import { pathToFileURL } from 'node:url';

const require = createRequire(import.meta.url);
const compiler = require('vue-template-compiler');
const { zipSync, strToU8 } = require('fflate');
const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const helperSource = await read('../src/utils/personaSkill.js');
const zipSource = await read('../src/utils/personaSkillZip.js');
const fflateUrl = new URL('./esm/index.mjs', pathToFileURL(require.resolve('fflate/package.json'))).href;
const zipModuleUrl = `data:text/javascript;base64,${Buffer.from(zipSource.replace("'fflate'", JSON.stringify(fflateUrl))).toString('base64')}`;
const helpers = await import(`data:text/javascript;base64,${Buffer.from(helperSource.replaceAll("'./personaSkillZip'", JSON.stringify(zipModuleUrl))).toString('base64')}`);
const componentSource = await read('../src/components/PersonaSkillImport.vue');
const pageSource = await read('../src/views/roleConfig.vue');
const messagesSource = await read('../src/i18n/personaSkill.js');
const { default: messages } = await import(`data:text/javascript;base64,${Buffer.from(messagesSource).toString('base64')}`);
const longPrompt = '# 人格与共同记忆\n' + '依据历史聊天，先回应眼前的问题。🙂\n'.repeat(250) + '\n结尾规则完整保留。\n';
const file = (text, name = 'SKILL.md') => new File([text], name);
const zipped = (files, name = 'persona.zip', options) => file(zipSync(Object.fromEntries(
  Object.entries(files).map(([path, text]) => [path, typeof text === 'string' ? strToU8(text) : text]),
), options), name);

function loadComponent(source, extra = {}) {
  const script = compiler.parseComponent(source).script.content
    .replace(/^import .*;[ \t]*\r?$/gm, '')
    .replace('export default', 'module.exports =');
  const sandbox = {
    module: { exports: {} }, ...helpers, ...extra,
    HeaderBar: {}, FunctionDialog: {}, ContextProviderDialog: {}, TtsAdvancedSettings: {},
    AgentSnapshotDialog: {}, NixiDaughterSettings: {}, NixiAccessPolicySettings: {},
    VersionFooter: {}, PersonaSkillImport: {},
  };
  vm.runInNewContext(script, sandbox);
  return sandbox.module.exports;
}

function importer() {
  const component = loadComponent(componentSource);
  const events = [], errors = [], successes = [];
  const instance = {
    ...component.data(), value: '原来的角色', agentName: '测试角色', disabled: false,
    $emit: (...args) => events.push(args),
    $t: (key) => key,
    $message: { error: (message) => errors.push(message), success: (message) => successes.push(message) },
  };
  for (const [name, method] of Object.entries(component.methods)) instance[name] = method.bind(instance);
  return { component, instance, events, errors, successes };
}

function rolePage() {
  const writes = [], errors = [];
  const Api = { agent: { updateAgentConfig: (id, body) => writes.push({ id, body }) } };
  const component = loadComponent(pageSource, { Api });
  const instance = {
    ...component.data.call({ $t: (key) => key }),
    $route: { query: { agentId: 'local-agent' } },
    $t: (key) => key,
    $message: { error: (message) => errors.push(message) },
    configInteractionBlocked: false,
  };
  for (const [name, method] of Object.entries(component.methods)) instance[name] = method.bind(instance);
  instance.shouldSubmitTtsLanguage = () => false;
  return { instance, writes, errors };
}

test('imports the full Markdown body beyond 2000 characters and strips only Skill metadata', async () => {
  assert.ok(longPrompt.length > 2000);
  const parsed = await helpers.readPersonaSkill(file('---\r\nname: test-persona\r\ndescription: A test skill\r\n---\r\n' + longPrompt));
  assert.equal(parsed.prompt, longPrompt);
  assert.equal(parsed.strippedFrontmatter, true);
  assert.equal(parsed.bytes, Buffer.byteLength(longPrompt));
  assert.equal(parsed.characters, Array.from(longPrompt).length);
});

test('preserves ordinary Markdown separators and the exact TXT body', async () => {
  const markdown = '---\n普通段落\n---\n正文\n';
  assert.equal((await helpers.readPersonaSkill(file(markdown))).prompt, markdown);
  const text = '  正文 🙂\r\n保留换行和空格。\r\n';
  assert.equal((await helpers.readPersonaSkill(file('\ufeff' + text, 'persona.TXT'))).prompt, text);
});

test('persona JSON takes only systemPrompt, preserving the current models and memory', async () => {
  const parsed = await helpers.readPersonaSkill(file(JSON.stringify({ systemPrompt: longPrompt, llmModelId: 'foreign-model', summaryMemory: 'foreign-memory' }), 'role.json'));
  assert.equal(parsed.prompt, longPrompt);
  assert.equal(parsed.llmModelId, undefined);
  assert.equal(parsed.summaryMemory, undefined);
});

test('rejects raw chat JSON, invalid JSON and wrong field types', async () => {
  for (const text of ['[{}]', '{}', '{', 'null', '{"systemPrompt":123}']) {
    await assert.rejects(helpers.readPersonaSkill(file(text, 'chat.json')), { code: 'invalidJson' });
  }
});

test('enforces the actual UTF-8 TEXT capacity, including Chinese and emoji', async () => {
  const boundary = '中'.repeat(21844) + 'abc';
  assert.equal(Buffer.byteLength(boundary), 65535);
  assert.equal((await helpers.readPersonaSkill(file(boundary))).prompt, boundary);
  assert.equal(helpers.systemPromptProblem(boundary + '🙂'), 'tooLarge');
  await assert.rejects(helpers.readPersonaSkill(file(boundary + '中')), { code: 'tooLarge' });
});

test('rejects invalid UTF-8, NUL, isolated surrogates and empty persona content', async () => {
  await assert.rejects(helpers.readPersonaSkill(file(new Uint8Array([0xff, 0xfe]))), { code: 'invalidEncoding' });
  await assert.rejects(helpers.readPersonaSkill(file('正文\0')), { code: 'invalidText' });
  await assert.rejects(helpers.readPersonaSkill(file('{"systemPrompt":"\\ud800"}', 'role.json')), { code: 'invalidText' });
  for (const text of ['', '  \n', '---\nname: empty\n---\n']) {
    await assert.rejects(helpers.readPersonaSkill(file(text)), { code: 'empty' });
  }
});

test('rejects large text files before reading and unsupported archive types', async () => {
  let readAttempted = false;
  await assert.rejects(helpers.readPersonaSkill({ name: 'large.md', size: 262145, arrayBuffer: () => { readAttempted = true; } }), { code: 'fileTooLarge' });
  assert.equal(readAttempted, false);
  for (const name of ['persona.7z', 'persona.rar', 'persona.tar.gz', 'script.js']) {
    await assert.rejects(helpers.readPersonaSkill(file('content', name)), { code: 'unsupportedFile' });
  }
});

test('ZIP prefers the prepared runtime text and verifies matching JSON without duplicating source copies', async () => {
  const parsed = await helpers.readPersonaSkill(zipped({
    '角色/full-system-prompt.txt': longPrompt,
    '角色/agent-patch.json': JSON.stringify({ systemPrompt: longPrompt, llmModelId: 'foreign' }),
    '角色/source/SKILL.md': 'original source version',
    '角色/source/persona.md': 'original persona copy',
    '角色/README.md': 'not part of the persona',
    '角色/tools/import.py': 'must never execute',
  }));
  assert.equal(parsed.prompt, longPrompt);
  assert.equal(parsed.archive, true);
  assert.equal(parsed.strategy, 'prepared');
  assert.deepEqual(parsed.usedFiles, ['角色/full-system-prompt.txt']);
  assert.deepEqual(parsed.verifiedFiles, ['角色/agent-patch.json']);
  assert.equal(parsed.ignoredFiles, 4);
  assert.equal(parsed.llmModelId, undefined);
});

test('ZIP reads a JSON-only persona without applying other configuration', async () => {
  const parsed = await helpers.readPersonaSkill(zipped({ 'agent-patch.json': JSON.stringify({ systemPrompt: longPrompt, summaryMemory: 'foreign' }) }));
  assert.equal(parsed.prompt, longPrompt);
  assert.equal(parsed.summaryMemory, undefined);
  assert.deepEqual(parsed.usedFiles, ['agent-patch.json']);
});

test('.skill packages combine SKILL.md with separate persona and memories from the same directory', async () => {
  const parsed = await helpers.readPersonaSkill(zipped({
    'persona/SKILL.md': '---\nname: test\n---\n请根据下列档案回应。',
    'persona/persona.md': '# 人格\n先接话，再简短追问。',
    'persona/memories.md': '# 共同记忆\n对方的工作是前端开发。',
    'persona/knowledge/chats.json': '[{"raw":"archive"}]',
  }, 'persona.skill'));
  assert.match(parsed.prompt, /请根据下列档案回应/);
  assert.match(parsed.prompt, /先接话，再简短追问/);
  assert.match(parsed.prompt, /对方的工作是前端开发/);
  assert.equal(parsed.strippedFrontmatter, true);
  assert.deepEqual(parsed.usedFiles, ['persona/SKILL.md', 'persona/persona.md', 'persona/memories.md']);
  assert.equal(parsed.ignoredFiles, 1);
  assert.doesNotMatch(parsed.prompt, /raw|archive/);
});

test('companions already inside SKILL.md are reported rather than inserted twice', async () => {
  const persona = '# 人格\n保持自然表达。', memory = '# 记忆\n一起聊过晚餐。';
  const body = persona + '\n\n' + memory;
  const parsed = await helpers.readPersonaSkill(zipped({ 'SKILL.md': body, 'persona.md': persona, 'memories.md': memory }));
  assert.equal(parsed.prompt, body);
  assert.deepEqual(parsed.usedFiles, ['SKILL.md']);
  assert.deepEqual(parsed.alreadyIncludedFiles, ['persona.md', 'memories.md']);
});

test('compiled TXT and JSON with different versions cannot be silently selected', async () => {
  await assert.rejects(helpers.readPersonaSkill(zipped({ 'full-system-prompt.txt': longPrompt, 'agent-patch.json': JSON.stringify({ systemPrompt: 'different' }) })), { code: 'conflictingPrompts' });
});

test('multiple independent personas or a package without an entry point are rejected', async () => {
  await assert.rejects(helpers.readPersonaSkill(zipped({ 'one/SKILL.md': 'one', 'two/SKILL.md': 'two' })), { code: 'multiplePersonas' });
  await assert.rejects(helpers.readPersonaSkill(zipped({ 'README.md': 'instructions', 'persona.md': 'no entry' })), { code: 'missingSkill' });
});

test('nested backups and macOS metadata do not replace the selected persona', async () => {
  const parsed = await helpers.readPersonaSkill(zipped({
    'SKILL.md': longPrompt, 'versions/old/SKILL.md': 'old', '__MACOSX/SKILL.md': 'metadata', '.hidden/SKILL.md': 'hidden',
  }));
  assert.equal(parsed.prompt, longPrompt);
  assert.equal(parsed.ignoredFiles, 3);
});

test('the combined persona must fit the same UTF-8 capacity as a single file', async () => {
  await assert.rejects(helpers.readPersonaSkill(zipped({
    'SKILL.md': '甲'.repeat(12000), 'persona.md': '乙'.repeat(12000),
  })), { code: 'tooLarge' });
});

test('ZIP limits are checked before reading and before expanding oversized entries', async () => {
  let attempted = false;
  await assert.rejects(helpers.readPersonaSkill({ name: 'large.zip', size: 8 * 1024 * 1024 + 1, arrayBuffer: () => { attempted = true; } }), { code: 'archiveTooLarge' });
  assert.equal(attempted, false);
  await assert.rejects(helpers.readPersonaSkill(zipped(Object.fromEntries(Array.from({ length: 257 }, (_, index) => [`${index}.txt`, 'small'])))), { code: 'archiveTooLarge' });
  await assert.rejects(helpers.readPersonaSkill(zipped({ 'SKILL.md': 'x'.repeat(262145) })), { code: 'fileTooLarge' });
  await assert.rejects(helpers.readPersonaSkill(zipped({ 'SKILL.md': 'small', 'raw.bin': new Uint8Array(16 * 1024 * 1024) })), { code: 'archiveTooLarge' });
});

test('ZIP rejects unsafe paths, case collisions and symbolic links without extracting anything', async () => {
  for (const name of ['../SKILL.md', '/SKILL.md', 'C:/SKILL.md', 'a/../SKILL.md']) {
    await assert.rejects(helpers.readPersonaSkill(zipped({ [name]: 'text' })), { code: 'invalidArchive' });
  }
  await assert.rejects(helpers.readPersonaSkill(zipped({ 'SKILL.md': 'text', 'skill.md': 'other' })), { code: 'invalidArchive' });
  const link = zipSync({ 'SKILL.md': [strToU8('outside.md'), { os: 3, attrs: 0xa1ff << 16 }] });
  await assert.rejects(helpers.readPersonaSkill(file(link, 'link.zip')), { code: 'unsupportedArchive' });
});

test('CRC damage and truncated archives are rejected instead of importing altered text', async () => {
  const bytes = zipSync({ 'SKILL.md': strToU8('original plain text') }, { level: 0 });
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const dataAt = 30 + view.getUint16(26, true) + view.getUint16(28, true);
  bytes[dataAt] ^= 1;
  await assert.rejects(helpers.readPersonaSkill(file(bytes, 'damaged.zip')), { code: 'invalidArchive' });
  await assert.rejects(helpers.readPersonaSkill(file(bytes.subarray(0, bytes.length - 15), 'truncated.zip')), { code: 'invalidArchive' });
});

test('forged declared size is bounded by actual streaming output', async () => {
  const bytes = zipSync({ 'SKILL.md': strToU8('x'.repeat(1024 * 1024)) });
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const end = bytes.length - 22;
  const central = view.getUint32(end + 16, true);
  view.setUint32(central + 24, 10, true);
  view.setUint32(22, 10, true);
  await assert.rejects(helpers.readPersonaSkill(file(bytes, 'forged.zip')), { code: 'fileTooLarge' });
});

test('selection previews without mutating the role; confirmation emits exactly the full prompt', async () => {
  const { instance, events, successes } = importer();
  await instance.selectFile({ target: { files: [file(longPrompt)], value: 'chosen-file' } });
  assert.equal(instance.preview.prompt, longPrompt);
  assert.equal(instance.previewVisible, true);
  assert.equal(instance.value, '原来的角色');
  assert.equal(events.length, 0);
  instance.applyPreview();
  assert.deepEqual(events, [['input', longPrompt]]);
  assert.equal(instance.previewVisible, false);
  assert.equal(successes.length, 1);
});

test('cancelling a preview or disabling the page leaves the current role intact', async () => {
  const { component, instance, events } = importer();
  await instance.selectFile({ target: { files: [file(longPrompt)], value: '' } });
  instance.cancelPreview();
  assert.equal(events.length, 0);
  await instance.selectFile({ target: { files: [file(longPrompt)], value: '' } });
  instance.disabled = true;
  component.watch.disabled.call(instance, true);
  instance.applyPreview();
  assert.equal(events.length, 0);
});

test('late file reads cannot reopen a cancelled or destroyed importer', async () => {
  for (const stop of ['cancel', 'destroy']) {
    const { component, instance, events } = importer();
    let finish;
    const pending = instance.selectFile({ target: { files: [{ name: 'SKILL.md', size: 10, arrayBuffer: () => new Promise((resolve) => { finish = resolve; }) }], value: '' } });
    if (stop === 'cancel') instance.cancelPreview();
    else component.beforeDestroy.call(instance);
    finish(new TextEncoder().encode('完整正文').buffer);
    await pending;
    assert.equal(instance.previewVisible, false);
    assert.equal(events.length, 0);
  }
});

test('file errors leave the current role untouched without exposing uploaded content', async () => {
  const { instance, events, errors } = importer();
  await instance.selectFile({ target: { files: [file('[{"private":"private-test-text"}]', 'chat.json')], value: '' } });
  assert.equal(instance.previewVisible, false);
  assert.equal(events.length, 0);
  assert.deepEqual(errors, ['personaSkill.errors.invalidJson']);
  assert.equal(instance.reading, false);
});

test('the existing save flow sends the full persona with the unchanged memory and model bindings', async () => {
  const { instance, writes } = rolePage();
  instance.form.systemPrompt = longPrompt;
  instance.form.summaryMemory = '当前记忆';
  instance.form.model.llmModelId = 'current-model';
  instance.form.model.memModelId = 'Memory_mem_local_short';
  instance.form.ttsVoiceId = 'current-voice';
  await instance.saveConfig();
  assert.equal(writes.length, 1);
  assert.equal(writes[0].id, 'local-agent');
  assert.equal(writes[0].body.systemPrompt, longPrompt);
  assert.equal(writes[0].body.summaryMemory, '当前记忆');
  assert.equal(writes[0].body.llmModelId, 'current-model');
  assert.equal(writes[0].body.memModelId, 'Memory_mem_local_short');
  assert.equal(instance.form.ttsVoiceId, 'current-voice');
  assert.equal(writes[0].body.ttsVoiceId, undefined);
});

test('manual edits beyond capacity are blocked before calling the save API', async () => {
  const { instance, writes, errors } = rolePage();
  instance.form.systemPrompt = '中'.repeat(21846);
  await instance.saveConfig();
  assert.equal(writes.length, 0);
  assert.deepEqual(errors, ['personaSkill.errors.tooLarge']);
});

test('existing roles with an unset optional prompt can still save other configuration', async () => {
  const { instance, writes } = rolePage();
  instance.form.systemPrompt = null;
  await instance.saveConfig();
  assert.equal(writes.length, 1);
  assert.equal(writes[0].body.systemPrompt, null);
  assert.equal(helpers.systemPromptProblem('', false), 'empty');
  assert.equal(helpers.systemPromptProblem(null, false), 'invalidText');
});

test('upload and role templates compile and the persona textarea has no 2000-character cap', () => {
  for (const source of [componentSource, pageSource]) {
    assert.deepEqual(compiler.compile(compiler.parseComponent(source).template.content).errors, []);
  }
  const input = /<el-input\b[^>]*v-model="form.systemPrompt"[^>]*\/>/.exec(pageSource)?.[0];
  assert.ok(input);
  assert.doesNotMatch(input, /maxlength/);
  assert.match(pageSource, /<persona-skill-import[\s\S]*?v-model="form.systemPrompt"/);
});

test('every supported locale supplies all upload and validation messages', () => {
  const keys = (object) => Object.entries(object).flatMap(([key, value]) => typeof value === 'object' ? keys(value).map((child) => `${key}.${child}`) : key).sort();
  for (const locale of ['zh_CN', 'zh_TW', 'en', 'de', 'vi', 'pt_BR']) {
    assert.deepEqual(keys(messages[locale]), keys(messages.zh_CN));
  }
});
