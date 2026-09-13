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
  io: {newURI(value) {const u=new URL(value);u.hash='';return {
    scheme:u.protocol.slice(0,-1),userPass:u.username||u.password,asciiHost:u.hostname,specIgnoringRef:u.href,
  };}},
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
    nsIHttpChannel:{}, nsIChannel:{}, nsITransportSecurityInfo:{},
    nsIContentPolicy:{TYPE_DOCUMENT:6}, nsIHttpChannelInternal:{} },
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
  return {loadInfo:{browsingContextID:id, externalContentPolicyType:6,
      originAttributes:{privateBrowsingId:0}}, QueryInterface(){return this;},
    grants:0, grantRufoxOneShot(){this.grants++;},
    URI:{asciiHost:host,spec:`https://${host}/`,specIgnoringRef:`https://${host}/`,schemeIs:s=>s==='https'},
    securityInfo:{QueryInterface(){return this;},rufoxPolicy:JSON.stringify({version:1,state,scts:[]})}};
}
function begin(browser, request) {service.progress(browser,{isTopLevel:true},request,5);}
function response(request) {Services.obs.notifyObservers(request,'http-on-examine-response');}
const first=channel(1);
first.securityInfo.handshakeCertificates=[{
  sha256Fingerprint:'AA:BB',subjectName:'CN=example.ru',issuerName:'CN=Issuer',serialNumber:'01',
  validity:{notBefore:1000000,notAfter:2000000},
}];
Object.defineProperty(first.securityInfo, 'serverCert', {get(){throw new Error('failed handshake');}});
begin(a,first); response(first); response(first);
assert.equal(service.snapshot(a).mainReport.certificate.sha256Fingerprint,'AA:BB');
assert.equal(service.snapshot(a).mainReport.certificate.subjectName,'CN=example.ru');
assert.equal(service.snapshot(a).mainReport.certificate.notBefore,'1970-01-01T00:00:01.000Z');
service.progress(a,{isTopLevel:true},first,2);
assert.equal(service.snapshot(a).blocked,1,'one request must not count twice');
assert.equal(service.snapshot(b).total,0,'tabs are isolated');
const late=channel(1,'late.ru');late.loadInfo.externalContentPolicyType=3;Services.obs.notifyObservers(late,'http-on-modify-request');
const next=channel(1,'new.ru','allowed');
next.securityInfo.serverCert={sha256Fingerprint:'CC:DD',subjectName:'x'.repeat(9000)};
next.securityInfo.handshakeCertificates=[{sha256Fingerprint:'WRONG'}];
begin(a,next);response(next);response(late);
assert.equal(service.snapshot(a).mainReport.certificate.sha256Fingerprint,'CC:DD');
assert.equal(service.snapshot(a).mainReport.certificate.subjectName.length,8192);
assert.equal(service.snapshot(a).total,1,'old responses cannot populate a new navigation');
assert.equal(service.snapshot(a).state,'allowed');
for(let i=0;i<105;i++) {const r=channel(1);r.loadInfo.externalContentPolicyType=3;Services.obs.notifyObservers(r,'http-on-modify-request');response(r);}
assert.equal(service.snapshot(a).badge,'99+');
assert.equal(service.snapshot(a).blocked,105);
const unrelated=channel(1);unrelated.loadInfo.externalContentPolicyType=3;unrelated.securityInfo.rufoxPolicy='';
Services.obs.notifyObservers(unrelated,'http-on-modify-request');response(unrelated);
assert.equal(service.snapshot(a).total,106,'unrelated certificates are absent');
// Real document loads use targetBrowsingContextID, with no loading context ID.
const failed=channel(0,'blocked.com');failed.loadInfo.targetBrowsingContextID=1;
Services.obs.notifyObservers(failed,'http-on-modify-request');
Services.obs.notifyObservers(failed,'http-on-rufox-request');
Services.obs.notifyObservers(failed,'http-on-rufox-security-info');
assert.equal(service.snapshot(a).blocked,1);
assert.equal(service.snapshot(a).blockedDomains,1);
assert.equal(service.snapshot(a).mainReport.certificate,null,'missing certificate must not discard the policy result');
assert.equal(service.errorPage(a,failed.URI.spec),'about:bearium-protection#warning=1&url='+encodeURIComponent(failed.URI.spec));
assert.equal(service.errorPage(b,failed.URI.spec),null,'another tab cannot reuse a report');
assert.equal(service.errorPage(a,'https://different.com/'),null);
// DocumentChannel progress arrives after the parent HttpChannel report.
const documentChannel=channel(1,'blocked.com');documentChannel.securityInfo.rufoxPolicy='';
begin(a,documentChannel);
assert.equal(service.snapshot(a).blocked,1,'late progress must not erase early TLS report');
const errorDocument=channel(1);errorDocument.URI={spec:'about:bearium-protection#warning=1',schemeIs:()=>false};
begin(a,errorDocument);
assert.equal(service.snapshot(a).blocked,1,'warning document preserves the failed page');
Services.obs.notifyObservers(failed,'http-on-failed-opening-request');
assert.equal(service.snapshot(a).blocked,1,'multiple failure notifications count once');
// Reloading the same URL resets counters even when progress precedes HTTP.
const reload=channel(1,'blocked.com');begin(a,reload);
Services.obs.notifyObservers(reload,'http-on-modify-request');
assert.equal(service.snapshot(a).total,0);
Services.obs.notifyObservers(reload,'http-on-rufox-security-info');
assert.equal(service.snapshot(a).blocked,1);
// Generic TLS errors remain generic, but cannot be advertised as zero detections.
const generic=channel(1,'other.com');generic.securityInfo.rufoxPolicy='';
Services.obs.notifyObservers(generic,'http-on-modify-request');
assert.equal(service.errorPage(a,generic.URI.spec),null);
service.retainErrorPage(a,generic.URI.spec,'data:text/html,fenix-error');
errorDocument.URI.spec='data:text/html,fenix-error';begin(a,errorDocument);
assert.equal(service.snapshot(a).state,'unavailable');
errorDocument.URI.spec='data:text/html,unrelated';begin(a,errorDocument);
assert.equal(service.snapshot(a).state,'unobserved','unrelated internal navigation clears diagnostics');
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
// The capability applies to one exact URL in one tab, not a host-wide timer.
function permission(request) {Services.obs.notifyObservers(request,'http-on-rufox-request');}
service.armOneShot(a,'https://once.ru/',false);
const wrongTab=channel(2,'once.ru');permission(wrongTab);assert.equal(wrongTab.grants,0);
const subresource=channel(1,'once.ru');subresource.loadInfo.externalContentPolicyType=3;
permission(subresource);assert.equal(subresource.grants,0);
const once=channel(1,'once.ru');permission(once);assert.equal(once.grants,1);
const again=channel(1,'once.ru');permission(again);assert.equal(again.grants,0);
service.armOneShot(a,'https://once.ru/path?q=1',false);
const wrongPath=channel(1,'once.ru');permission(wrongPath);assert.equal(wrongPath.grants,0);
assert.equal(service.snapshot(a).available,true);
service.armOneShot(a,'https://once.ru/',true);
const wrongPrivacy=channel(1,'once.ru');permission(wrongPrivacy);assert.equal(wrongPrivacy.grants,0);
service.armOneShot(a,'https://once.ru/',true);
const privateOnce=channel(1,'once.ru');privateOnce.loadInfo.originAttributes.privateBrowsingId=1;
permission(privateOnce);assert.equal(privateOnce.grants,1);
service.armOneShot(a,'https://once.ru/',false);clock+=60_000;
const expired=channel(1,'once.ru');permission(expired);assert.equal(expired.grants,0);
service.armOneShot(a,'https://once.ru/',false);service.cancelOneShot(a);
const cancelled=channel(1,'once.ru');permission(cancelled);assert.equal(cancelled.grants,0);
assert.throws(()=>service.armOneShot(a,'https://user:password@once.ru/',false));
assert.throws(()=>service.armOneShot(a,'http://once.ru/',false));
assert(![...normal.values(),...memory.values()].some(v=>v.includes('once.ru')));
service.armOneShot(a,'https://once.ru/',false);
service.detach(a);assert.equal(service.snapshot(a).available,false);
service.detach(b);
console.log('Native per-tab diagnostics and expiry checks passed');
