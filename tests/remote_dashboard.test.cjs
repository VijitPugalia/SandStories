const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
function consoleApp() {
  const elements = new Map();
  const get = selector => {
    if (!elements.has(selector)) elements.set(selector, { textContent: '', innerHTML: '', value: '', addEventListener(){}, appendChild(){} });
    return elements.get(selector);
  };
  let socket;
  const context = vm.createContext({
    URLSearchParams, Date, Math, JSON, String, Number,
    location: { search: '', protocol: 'https:', host: 'example.test' },
    localStorage: { getItem(){}, setItem(){} },
    document: { querySelector: get, querySelectorAll: () => [], createElement: () => ({}) },
    fetch: async () => ({ok:true, json:async()=>[]}),
    WebSocket: class { constructor(){ socket = this; } },
    setInterval(){}, setTimeout(){}, window: {},
  });
  vm.runInContext(fs.readFileSync('server/static/dashboard.js','utf8'), context);
  vm.runInContext("selectedDeviceId = 'phone'", context);
  return { get, socket, context };
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
