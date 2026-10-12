/* MPL-2.0. Parent-process, per-tab diagnostics. No browsing history on disk. */
import { setTimeout, clearTimeout } from "resource://gre/modules/Timer.sys.mjs";

const TOPICS = ["http-on-rufox-request", "http-on-rufox-security-info", "http-on-modify-request", "http-on-examine-response",
  "http-on-examine-cached-response", "http-on-examine-merged-response",
  "http-on-failed-opening-request"];
const tabs = new Map();
const bindings = new WeakMap();
const MAX_DOMAINS = 1000;
const MAX_REPORTS = 20;
const MAX_CHAIN_CERTS = 10;
const trustHistory = new Map();
const privateTrustHistory = new Map();
let observing = false;
let policyObserverStarted = false;
let expiryTimer;
// Expiration must also terminate established connections, not just affect the
// next handshake. Native verification independently checks the absolute expiry.
function expirePermissions() {
  clearTimeout(expiryTimer);
  let next = Infinity;
  let changed = false;
  const now = Math.floor(Date.now() / 1000);
  for (const [branch, pref] of [
    [Services.prefs, "security.rufox.exceptions"],
    [Services.prefs.getDefaultBranch(""), "security.rufox.session_exceptions"],
    [Services.prefs.getDefaultBranch(""), "security.rufox.private_exceptions"],
  ]) {
    const original = branch.getStringPref(pref, "");
    const retained = original.split(",").filter(entry => {
      const expiry = entry.split("|")[2];
      if (!expiry) return Boolean(entry);
      const until = Number(expiry);
      if (!Number.isSafeInteger(until) || until <= now) return false;
      next = Math.min(next, until);
      return true;
    }).join(",");
    if (retained !== original) {
      branch.setStringPref(pref, retained);
      changed = true;
    }
  }
  if (changed) Services.obs.notifyObservers(null, "net:cancel-all-connections");
  if (Number.isFinite(next)) expiryTimer = setTimeout(expirePermissions,
    Math.min(2147483647, Math.max(1, next * 1000 - Date.now())));
}
const policyObserver = {
  observe(_subject, topic) {
    if (topic === "last-pb-context-exited") {
      privateTrustHistory.clear();
      for (const tab of tabs.values()) if (tab.oneShot?.privateMode) clearOneShot(tab);
      Services.prefs.getDefaultBranch("").setStringPref("security.rufox.private_exceptions", "");
      Services.obs.notifyObservers(null, "net:cancel-all-connections");
    }
    clearTimeout(expiryTimer);
    expiryTimer = setTimeout(expirePermissions, 0);
  },
};
function fresh() {
  return { domains: new Map(), recent: [], blocked: 0, total: 0, truncated: false, unavailable: false, mainReport: null, trustChange: null, url: "" };
}
function tabFor(channel) {
  const info = channel.loadInfo;
  const context = BrowsingContext.get(info.targetBrowsingContextID || info.browsingContextID || info.associatedBrowsingContextID);
  const browser = context?.top?.embedderElement;
  return tabs.get(browser);
}
// A grant is held by the parent UI, never by a preference or a content process.
function clearOneShot(tab) {
  if (!tab?.oneShot) return;
  clearTimeout(tab.oneShot.timer);
  delete tab.oneShot;
}
function consumeOneShot(channel, tab) {
  const grant = tab?.oneShot;
  if (!grant) return;
  if (Date.now() >= grant.expires) { clearOneShot(tab); return; }
  const info = channel.loadInfo;
  if (info.externalContentPolicyType !== Ci.nsIContentPolicy.TYPE_DOCUMENT) return;
  // A navigation to another URL cancels the grant, including a redirect.
  const matches = channel.URI.specIgnoringRef === grant.url &&
    Boolean(info.originAttributes.privateBrowsingId) === grant.privateMode;
  clearOneShot(tab);
  if (matches) channel.QueryInterface(Ci.nsIHttpChannelInternal).grantRufoxOneShot();
}
function begin(channel, tab) {
  if (bindings.get(channel)?.started) return;
  if (channel.loadInfo.externalContentPolicyType === Ci.nsIContentPolicy.TYPE_DOCUMENT) {
    tab.page = fresh();
    tab.page.url = channel.URI.spec;
    bindings.delete(channel);
  }
  bind(channel, tab);
  bindings.get(channel).started = true;
}
function bind(channel, tab) {
  if (!bindings.has(channel)) bindings.set(channel, { tab, page: tab.page, seen: false });
}
// Keep only bounded, plain certificate fields, alongside the existing 20-report
// per-tab history. Failed TLS handshakes may only expose handshakeCertificates.
function describeCertificate(cert, limit = 8192) {
  if (!cert) return null;
  const result = {};
  for (const field of ["sha256Fingerprint", "subjectName", "issuerName", "serialNumber"]) {
    try { result[field] = String(cert[field] || "").slice(0, limit); } catch (_) {}
  }
  for (const field of ["notBefore", "notAfter"]) {
    try {
      const millis = Number(cert.validity[field]) / 1000;
      if (Number.isFinite(millis)) result[field] = new Date(millis).toISOString();
    } catch (_) {}
  }
  return result;
}
function certificateDetails(info) {
  let cert;
  try { cert = info.serverCert; } catch (_) {}
  if (!cert) {
    try { cert = info.handshakeCertificates?.[0]; } catch (_) {}
  }
  return describeCertificate(cert);
}
function certificateChain(info) {
  let certificates, source = "built";
  try { certificates = info.succeededCertChain; } catch (_) {}
  if (!certificates?.length) {
    source = "received";
    try { certificates = info.handshakeCertificates; } catch (_) {}
  }
  if (!certificates?.length) return null;
  // The end of a received TLS list is not necessarily a root or a trust anchor.
  // Full DER blobs never enter the bounded per-tab snapshots.
  const chain = [];
  const count = Math.min(MAX_CHAIN_CERTS, certificates.length);
  for (let index = 0; index < count; index++) {
    const certificate = describeCertificate(certificates[index], 512);
    if (certificate) chain.push(certificate);
  }
  return { source, truncated: certificates.length > count, certificates: chain };
}
function tlsAccepted(info) {
  try {
    const W = Ci.nsIWebProgressListener;
    return info.errorCode === 0 && Boolean(info.securityState & W.STATE_IS_SECURE) &&
      !(info.securityState & W.STATE_CERT_USER_OVERRIDDEN);
  } catch (_) { return false; }
}
function observeTrust(channel, binding, info) {
  // A response observation is informational and happens after HTTP. Never use
  // this history to authorize a request, create an exception or replay a body.
  if (channel.loadInfo.externalContentPolicyType !== Ci.nsIContentPolicy.TYPE_DOCUMENT ||
      channel.URI.scheme !== "https" || !tlsAccepted(info) || !info.succeededCertChain?.length) return;
  const raw = info.rufoxPolicy;
  let current;
  if (raw === "") current = "other";  // Explicit native absence, not a missing IPC field.
  else {
    let report;
    try { report = JSON.parse(raw); } catch (_) { return; }
    if (report.version !== 1 || !["allowed", "exception"].includes(report.state)) return;
    current = "protected";
  }
  const host = channel.URI.asciiHost.toLowerCase().replace(/\.$/, "");
  const port = channel.URI.port === -1 ? 443 : channel.URI.port;
  if (!host || !Number.isInteger(port) || port < 1 || port > 65535) return;
  const key = JSON.stringify([host, port]);
  const history = channel.loadInfo.originAttributes.privateBrowsingId ? privateTrustHistory : trustHistory;
  const previous = history.get(key);
  if (previous && previous !== current) binding.page.trustChange = { host, port, from: previous, to: current };
  history.delete(key);
  history.set(key, current);
  if (history.size > MAX_DOMAINS) history.delete(history.keys().next().value);
}
function collect(channel, networkResponse = false) {
  const binding = bindings.get(channel);
  if (!binding || binding.page !== binding.tab.page) return;
  const info = channel.securityInfo?.QueryInterface(Ci.nsITransportSecurityInfo);
  // Cache replay must not claim that a server just changed its trust source.
  // An earlier TLS report can already have marked this binding as seen.
  if (networkResponse && info) {
    try { observeTrust(channel, binding, info); } catch (_) {
      // An unavailable observation must not suppress the CA policy report.
    }
  }
  if (binding.seen) return;
  const raw = info?.rufoxPolicy;
  if (!raw) return;
  let report;
  try { report = JSON.parse(raw); } catch (_) { return; }
  if (report.version !== 1 || !["allowed", "blocked", "exception"].includes(report.state)) return;
  report.tlsAccepted = tlsAccepted(info);
  try {
    report.tlsError = info.errorCode;
  } catch (_) { /* Missing metadata never confirms acceptance of the chain. */ }
  report.certificate = certificateDetails(info);
  report.chain = certificateChain(info);
  binding.seen = true;
  const page = binding.page;
  const host = channel.URI.asciiHost.toLowerCase().replace(/\.$/, "");
  if (channel.loadInfo.externalContentPolicyType === Ci.nsIContentPolicy.TYPE_DOCUMENT) page.mainReport = report;
  page.total++;
  if (report.state === "blocked") page.blocked++;
  if (!page.domains.has(host) && page.domains.size >= MAX_DOMAINS) {
    page.truncated = true;
    // Keep blocked domains selectable even if successful domains filled the list.
    const replaceable = report.state === "blocked" &&
      [...page.domains.values()].find(domain => !domain.blocked);
    if (!replaceable) return;
    page.domains.delete(replaceable.host);
    page.recent = page.recent.filter(item => item.host !== replaceable.host);
  }
  const previous = page.domains.get(host);
  // Preserve distinct outcomes (e.g. different certificates on one CDN host).
  const reports = previous?.reports || [];
  const identity = JSON.stringify(report);
  if (!reports.some(item => JSON.stringify(item) === identity)) {
    reports.push(report);
    page.recent.push({ host, report });
    if (page.recent.length > MAX_REPORTS) {
      const oldest = page.recent.shift();
      const oldReports = oldest.host === host ? reports : page.domains.get(oldest.host)?.reports;
      const index = oldReports?.indexOf(oldest.report) ?? -1;
      if (index >= 0) oldReports.splice(index, 1);
    }
  }
  page.domains.set(host, { host, count: (previous?.count || 0) + 1,
    blocked: (previous?.blocked || 0) + (report.state === "blocked" ? 1 : 0), reports });
}
const observer = {
  observe(subject, topic) {
    try {
      const channel = subject.QueryInterface(Ci.nsIHttpChannel);
      if (topic === "http-on-rufox-request") {
        const tab = tabFor(channel);
        consumeOneShot(channel, tab);
        if (tab) begin(channel, tab);
      } else if (topic === "http-on-modify-request") {
        const tab = tabFor(channel);
        if (tab) begin(channel, tab);
      } else {
        // Never attach a late response to whichever page happens to be current.
        // Cached requests are bound by the progress listener at STATE_START.
        collect(channel, topic === "http-on-examine-response");
      }
    } catch (_) { /* Non-HTTP or a channel without TLS metadata. */ }
  },
};
export const RufoxProtection = {
  errorPage(browser, target) {
    const page = tabs.get(browser)?.page;
    if (!page || page.url !== target) return null;
    if (page.mainReport?.state === "blocked") {
      return "about:bearium-protection#warning=1&url=" + encodeURIComponent(target);
    }
    page.unavailable = true;
    return null;
  },
  retainErrorPage(browser, target, uri) {
    const page = tabs.get(browser)?.page;
    if (page?.url === target && uri) page.errorURI = uri;
  },
  armOneShot(browser, target, privateMode) {
    const tab = tabs.get(browser);
    if (!tab) throw new Error("Исходная вкладка уже закрыта.");
    const uri = Services.io.newURI(target);
    if (uri.scheme !== "https" || uri.userPass || !uri.asciiHost) {
      throw new Error("Одноразовый переход доступен только для HTTPS-сайта.");
    }
    clearOneShot(tab);
    tab.oneShot = { url: uri.specIgnoringRef, privateMode: Boolean(privateMode),
      expires: Date.now() + 60000, timer: setTimeout(() => clearOneShot(tab), 60000) };
  },
  cancelOneShot(browser) { clearOneShot(tabs.get(browser)); },
  attach(browser) {
    if (!policyObserverStarted) {
      Services.prefs.addObserver("security.rufox.", policyObserver);
      Services.obs.addObserver(policyObserver, "wake_notification");
      Services.obs.addObserver(policyObserver, "last-pb-context-exited");
      policyObserverStarted = true;
      expirePermissions();
    }
    if (!tabs.has(browser)) tabs.set(browser, { page: fresh() });
    if (!observing) {
      TOPICS.forEach(topic => Services.obs.addObserver(observer, topic));
      observing = true;
    }
  },
  detach(browser) {
    clearOneShot(tabs.get(browser));
    tabs.delete(browser);
    if (!tabs.size && observing) {
      TOPICS.forEach(topic => Services.obs.removeObserver(observer, topic));
      observing = false;
    }
  },
  progress(browser, progress, request, flags, status = 0) {
    const tab = tabs.get(browser);
    if (!tab || !request) return;
    try {
      const channel = request.QueryInterface(Ci.nsIChannel);
      const W = Ci.nsIWebProgressListener;
      // Only our controls and certificate error pages retain the originating page.
      if (!channel.URI.schemeIs("http") && !channel.URI.schemeIs("https")) {
        if (progress.isTopLevel && (flags & W.STATE_START) && (flags & W.STATE_IS_NETWORK) &&
            channel.URI.spec !== tab.page.errorURI &&
            !/^(about:(bearium-protection|neterror|certerror)([?#]|$)|chrome:\/\/global\/content\/rufoxProtection.html)/.test(channel.URI.spec)) {
          clearOneShot(tab);
          tab.page = fresh();
        }
        return;
      }
      if (progress.isTopLevel && (flags & W.STATE_START) && (flags & W.STATE_IS_NETWORK)) {
        if (tab.oneShot && channel.URI.specIgnoringRef !== tab.oneShot.url) clearOneShot(tab);
        // The parent HTTP observer can run before the DocumentChannel progress
        // notification. Do not discard its report when that notification arrives.
        if (tab.page.url !== channel.URI.spec) {
          tab.page = fresh();
          tab.page.url = channel.URI.spec;
        }
      }
      if (flags & W.STATE_START) bind(channel, tab);
      if (flags & W.STATE_STOP) {
        collect(channel);
        if (progress.isTopLevel && (flags & W.STATE_IS_NETWORK) && status &&
            bindings.get(channel)?.page === tab.page && !tab.page.mainReport) tab.page.unavailable = true;
      }
    } catch (_) { /* Requests without a channel carry no certificate report. */ }
  },
  snapshot(browser) {
    const page = tabs.get(browser)?.page;
    if (!page) return { available: false, domains: [], blocked: 0, total: 0 };
    return { available: true, url: page.url, blocked: page.blocked,
      blockedDomains: [...page.domains.values()].filter(d => d.blocked).length,
      domainCount: page.domains.size, mainReport: page.mainReport,
      trustChange: page.trustChange ? { ...page.trustChange } : null,
      badge: page.blocked > 99 ? "99+" : page.blocked ? String(page.blocked) :
        page.unavailable ? "?" : page.mainReport?.state === "exception" ? "!" :
        page.mainReport && !page.mainReport.tlsAccepted ? "?" :
        page.mainReport?.ctReason === "verified" ? "CT" : "", total: page.total,
      truncated: page.truncated,
      state: page.blocked ? "blocked" : page.unavailable ? "unavailable" : [...page.domains.values()].some(
        d => d.reports.some(r => r.state === "exception")) ? "exception" :
        page.total ? "allowed" : "unobserved",
      domains: [...page.domains.values()].map(d => ({ ...d, reports: d.reports.map(r => ({ ...r })) })),
    };
  },
};
