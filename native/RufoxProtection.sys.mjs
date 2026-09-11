/* MPL-2.0. Parent-process, per-tab diagnostics. No browsing history on disk. */
import { setTimeout, clearTimeout } from "resource://gre/modules/Timer.sys.mjs";

const TOPICS = ["http-on-modify-request", "http-on-examine-response",
  "http-on-examine-cached-response", "http-on-examine-merged-response",
  "http-on-failed-opening-request"];
const tabs = new Map();
const bindings = new WeakMap();
const MAX_DOMAINS = 1000;
const MAX_REPORTS = 20;
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
      Services.prefs.getDefaultBranch("").setStringPref("security.rufox.private_exceptions", "");
      Services.obs.notifyObservers(null, "net:cancel-all-connections");
    }
    clearTimeout(expiryTimer);
    expiryTimer = setTimeout(expirePermissions, 0);
  },
};
function fresh() {
  return { domains: new Map(), recent: [], blocked: 0, total: 0, truncated: false, url: "" };
}
function tabFor(channel) {
  const info = channel.loadInfo;
  const context = BrowsingContext.get(info.browsingContextID || info.topBrowsingContextID);
  const browser = context?.top?.embedderElement;
  return tabs.get(browser);
}
function bind(channel, tab) {
  if (!bindings.has(channel)) bindings.set(channel, { tab, page: tab.page, seen: false });
}
function collect(channel) {
  const binding = bindings.get(channel);
  if (!binding || binding.seen || binding.page !== binding.tab.page) return;
  const raw = channel.securityInfo?.QueryInterface(Ci.nsITransportSecurityInfo).rufoxPolicy;
  if (!raw) return;
  let report;
  try { report = JSON.parse(raw); } catch (_) { return; }
  if (report.version !== 1) return;
  binding.seen = true;
  const page = binding.page;
  const host = channel.URI.asciiHost.toLowerCase().replace(/\.$/, "");
  page.total++;
  if (report.state === "blocked") page.blocked++;
  if (!page.domains.has(host) && page.domains.size >= MAX_DOMAINS) {
    page.truncated = true;
    return;
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
      if (topic === "http-on-modify-request") {
        const tab = tabFor(channel);
        if (tab) bind(channel, tab);
      } else {
        // Never attach a late response to whichever page happens to be current.
        // Cached requests are bound by the progress listener at STATE_START.
        collect(channel);
      }
    } catch (_) { /* Non-HTTP or a channel without TLS metadata. */ }
  },
};
export const RufoxProtection = {
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
    tabs.delete(browser);
    if (!tabs.size && observing) {
      TOPICS.forEach(topic => Services.obs.removeObserver(observer, topic));
      observing = false;
    }
  },
  progress(browser, progress, request, flags) {
    const tab = tabs.get(browser);
    if (!tab || !request) return;
    try {
      const channel = request.QueryInterface(Ci.nsIChannel);
      const W = Ci.nsIWebProgressListener;
      // Only our controls and certificate error pages retain the originating page.
      if (!channel.URI.schemeIs("http") && !channel.URI.schemeIs("https")) {
        if (progress.isTopLevel && (flags & W.STATE_START) && (flags & W.STATE_IS_NETWORK) &&
            !/^(about:(rufox-protection|neterror|certerror)([?#]|$))/.test(channel.URI.spec)) {
          tab.page = fresh();
        }
        return;
      }
      if (progress.isTopLevel && (flags & W.STATE_START) && (flags & W.STATE_IS_NETWORK)) {
        tab.page = fresh();
        tab.page.url = channel.URI.spec;
        bindings.delete(channel);
      }
      if (flags & W.STATE_START) bind(channel, tab);
      if (flags & W.STATE_STOP) collect(channel);
    } catch (_) { /* Requests without a channel carry no certificate report. */ }
  },
  snapshot(browser) {
    const page = tabs.get(browser)?.page;
    if (!page) return { available: false, domains: [], blocked: 0, total: 0 };
    return { available: true, url: page.url, blocked: page.blocked,
      badge: page.blocked > 99 ? "99+" : String(page.blocked), total: page.total,
      truncated: page.truncated,
      state: page.blocked ? "blocked" : [...page.domains.values()].some(
        d => d.reports.some(r => r.state === "exception")) ? "exception" :
        page.total ? "allowed" : "unobserved",
      domains: [...page.domains.values()].map(d => ({ ...d, reports: d.reports.map(r => ({ ...r })) })),
    };
  },
};
