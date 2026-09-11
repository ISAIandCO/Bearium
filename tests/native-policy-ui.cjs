// Test the actual privileged page script against isolated browser service fakes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function page(privateMode = false, target = 'https://EXAMPLE.ru/a') {
  const normal = new Map(), defaults = new Map(), observers = new Map();
  let cancelled = 0;
  function branch(map) {
    return { getStringPref: (k, fallback) => map.get(k) ?? fallback,
      setStringPref: (k, v) => map.set(k, v) };
  }
  function element() {
    return {value: '', hidden: true, textContent: '', children: [], handlers: {},
      addEventListener(k, fn) {this.handlers[k] = fn;},
      append(...items) {this.children.push(...items);},
      replaceChildren() {this.children = [];}};
  }
  const elements = new Map();
  const get = id => {if (!elements.has(id)) elements.set(id, element()); return elements.get(id);};
  get('scope').value = 'all';
  const Services = {prefs: {...branch(normal), getDefaultBranch: () => branch(defaults)},
    io: {newURI(value) {const u = new URL(value);return {scheme:u.protocol.slice(0,-1),
      userPass:u.username || u.password, asciiHost:u.hostname, spec:u.href};}},
    obs: {addObserver: (fn, topic) => observers.set(topic, fn),
      removeObserver: (_, topic) => observers.delete(topic),
      notifyObservers: (_, topic) => {if (topic === 'net:cancel-all-connections') cancelled++;}}};
  vm.runInNewContext(fs.readFileSync('native/rufoxProtection.js','utf8'), {
    ChromeUtils: {importESModule: () => ({PrivateBrowsingUtils: {isContentWindowPrivate: () => privateMode}})},
    Services, window: {}, URLSearchParams, location: {hash:'#url='+encodeURIComponent(target)},
    document: {getElementById:get, createElement:element, createTextNode:v=>v},
  });
  return {get, normal, defaults, observers, cancelled:()=>cancelled,
    click(trusted=true) {get('allow').handlers.click({isTrusted:trusted});}};
}
const p = page();
assert.equal(p.get('hosts').value, 'example.ru');
p.click(false);
assert.equal(p.normal.size, 0, 'scripted clicks cannot grant permissions');
p.get('hosts').value = 'example.ru\nhttps://other.com/path';
p.click();
assert.equal(p.normal.get('security.rufox.exceptions'), 'example.ru|all,other.com|all');
assert.equal(p.cancelled(), 1);
assert(!p.normal.get('security.rufox.exceptions').includes('*.'));
p.get('hosts').value = 'https://user:password@example.com';
p.click();
assert.equal(p.cancelled(), 1, 'invalid input must not mutate permissions');
p.get('exceptions').children[0].children[1].handlers.click({isTrusted:true});
assert.equal(p.normal.get('security.rufox.exceptions'), 'other.com|all');
const priv = page(true); priv.click();
assert.equal(priv.normal.size, 0, 'private permissions never reach persisted user prefs');
assert.equal(priv.defaults.get('security.rufox.private_exceptions'), 'example.ru|all');
priv.observers.get('last-pb-context-exited')();
assert.equal(priv.defaults.get('security.rufox.private_exceptions'), '');
const malicious = page(false, 'javascript:alert(1)');
assert.equal(malicious.get('return').hidden, true);
console.log('Native policy UI checks passed');
