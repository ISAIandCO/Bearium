// Test the actual privileged page script against isolated browser service fakes.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function page(privateMode = false, target = 'https://EXAMPLE.ru/a', report = null, view = report ? 'warning' : 'settings') {
  const normal = new Map(), defaults = new Map(), observers = new Map();
  let cancelled = 0, oneShots = 0, navigations = 0, reloads = 0;
  const windowHandlers = {};
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
  const ids = new Set([...fs.readFileSync('native/rufoxProtection.html','utf8').matchAll(/id="([^"]+)"/g)].map(m => m[1]));
  const get = id => {assert(ids.has(id), `Missing HTML control: ${id}`); if (!elements.has(id)) elements.set(id, element()); return elements.get(id);};
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
    Services, window: {addEventListener(name, fn) {windowHandlers[name] = fn;}, browsingContext: {top: {embedderElement:{}}}}, URL, URLSearchParams, location: {protocol:'about:', reload() {reloads++;}, hash:'#'+(view === 'warning'?'warning=1&':view === 'settings'?'view=settings&':'')+'url='+encodeURIComponent(target),replace() {navigations++;}},
    document: {documentURI:"about:bearium-protection#"+(view === "warning"?"warning=1&":view === "settings"?"view=settings&":"")+"url="+encodeURIComponent(target), getElementById:get, createElement:element, createTextNode:v=>v},
  });
  return {get, normal, defaults, observers, windowHandlers, reloads:()=>reloads, cancelled:()=>cancelled, oneShots:()=>oneShots, navigations:()=>navigations,
    click(trusted=true) {get('allow').handlers.click({isTrusted:trusted});}};
}
const p = page();
p.get('open-once').handlers.click({isTrusted:false});assert.equal(p.oneShots(),0);
p.get('open-once').handlers.click({isTrusted:true});assert.equal(p.oneShots(),1);
assert.equal(p.navigations(),1);assert.equal(p.normal.size,0);assert.equal(p.defaults.size,0);
assert.equal(p.get('hosts').value, '');
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
const session = page(); session.get('hosts').value = 'example.ru'; session.get('duration').value = 'session'; session.click();
assert.equal(session.normal.size, 0);
assert.equal(session.defaults.get('security.rufox.session_exceptions'), 'example.ru|all');
const priv = page(true); priv.get('hosts').value = 'example.ru'; priv.click();
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
assert.equal(warning.get('page-controls').hidden,true);
assert.equal(warning.get('permission-controls').hidden,false);
assert.equal(warning.get('warning-certificate').hidden,false);
assert.equal(warning.get('manage').href,'about:bearium-protection#view=settings&url=https%3A%2F%2Fblocked.com%2F');
assert.equal(p.get('management').hidden,false);
assert.equal(p.get('page-controls').hidden,true);
assert.equal(p.get('manual-entry').hidden,false);
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
assert.match(privateWarning.get('privacy').textContent,/до закрытия всех приватных вкладок/);
privateWarning.get('allow-domain').handlers.click({isTrusted:true});
assert.equal(privateWarning.normal.size,0);
assert.equal(privateWarning.defaults.get('security.rufox.private_exceptions'),'blocked.com|all');
const staleWarning = page(false, 'https://blocked.com/', {
  available:true, url:'https://other.com/', domains:[], mainReport:{state:'blocked'},
});
assert.equal(staleWarning.get('warning-actions').hidden,true);
staleWarning.get('allow-domain').handlers.click({isTrusted:true});
assert.equal(staleWarning.normal.size,0);

// Warning controls use the visible scope/duration without leaving the warning.
const customWarning = page(false, 'https://blocked.com/', {
  available:true, url:'https://blocked.com/', domains:[],
  mainReport:{state:'blocked',zoneAllowed:false,certificate:{subjectName:'CN=<script>not markup</script>',sha256Fingerprint:'AA:BB'}},
});
customWarning.get('scope').value = 'zone';
customWarning.get('duration').value = 'hour';
customWarning.get('allow-domain').handlers.click({isTrusted:true});
assert.match(customWarning.normal.get('security.rufox.exceptions'), /^blocked.com\|zone\|[0-9]+$/);
assert.equal(customWarning.navigations(),1,'warning permission always returns to the site');
const certificateValues = customWarning.get('certificate-fields').children[0].children.map(c => c.textContent);
assert(certificateValues.includes('CN=<script>not markup</script>'));
assert(certificateValues.includes('AA:BB'));
assert(staleWarning.get('permission-controls').hidden);

// The page screen selects blocked hosts only, with no hidden manual additions.
const tab = page(false, 'https://example.ru/', {
  available:true, domains:[
    {host:'a.com',blocked:1,count:1,reports:[{state:'blocked',zoneAllowed:false}]},
    {host:'b.com',blocked:2,count:2,reports:[{state:'blocked',zoneAllowed:false}]},
    {host:'example.ru',blocked:0,count:1,reports:[{state:'allowed',zoneAllowed:true}]},
  ],
}, 'page');
assert.equal(tab.get('management').hidden,true);
assert.equal(tab.get('page-controls').hidden,false);
assert.equal(tab.get('manual-entry').hidden,true);
assert.equal(tab.get('allow').disabled,true);
assert.equal(tab.get('domains').querySelectorAll('input').length,2);
tab.get('select-blocked').checked = true;
tab.get('select-blocked').handlers.change({isTrusted:true});
assert.equal(tab.get('allow').disabled,false);
assert.match(tab.get('allow').textContent,/\(2\)/);
tab.get('select-blocked').checked = false;
tab.get('select-blocked').handlers.change({isTrusted:true});
assert.equal(tab.get('allow').disabled,true);
const checkbox = tab.get('domains').querySelectorAll('input')[0];
checkbox.checked = true; checkbox.handlers.change({isTrusted:true});
assert.equal(tab.get('select-blocked').indeterminate,true);
tab.get('hosts').value='hidden.com';
tab.get('scope').value='ct';
tab.click();
assert.equal(tab.normal.get('security.rufox.exceptions'),'a.com|ct');

tab.windowHandlers.hashchange();
assert.equal(tab.reloads(),1,'fragment links must initialize the destination view');
