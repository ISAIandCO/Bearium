/* MPL-2.0. Parent-process, per-tab diagnostics. No browsing history on disk. */
import { setTimeout, clearTimeout } from "resource://gre/modules/Timer.sys.mjs";

const TOPICS = ["http-on-rufox-request", "http-on-rufox-security-info", "http-on-modify-request", "http-on-examine-response",
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
      for (const tab of tabs.values()) if (tab.oneShot?.privateMode) clearOneShot(tab);
      Services.prefs.getDefaultBranch("").setStringPref("security.rufox.private_exceptions", "");
      Services.obs.notifyObservers(null, "net:cancel-all-connections");
    }
    clearTimeout(expiryTimer);
    expiryTimer = setTimeout(expirePermissions, 0);
  },
};
function fresh() {
  return { domains: new Map(), recent: [], blocked: 0, total: 0, truncated: false, unavailable: false, mainReport: null, url: "" };
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
        collect(channel);
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
      badge: page.blocked > 99 ? "99+" : page.blocked ? String(page.blocked) :
        page.unavailable ? "?" : page.mainReport?.ctReason === "verified" ? "CT" : "", total: page.total,
      truncated: page.truncated,
      state: page.blocked ? "blocked" : page.unavailable ? "unavailable" : [...page.domains.values()].some(
        d => d.reports.some(r => r.state === "exception")) ? "exception" :
        page.total ? "allowed" : "unobserved",
      domains: [...page.domains.values()].map(d => ({ ...d, reports: d.reports.map(r => ({ ...r })) })),
    };
  },
};
