import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const digitalRoot = new URL('../../digital-human/js/', import.meta.url);

async function loadClass(path, name, globals) {
  const source = (await readFile(new URL(path, digitalRoot), 'utf8'))
    .replace(/^import .*;\r?$/gm, '')
    .replace(/^export \{[^}]*\};\r?$/gm, '')
    .replace(/^export /gm, '');
  const context = vm.createContext({ ...globals, setTimeout, clearTimeout, setInterval, clearInterval });
  vm.runInContext(`${source}\nglobalThis.Subject = ${name};`, context, { filename: path });
  return context.Subject;
}

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

async function recorderHarness(t, { worklet = false, acknowledge = true } = {}) {
  const tracks = [];
  const sent = [];
  const encoded = [];
  const nodes = [];
  const worklets = [];
  let loads = 0;
  const node = () => {
    const result = { connected: true, connect() {}, disconnect() { this.connected = false; } };
    nodes.push(result);
    return result;
  };
  const createStream = () => {
    const track = { readyState: 'live', stop() { this.readyState = 'ended'; } };
    tracks.push(track);
    return { getTracks: () => [track] };
  };
  const mediaDevices = { getUserMedia: async () => createStream() };
  const context = {
    state: 'running', destination: {},
    createMediaStreamSource: node,
    createAnalyser: () => ({ ...node(), frequencyBinCount: 16 }),
    createGain: () => ({ ...node(), gain: { value: 1 } }),
    createScriptProcessor: node,
  };
  if (worklet) context.audioWorklet = { addModule: async () => { loads++; } };
  class WorkletNode {
    constructor() {
      Object.assign(this, node());
      this.tail = new Int16Array();
      this.port = {
        onmessage: null, close() {},
        postMessage: ({ command }) => {
          if (command === 'stop' && acknowledge) queueMicrotask(() => {
            this.port.onmessage?.({ data: { type: 'buffer', buffer: this.tail } });
            this.port.onmessage?.({ data: { type: 'status', status: 'stopped' } });
          });
        },
      };
      worklets.push(this);
    }
  }
  const Recorder = await loadClass('core/audio/recorder.js', 'AudioRecorder', {
    log() {}, navigator: { mediaDevices }, WebSocket: { OPEN: 1 },
    Blob, URL, AudioWorkletNode: WorkletNode,
    getAudioPlayer: () => ({ getAudioContext: () => context }),
    initOpusEncoder: () => ({ encode(pcm) {
      encoded.push(Array.from(pcm));
      // A view must transmit only its own bytes, not the surrounding allocation.
      return new Uint8Array([99, 1, 2, 88]).subarray(1, 3);
    } }),
    cancelAnimationFrame() {},
  });
  const recorder = new Recorder();
  const websocket = { readyState: 1, send(value) {
    sent.push(typeof value === 'string' ? JSON.parse(value) : Array.from(value));
  } };
  recorder.setWebSocket(websocket);
  t.after(async () => { await recorder.stop(); });
  return { recorder, websocket, sent, encoded, tracks, nodes, worklets, context,
    mediaDevices, createStream, get loads() { return loads; } };
}

test('recording sends listen start, padded final audio, then listen stop and releases capture', async t => {
  const h = await recorderHarness(t);
  assert.equal(await h.recorder.start(), true);
  h.recorder.processPCMBuffer(new Int16Array([123, 456]));
  assert.equal(await h.recorder.stop(), true);
  assert.deepEqual(h.sent, [{ type: 'listen', state: 'start', mode: 'auto' }, [1, 2],
    { type: 'listen', state: 'stop' }]);
  assert.deepEqual(h.encoded[0].slice(0, 3), [123, 456, 0]);
  assert.equal(h.encoded[0].length, 960);
  assert.ok(h.tracks.every(track => track.readyState === 'ended'));
  assert.equal(h.recorder.mediaStream, null);
  assert.equal(h.recorder.recordingTimer, null);
  assert.equal(h.recorder.isRecording, false);
});

test('worklet tail is flushed before the protocol stop and the module is reused on restart', async t => {
  const h = await recorderHarness(t, { worklet: true });
  for (let index = 0; index < 2; index++) {
    assert.equal(await h.recorder.start(), true);
    h.worklets[index].tail = new Int16Array([321, 654]);
    await h.recorder.stop();
  }
  assert.equal(h.loads, 1);
  assert.deepEqual(h.sent.map(item => item.type || 'audio'),
    ['listen', 'audio', 'listen', 'listen', 'audio', 'listen']);
  assert.deepEqual(h.encoded.map(pcm => pcm.slice(0, 3)), [[321, 654, 0], [321, 654, 0]]);
  assert.ok(h.tracks.every(track => track.readyState === 'ended'));
});

test('concurrent stop calls send one stop message', async t => {
  const h = await recorderHarness(t, { worklet: true });
  await h.recorder.start();
  const first = h.recorder.stop();
  assert.equal(h.recorder.stop(), first);
  assert.equal(await h.recorder.start(), false);
  await first;
  assert.equal(h.sent.filter(item => item.state === 'stop').length, 1);
});

