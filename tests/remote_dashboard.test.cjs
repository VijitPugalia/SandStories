const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
function consoleApp() {
  const elements = new Map();
  const get = selector => {
    if (!elements.has(selector)) elements.set(selector, { textContent: '', innerHTML: '', value: '', children: [], addEventListener(){}, appendChild(child){ this.children.push(child); } });
    return elements.get(selector);
  };
  let socket;
  const sockets = [], requests = [], revoked = [];
  const context = vm.createContext({
    URLSearchParams, Date, Math, JSON, String, Number,
    URL: { createObjectURL: () => 'blob:test', revokeObjectURL: url => revoked.push(url) },
    location: { search: '', protocol: 'https:', host: 'example.test' },
    localStorage: { getItem(){}, setItem(){} },
    document: { addEventListener(){}, querySelector: get, querySelectorAll: () => [], createElement: () => ({}) },
    fetch: async path => { requests.push(path); return {ok:true, json:async()=>[]}; },
    WebSocket: class {
      static OPEN = 1;
      constructor(){ socket = this; this.readyState = 1; this.sent = []; sockets.push(this); }
      send(value){ this.sent.push(value); }
      close(){ this.closed = true; }
    },
    setInterval(){}, setTimeout(){}, clearTimeout(){}, window: {},
  });
  vm.runInContext(fs.readFileSync('server/static/dashboard.js','utf8'), context);
  vm.runInContext("selectedDeviceId = 'phone'", context);
  return { get, socket, context, sockets, requests, revoked };
}
test('selected device pause and zero counters render correctly', async () => {
  const { get, socket } = consoleApp();
  await socket.onmessage({data:JSON.stringify({type:'device_message', deviceId:'phone', message:{type:'device_status', recording:true,paused:true,elapsedSeconds:0,savedFrames:0}})});
  assert.equal(get('#capture-state').textContent,'paused');
  assert.equal(get('#elapsed').textContent,'0s');
  assert.equal(get('#frames').textContent,0);
});
test('other devices and command receipts cannot reset the selected recording', async () => {
  const { get, socket } = consoleApp();
  get('#capture-state').textContent='recording';
  for(const [deviceId,message] of [['other',{type:'device_status',recording:false}],['phone',{type:'command_ack',status:'accepted'}],['phone',{type:'command_result',status:'completed'}]]) {
    await socket.onmessage({data:JSON.stringify({type:'device_message',deviceId,message})});
    assert.equal(get('#capture-state').textContent,'recording');
  }
});
test('event log memory stays bounded during long recording', () => {
  const { get, context }=consoleApp();
  vm.runInContext("for(let i=0;i<1000;i++) log('message', {text:'x'.repeat(100)})",context);
  assert.ok(get('#events').textContent.length<=24000);
});

test('Tunnel preview never requests LiveKit and waits for image decode before next frame', async () => {
  const { get, context, sockets, requests } = consoleApp();
  await vm.runInContext('connectPreview()', context);
  const preview = sockets.at(-1);
  preview.onopen();
  assert.deepEqual(preview.sent, ['ready']);
  preview.onmessage({data:{image:true}});
  assert.deepEqual(preview.sent, ['ready']);
  get('#preview').children.at(-1).onload();
  assert.deepEqual(preview.sent, ['ready','ready']);
  assert.equal(get('#preview-status').textContent, 'Console Tunnel live');
  assert.ok(!requests.some(path => path.includes('livekit')));
});
test('disconnect closes preview and stale frames cannot restart it', async () => {
  const { context, sockets, get } = consoleApp();
  await vm.runInContext('connectPreview()', context);
  const preview=sockets.at(-1);
  const oldMessage=preview.onmessage;
  vm.runInContext('disconnectPreview()', context);
  assert.equal(preview.closed,true);
  oldMessage({data:{image:true}});
  assert.equal(get('#preview-status').textContent,'Preview off');
  assert.equal(preview.onclose,null);
});
