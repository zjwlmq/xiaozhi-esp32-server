import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import test from 'node:test';

const root = new URL('../../digital-human/js/', import.meta.url);
const source = await readFile(new URL('config/voice-settings.js', root), 'utf8');
const settings = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

test('new and corrupt storage safely follow the agent', () => {
    for (const value of [null, '{bad', 'null', '[]', '{"version":"other","pitch":99,"speed":false}']) {
        assert.deepEqual(settings.getStoredVoiceSettings({getItem: () => value}), settings.DEFAULT_VOICE_SETTINGS);
    }
    assert.deepEqual(settings.getStoredVoiceSettings({getItem() { throw new Error('blocked'); }}), settings.DEFAULT_VOICE_SETTINGS);
});

test('saved supported values survive reload and exclude arbitrary upstream settings', () => {
    const desired = {version: '2.0', generation: 'expressive', speed: 1.3, pitch: -5, language: 'en'};
    assert.deepEqual(settings.getStoredVoiceSettings({getItem: () => JSON.stringify({...desired, api_key:'discard', speaker:'discard'})}), desired);
});

test('generation choices match the selected model capabilities', () => {
    assert.equal(settings.normalizeVoiceSettings({version:'1.0', generation:'restoration'}).generation, 'restoration');
    assert.equal(settings.normalizeVoiceSettings({version:'2.0', generation:'trained'}).generation, 'standard');
    assert.equal(settings.normalizeVoiceSettings({version:'2.0', generation:'restoration'}).generation, 'standard');
});

async function makeWebSocketHandler() {
    let code = await readFile(new URL('core/network/websocket.js', root), 'utf8');
    code = code.replace(/^import .*;\r?\n/gm, '').replace(/export /g, '');
    const context = vm.createContext({WebSocket:{OPEN:1}, log(){}, getStoredVoiceSettings:()=>({...settings.DEFAULT_VOICE_SETTINGS}),
        getConfig:()=>({deviceId:'browser-test'}), setTimeout, clearTimeout,
        window:{}, document:{getElementById:()=>null},
        uiController:{updateDialButton(){},startAIChatSession(){}},
    });
    vm.runInContext(code+'\nthis.Handler = WebSocketHandler;', context);
    const handler = new context.Handler();
    const messages = [];
    handler.websocket = {readyState:1, send:raw=>messages.push(JSON.parse(raw))};
    return {handler, messages};
}

test('voice controls require an acknowledged protocol and send a separate bounded message', async () => {
    const {handler,messages} = await makeWebSocketHandler();
    assert.equal(handler.sendVoiceSettings({version:'2.0'}, 'r1'), false);
    handler.voiceSettingsProtocol = true;
    assert.equal(handler.sendVoiceSettings({version:'2.0',pitch:4,speed:1.2}, 'r1'), true);
    assert.deepEqual(messages, [{type:'voice_settings', request_id:'r1', settings:{version:'2.0',pitch:4,speed:1.2}}]);
    handler.websocket.readyState = 3;
    assert.equal(handler.sendVoiceSettings({}, 'r2'), false);
});

test('voice acknowledgements and errors never become chat messages', async () => {
    const {handler} = await makeWebSocketHandler();
    const results = [], chat = [];
    handler.onVoiceSettingsMessage = value => results.push(value);
    handler.onChatMessage = value => chat.push(value);
    handler.handleTextMessage({type:'voice_settings',status:'accepted',request_id:'r1'});
    handler.handleTextMessage({type:'voice_settings',status:'error',message:'unsupported'});
    assert.equal(results.length, 2);
    assert.equal(chat.length, 0);
});

test('hello advertises support and carries the saved settings before conversation starts', async () => {
    const {handler,messages} = await makeWebSocketHandler();
    handler.websocket.addEventListener = (_event, listener) => queueMicrotask(() => listener({data:JSON.stringify({type:'hello',session_id:'test'})}));
    handler.websocket.removeEventListener = () => {};
    assert.equal(await handler.sendHelloMessage(), true);
    assert.equal(messages[0].features.voice_settings, true);
    assert.deepEqual(messages[0].voice_settings, settings.DEFAULT_VOICE_SETTINGS);
});

async function makePanel() {
    let code = await readFile(new URL('ui/voice-settings.js', root), 'utf8');
    code = code.replace(/^import .*;\r?\n/gm, '').replace(/export /g, '');
    const identity = {textContent:'当前音色 · S_previous'};
    const writes = [];
    const context = vm.createContext({...settings, clearTimeout,
        getStoredVoiceSettings:()=>({...settings.DEFAULT_VOICE_SETTINGS}),
        document:{getElementById:()=>identity}, localStorage:{setItem:(key,value)=>writes.push(JSON.parse(value))},
    });
    vm.runInContext(code+'\nthis.Panel = VoiceSettingsPanel;',context);
    const panel = new context.Panel(()=>({}));
    panel.panel = {};
    panel.status = {textContent:'',dataset:{}};
    panel.render = () => {};
    return {panel,writes,identity};
}

test('hello acknowledgement does not claim an unsaved draft has been applied', async () => {
    const {panel,writes} = await makePanel();
    panel.draft = {...settings.DEFAULT_VOICE_SETTINGS, version:'2.0',pitch:5};
    panel.handleMessage({status:'accepted',supported:true,voice:'S_bound',settings:settings.DEFAULT_VOICE_SETTINGS});
    assert.equal(panel.status.dataset.state,'pending');
    assert.match(panel.status.textContent,/尚未应用/);
    assert.equal(panel.draft.pitch,5);
    assert.deepEqual(writes,[settings.DEFAULT_VOICE_SETTINGS]);
});

test('rejected or stale changes preserve the acknowledged voice and saved preference', async () => {
    const {panel,writes,identity} = await makePanel();
    panel.pending = 'current';
    panel.handleMessage({status:'accepted',request_id:'stale',voice:'S_stale',settings:settings.DEFAULT_VOICE_SETTINGS});
    assert.equal(panel.pending,'current');
    panel.handleMessage({status:'error',request_id:'current',voice:'S_rejected',message:'尚未关联音色'});
    assert.equal(panel.pending,null);
    assert.equal(panel.status.dataset.state,'error');
    assert.equal(identity.textContent,'当前音色 · S_previous');
    assert.deepEqual(writes,[]);
});
