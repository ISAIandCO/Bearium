// Test the actual privileged page script against isolated browser service fakes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function page(privateMode = false, target = 'https://EXAMPLE.ru/a', report = null) {
  const normal = new Map(), defaults = new Map(), observers = new Map();
  let cancelled = 0, oneShots = 0, navigations = 0;
  function branch(map) {
    return { getStringPref: (k, fallback) => map.get(k) ?? fallback,
      setStringPref: (k, v) => map.set(k, v), getBoolPref: (k, v) => map.get(k) ?? v, setBoolPref: (k, v) => map.set(k, v) };
  }
  function element() {
    return {value: '', hidden: true, textContent: '', children: [], handlers: {}, dataset: {}, options: [{}, {}, {}],
      querySelectorAll() {return this.children.flatMap(s => s.children.flatMap(l => l.children.filter(c => c.type === 'checkbox')));},
      addEventListener(k, fn) {this.handlers[k] = fn;},
      append(...items) {this.children.push(...items);},
      replaceChildren() {this.children = [];}};
  }
  const elements = new Map();
  const get = id => {if (!elements.has(id)) elements.set(id, element()); return elements.get(id);};
  get('scope').value = 'all'; get('duration').value = 'permanent';
  const Services = {prefs: {...branch(normal), getDefaultBranch: () => branch(defaults)},
    io: {newURI(value) {const u = new URL(value);return {scheme:u.protocol.slice(0,-1),
      userPass:u.username || u.password, asciiHost:u.hostname, spec:u.href};}},
    obs: {addObserver: (fn, topic) => observers.set(topic, fn),
      removeObserver: (_, topic) => observers.delete(topic),
      notifyObservers: (_, topic) => {if (topic === 'net:cancel-all-connections') cancelled++;}}};
  vm.runInNewContext(fs.readFileSync('native/rufoxProtection.js','utf8'), {
    ChromeUtils: {importESModule: () => ({PrivateBrowsingUtils: {isContentWindowPrivate: () => privateMode}, RufoxProtection: {armOneShot() {oneShots++;}, cancelOneShot() {}, snapshot: () => report || ({available:true, total:0, blocked:0, domains:[]})}})},
    RufoxLogMetadata: {version:'test',timestamp:'2026-01-01',logs:{}},
    setInterval: () => 1, clearInterval() {},
    Services, window: {addEventListener() {}, browsingContext: {top: {embedderElement:{}}}}, URL, URLSearchParams, location: {hash:'#'+(report?'warning=1&':'')+'url='+encodeURIComponent(target),replace() {navigations++;}},
    document: {documentURI:"about:bearium-protection#"+(report?"warning=1&":"")+"url="+encodeURIComponent(target), getElementById:get, createElement:element, createTextNode:v=>v},
  });
  return {get, normal, defaults, observers, cancelled:()=>cancelled, oneShots:()=>oneShots, navigations:()=>navigations,
    click(trusted=true) {get('allow').handlers.click({isTrusted:trusted});}};
}
const p = page();
p.get('open-once').handlers.click({isTrusted:false});assert.equal(p.oneShots(),0);
p.get('open-once').handlers.click({isTrusted:true});assert.equal(p.oneShots(),1);
assert.equal(p.navigations(),1);assert.equal(p.normal.size,0);assert.equal(p.defaults.size,0);
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
p.get('exceptions').children[0].children[0].handlers.click({isTrusted:true});
assert.equal(p.normal.get('security.rufox.exceptions'), 'other.com|all');
const session = page(); session.get('duration').value = 'session'; session.click();
assert.equal(session.normal.size, 0);
assert.equal(session.defaults.get('security.rufox.session_exceptions'), 'example.ru|all');
const priv = page(true); priv.click();
assert.equal(priv.normal.size, 0, 'private permissions never reach persisted user prefs');
assert.equal(priv.defaults.get('security.rufox.private_exceptions'), 'example.ru|all');
// Last-private-context cleanup is owned by the GeckoView service, not the page.
const malicious = page(false, 'javascript:alert(1)');
assert.equal(malicious.get('return').hidden, true);
console.log('Native policy UI checks passed');

const warning = page(false, 'https://blocked.com/', {
  available:true, url:'https://blocked.com/', total:1, blocked:1, blockedDomains:1, domains:[],
  mainReport:{state:'blocked',zoneAllowed:false,zoneException:false},
});
assert.equal(warning.get('warning-actions').hidden,false);
assert.match(warning.get('reason').textContent,/не относится к российским доменам/);
assert.match(warning.get('warning-detail').textContent,/вне разрешённых зон/);
assert.equal(warning.get('management').hidden,true);
assert.equal(warning.get('page-state').hidden,true);
assert.equal(warning.get('manage').href,'about:bearium-protection#url=https%3A%2F%2Fblocked.com%2F');
assert.equal(p.get('management').hidden,false);
assert.equal(p.get('page-state').hidden,false);
assert.match(warning.get('page-state').textContent,/Заблокировано запросов: 1. Доменов: 1/);
warning.get('allow-domain').handlers.click({isTrusted:false});
assert.equal(warning.normal.size,0);
warning.get('allow-domain').handlers.click({isTrusted:true});
assert.equal(warning.normal.get('security.rufox.exceptions'),'blocked.com|all');
warning.get('continue').handlers.click({isTrusted:true});
assert.equal(warning.oneShots(),1);

const privateWarning = page(true, 'https://blocked.com/', {
  available:true, url:'https://blocked.com/', domains:[],
  mainReport:{state:'blocked',zoneAllowed:true,ctReason:'missing-yandex'},
});
assert.match(privateWarning.get('reason').textContent,/не прошёл дополнительную проверку/);
assert.match(privateWarning.get('warning-lifetime').textContent,/до закрытия всех приватных вкладок/);
privateWarning.get('allow-domain').handlers.click({isTrusted:true});
assert.equal(privateWarning.normal.size,0);
assert.equal(privateWarning.defaults.get('security.rufox.private_exceptions'),'blocked.com|all');
const staleWarning = page(false, 'https://blocked.com/', {
  available:true, url:'https://other.com/', domains:[], mainReport:{state:'blocked'},
});
assert.equal(staleWarning.get('warning-actions').hidden,true);
staleWarning.get('allow-domain').handlers.click({isTrusted:true});
assert.equal(staleWarning.normal.size,0);
