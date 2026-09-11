// Exercise the real parent-process collector with isolated Gecko services.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const contexts = new Map(), observers = new Map(), timers = new Map();
const normal = new Map(), memory = new Map();
let clock = 100_000, timerId = 0, closedConnections = 0;
const preferenceObservers = [];
function prefBranch(values) {
  return {
    getStringPref: (key, fallback) => values.get(key) ?? fallback,
    setStringPref(key, value) {
      values.set(key, value);
      preferenceObservers.forEach(o => o.observe(null, 'nsPref:changed', key));
    },
  };
}
const Services = {
  prefs: { ...prefBranch(normal), getDefaultBranch: () => prefBranch(memory),
    addObserver(_prefix, observer) { preferenceObservers.push(observer); } },
  obs: {
    addObserver(observer, topic) { if (!observers.has(topic)) observers.set(topic, new Set()); observers.get(topic).add(observer); },
    removeObserver(observer, topic) { observers.get(topic)?.delete(observer); },
    notifyObservers(subject, topic) {
      if (topic === 'net:cancel-all-connections') closedConnections++;
      for (const observer of observers.get(topic) || []) observer.observe(subject, topic);
    },
  },
};
const context = { Services, BrowsingContext: { get: id => contexts.get(id) },
  Ci: { nsIWebProgressListener: { STATE_START:1, STATE_STOP:2, STATE_IS_NETWORK:4 },
    nsIHttpChannel:{}, nsIChannel:{}, nsITransportSecurityInfo:{} },
  Date: class extends Date { static now() { return clock; } },
  setTimeout: (fn, delay) => { const id=++timerId; timers.set(id,{fn,at:clock+delay}); return id; },
  clearTimeout: id => timers.delete(id),
};
const source = fs.readFileSync('native/RufoxProtection.sys.mjs', 'utf8')
  .replace(/^import .*Timer\.sys\.mjs";\n/m, '')
  .replace('export const RufoxProtection =', 'globalThis.RufoxProtection =');
vm.runInNewContext(source, context);
const service = context.RufoxProtection;
const a={}, b={};
contexts.set(1, {top:{embedderElement:a}}); contexts.set(2, {top:{embedderElement:b}});
service.attach(a); service.attach(b);
function channel(id, host='example.ru', state='blocked') {
  return {loadInfo:{browsingContextID:id}, QueryInterface(){return this;},
    URI:{asciiHost:host,spec:`https://${host}/`,schemeIs:s=>s==='https'},
    securityInfo:{QueryInterface(){return this;},rufoxPolicy:JSON.stringify({version:1,state,scts:[]})}};
}
function begin(browser, request) {service.progress(browser,{isTopLevel:true},request,5);}
function response(request) {Services.obs.notifyObservers(request,'http-on-examine-response');}
const first=channel(1); begin(a,first); response(first); response(first);
service.progress(a,{isTopLevel:true},first,2);
assert.equal(service.snapshot(a).blocked,1,'one request must not count twice');
assert.equal(service.snapshot(b).total,0,'tabs are isolated');
const late=channel(1,'late.ru');Services.obs.notifyObservers(late,'http-on-modify-request');
const next=channel(1,'new.ru','allowed');begin(a,next);response(next);response(late);
assert.equal(service.snapshot(a).total,1,'old responses cannot populate a new navigation');
assert.equal(service.snapshot(a).state,'allowed');
for(let i=0;i<105;i++) {const r=channel(1);Services.obs.notifyObservers(r,'http-on-modify-request');response(r);}
assert.equal(service.snapshot(a).badge,'99+');
assert.equal(service.snapshot(a).blocked,105);
const unrelated=channel(1);unrelated.securityInfo.rufoxPolicy='';
Services.obs.notifyObservers(unrelated,'http-on-modify-request');response(unrelated);
assert.equal(service.snapshot(a).total,106,'unrelated certificates are absent');
normal.set('security.rufox.exceptions','example.ru|all|101,keep.ru|ct');
Services.obs.notifyObservers(null,'wake_notification');
function runDue() {
  for (let pass=0;pass<20;pass++) {
    const due=[...timers].filter(([,timer])=>timer.at<=clock);
    if (!due.length) return;
    for (const [id,timer] of due) {timers.delete(id);timer.fn();}
  }
  throw new Error('timer did not settle');
}
runDue();clock=101_000;runDue();
assert.equal(normal.get('security.rufox.exceptions'),'keep.ru|ct');
assert(closedConnections>0,'expiry must terminate existing connections');
memory.set('security.rufox.private_exceptions','private.ru|all');
Services.obs.notifyObservers(null,'last-pb-context-exited');runDue();
assert.equal(memory.get('security.rufox.private_exceptions'),'');
service.detach(a);assert.equal(service.snapshot(a).available,false);
service.detach(b);
console.log('Native per-tab diagnostics and expiry checks passed');
