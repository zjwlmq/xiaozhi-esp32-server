import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import test from 'node:test';

const require = createRequire(import.meta.url);
const compiler = require('vue-template-compiler');
const read = (path) => readFile(new URL(path, import.meta.url), 'utf8');
const helpersSource = await read('../src/utils/modelCredentials.js');
const helpers = await import(`data:text/javascript;base64,${Buffer.from(helpersSource).toString('base64')}`);
const editSource = await read('../src/components/ModelEditDialog.vue');
const addSource = await read('../src/components/AddModelDialog.vue');
const listSource = await read('../src/views/ModelConfig.vue');
const apiSource = await read('../src/apis/module/model.js');

function loadEditor() {
  const api = { model: {} };
  const script = compiler.parseComponent(editSource).script.content
    .replace(/^import .*;\r?$/gm, '')
    .replace('export default', 'module.exports =');
  const sandbox = { module: { exports: {} }, Api: api, CustomDialog: {}, ...helpers, setTimeout };
  vm.runInNewContext(script, sandbox);
  const component = sandbox.module.exports;
  const errors = [];
  const instance = {
    ...component.data.call({ visible: true }),
    modelData: { id: 'opaque-internal-id', modelName: 'claude_副本' },
    modelType: 'llm',
    $t: (key, params) => `${key}${params ? JSON.stringify(params) : ''}`,
    $set: (object, key, value) => { object[key] = value; },
    $delete: (object, key) => { delete object[key]; },
    $message: { error: (message) => errors.push(message) },
    $emit: () => {},
  };
  for (const [name, method] of Object.entries(component.methods)) instance[name] = method.bind(instance);
  return { instance, api, errors };
}

test('list shows readable names and codes, not the internal ID column', () => {
  assert.match(listSource, /prop="modelName"/);
  assert.match(listSource, /prop="modelCode"/);
  assert.doesNotMatch(listSource, /prop="id"/);
  assert.match(listSource, /editModel\(scope.row\)/);
});

test('API key defaults to plaintext while other password fields retain their controls', () => {
  assert.equal(helpers.apiKeyInputType({ prop: 'api_key', type: 'password' }), 'text');
  assert.equal(helpers.apiKeyInputType({ prop: 'access_key_secret', type: 'password' }), 'password');
  for (const source of [editSource, addSource]) {
    assert.match(source, /:type="apiKeyInputType\(field\)"/);
    assert.match(source, /credentialState\(/);
    assert.match(source, /field\.prop !== 'api_key'/);
  }
});

test('credential status distinguishes empty, example, masked, invalid and merely filled', () => {
  for (const value of ['', null, undefined, '   ']) assert.equal(helpers.credentialState(value), 'empty');
  for (const value of ['你的API密钥', '请输入API Key', 'your_api_key']) {
    assert.equal(helpers.credentialState(value), 'placeholder');
    assert.equal(helpers.normalizeCredential(value), '');
  }
  assert.equal(helpers.credentialState('sk-****abcd'), 'masked');
  assert.equal(helpers.credentialState('sk-key\nvalue'), 'invalid');
  assert.equal(helpers.credentialState('sk-密钥'), 'invalid');
  assert.equal(helpers.credentialState('sk-test-key'), 'filled');
});

test('empty credentials stay empty on blur instead of being replaced with fake keys', () => {
  const { instance } = loadEditor();
  instance.form.configJson = { api_key: '' };
  instance.handleInputBlur('api_key');
  assert.equal(instance.form.configJson.api_key, '');
  assert.doesNotMatch(editSource, /`你的\$\{sensitiveName\}`/);
});

test('loading normalizes old placeholders without changing the model binding or a real key', () => {
  const { instance } = loadEditor();
  instance.dynamicCallInfoFields = [{ prop: 'api_key', type: 'password', defaultValue: '' }];
  const model = { id: 'stable-id', modelName: 'claude_副本', configJson: { api_key: '你的API密钥' } };
  instance.processModelData(model);
  assert.equal(instance.form.id, 'stable-id');
  assert.equal(instance.form.configJson.api_key, '');
  instance.processModelData({ ...model, configJson: { api_key: null } });
  assert.equal(instance.form.configJson.api_key, '');
  instance.processModelData({ ...model, configJson: { api_key: 'sk-actual-test-value' } });
  assert.equal(instance.form.configJson.api_key, 'sk-actual-test-value');
});

test('duplicate reads the masked endpoint and clears credentials, not reusing or inventing keys', () => {
  const { instance, api } = loadEditor();
  instance.modelData.duplicateMode = true;
  instance.modelData.modelCode = 'ClaudeRelay';
  instance.loadProviders = () => {};
  api.model.getModelConfig = (id, done) => done({ data: { code: 0, data: {
    id, configJson: { type: 'anthropic_messages', api_key: 'sk-****masked', access_token: 'to****en' },
  } } });
  api.model.getModelConfigForEdit = () => assert.fail('duplicate must not fetch plaintext');
  instance.loadModelData();
  assert.equal(instance.pendingModelData.configJson.api_key, '');
  assert.equal(instance.pendingModelData.configJson.access_token, '');
});

test('editing uses the dedicated endpoint and a late result cannot refill a closed editor', () => {
  const { instance, api } = loadEditor();
  let reply;
  api.model.getModelConfigForEdit = (id, done) => { reply = done; };
  api.model.getModelConfig = () => assert.fail('editing must fetch the actual API key');
  instance.loadModelData();
  instance.handleClose();
  reply({ data: { code: 0, data: { configJson: { api_key: 'sk-late-test-secret' } } } });
  assert.equal(instance.form.configJson.api_key, undefined);
  assert.equal(instance.pendingModelData, null);
});

test('unloaded editor cannot save and invalid-key validation identifies the model without revealing the key', () => {
  const { instance, errors } = loadEditor();
  assert.equal(instance.validateApiKey(), false);
  instance.modelLoaded = true;
  instance.form = { modelName: 'claude_副本', isEnabled: 1, configJson: { type: 'anthropic_messages', api_key: 'sk-private\nvalue' } };
  assert.equal(instance.validateApiKey(), false);
  assert.match(errors.at(-1), /claude_副本/);
  assert.doesNotMatch(errors.at(-1), /sk-private/);
  instance.form.configJson.api_key = '';
  assert.equal(instance.validateApiKey(), false);
  instance.form.configJson.api_key = 'sk-test-key';
  assert.equal(instance.validateApiKey(), true);
});

test('editor requests stay on manager-api and do not persist plaintext keys', () => {
  assert.match(apiSource, /\/models\/\$\{id\}\/editor/);
  assert.doesNotMatch(editSource + helpersSource, /localStorage|sessionStorage/);
});

test('changed Vue templates compile without template errors', () => {
  for (const [name, source] of [['editor', editSource], ['add', addSource], ['list', listSource]]) {
    const template = compiler.parseComponent(source).template.content;
    const result = compiler.compile(template);
    assert.deepEqual(result.errors, [], `${name} template`);
  }
});