test('a nonresponding worklet still releases the microphone', async t => {
  const h = await recorderHarness(t, { worklet: true, acknowledge: false });
  await h.recorder.start();
  await h.recorder.stop();
  assert.equal(h.tracks[0].readyState, 'ended');
  assert.equal(h.sent.at(-1).state, 'stop');
});

test('disconnected sockets never request microphone access', async t => {
  const h = await recorderHarness(t);
  h.websocket.readyState = 3;
  assert.equal(await h.recorder.start(), false);
  assert.equal(h.tracks.length, 0);
});

test('permission denial leaves recording idle', async t => {
  const h = await recorderHarness(t);
  h.mediaDevices.getUserMedia = async () => { throw new Error('permission denied'); };
  assert.equal(await h.recorder.start(), false);
  assert.equal(h.recorder.isStarting, false);
  assert.equal(h.recorder.isRecording, false);
  assert.equal(h.sent.length, 0);
});

test('stop during a pending permission request releases the late stream', async t => {
  const h = await recorderHarness(t);
  const permission = deferred();
  h.mediaDevices.getUserMedia = () => permission.promise;
  const start = h.recorder.start();
  assert.equal(await h.recorder.start(), false);
  await h.recorder.stop();
  permission.resolve(h.createStream());
  assert.equal(await start, false);
  assert.equal(h.tracks[0].readyState, 'ended');
  assert.equal(h.sent.length, 0);
});

test('disconnect during permission request cannot start capture on the old socket', async t => {
  const h = await recorderHarness(t);
  const permission = deferred();
  h.mediaDevices.getUserMedia = () => permission.promise;
  const start = h.recorder.start();
  h.websocket.readyState = 3;
  permission.resolve(h.createStream());
  assert.equal(await start, false);
  assert.equal(h.tracks[0].readyState, 'ended');
  assert.equal(h.sent.length, 0);
});

test('processor initialization failure releases a previously acquired stream', async t => {
  const h = await recorderHarness(t);
  h.context.createScriptProcessor = () => { throw new Error('audio unavailable'); };
  assert.equal(await h.recorder.start(), false);
  assert.equal(h.tracks[0].readyState, 'ended');
  assert.equal(h.recorder.mediaStream, null);
});

test('stopping during worklet initialization cleans up the late processor', async t => {
  const h = await recorderHarness(t, { worklet: true });
  const loaded = deferred();
  const entered = deferred();
  h.context.audioWorklet.addModule = () => { entered.resolve(); return loaded.promise; };
  const start = h.recorder.start();
  await entered.promise;
  await h.recorder.stop();
  loaded.resolve();
  assert.equal(await start, false);
  assert.equal(h.tracks[0].readyState, 'ended');
  assert.equal(h.worklets[0].connected, false);
});

test('closed or replaced sockets cannot receive late audio from an earlier recording', async t => {
  const h = await recorderHarness(t, { worklet: true });
  await h.recorder.start();
  h.worklets[0].tail = new Int16Array([123]);
  const newMessages = [];
  h.websocket.readyState = 3;
  h.recorder.setWebSocket({ readyState: 1, send: value => newMessages.push(value) });
  await h.recorder.stop();
  assert.equal(newMessages.length, 0);
  assert.equal(h.tracks[0].readyState, 'ended');
});

test('a failed stop send still releases capture and clears recording state', async t => {
  const h = await recorderHarness(t);
  await h.recorder.start();
  h.websocket.send = () => { throw new Error('connection lost'); };
  assert.equal(await h.recorder.stop(), false);
  assert.equal(h.tracks[0].readyState, 'ended');
  assert.equal(h.recorder.isStopping, false);
});

test('chat renders user and model markup as literal text', async () => {
  const added = [];
  const element = () => ({ children: [], appendChild(child) { this.children.push(child); },
    set innerHTML(_) { throw new Error('chat must not parse HTML'); } });
  const Controller = await loadClass('ui/controller.js', 'UIController', {
    localStorage: { getItem: () => null },
    document: { createElement: element,
      getElementById: () => ({ appendChild: child => added.push(child) }) },
  });
  const controller = new Controller();
  const text = '<img src=x onerror="globalThis.injected=true"> & <b>hello</b>';
  for (const isUser of [true, false]) controller.addChatMessage(text, isUser);
  assert.deepEqual(added.map(message => message.children[0].textContent), [text, text]);
  assert.deepEqual(added.map(message => message.className), ['chat-message user', 'chat-message ai']);
});

test('pending microphone permission is not displayed as a microphone failure', async () => {
  const window = {};
  const Controller = await loadClass('ui/controller.js', 'UIController', {
    window, localStorage: { getItem: () => null },
    document: { getElementById: () => null },
  });
  const messages = [];
  const controller = new Controller();
  controller.addChatMessage = message => messages.push(message);
  controller.startAIChatSession();
  assert.equal(messages.length, 1);
  window.microphoneAvailable = false;
  controller.startAIChatSession();
  assert.ok(messages.at(-1).includes('麦克风不可用'));
});
