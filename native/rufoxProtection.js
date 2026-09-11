/* MPL-2.0. Runs only in the privileged, non-linkable about page. */
"use strict";
const { PrivateBrowsingUtils } = ChromeUtils.importESModule("resource://gre/modules/PrivateBrowsingUtils.sys.mjs");
const { RufoxProtection } = ChromeUtils.importESModule("resource://gre/modules/RufoxProtection.sys.mjs");
const privateMode = PrivateBrowsingUtils.isContentWindowPrivate(window);
const memory = Services.prefs.getDefaultBranch("");
const regularPref = "security.rufox.exceptions";
const sessionPref = "security.rufox.session_exceptions";
const privatePref = "security.rufox.private_exceptions";
const $ = id => document.getElementById(id);
const selected = new Set();
let snapshot = { domains: [] };
let lastSnapshot = "";
let returnURL = null;
const sources = privateMode ? [[memory, privatePref, "приватный сеанс"]] :
  [[memory, sessionPref, "сеанс"], [Services.prefs, regularPref, "постоянно"]];
function entries(branch, pref) {
  return new Set(branch.getStringPref(pref, "").split(",").filter(Boolean));
}
function normalize(value) {
  const uri = Services.io.newURI(value.includes("://") ? value : `https://${value}`);
  if (uri.scheme !== "https" || uri.userPass || !uri.asciiHost) {
    throw new Error("Укажите HTTPS-сайт без имени пользователя и пароля.");
  }
  const host = uri.asciiHost.toLowerCase().replace(/\.$/, "");
  if (!/^[a-z0-9.:[\]-]+$/.test(host) || host.length > 253) throw new Error("Некорректное имя сайта.");
  return host;
}
function save(branch, pref, values) {
  if (values.size > 1000) throw new Error("Допускается не более 1000 исключений.");
  branch.setStringPref(pref, [...values].sort().join(","));
  Services.obs.notifyObservers(null, "net:cancel-all-connections");
  renderExceptions();
}
function node(tag, text, parent) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (parent) parent.append(element);
  return element;
}
function renderExceptions() {
  $("exceptions").replaceChildren();
  for (const [branch, pref, duration] of sources) {
    for (const entry of entries(branch, pref)) {
      const [host, scope, expiry] = entry.split("|");
      const lifetime = expiry ? `до ${new Date(Number(expiry) * 1000).toLocaleString()}` : duration;
      const item = node("li", `${host} — ${scope === "zone" ? "зона" : scope === "ct" ? "SCT" : "зона и SCT"}, ${lifetime} `, $("exceptions"));
      const remove = node("button", "Удалить", item);
      remove.addEventListener("click", event => {
        if (!event.isTrusted) return;
        const values = entries(branch, pref); values.delete(entry); save(branch, pref, values);
        $("status").textContent = "Исключение удалено. Откройте сайт повторно для новой проверки.";
      });
    }
  }
}
const reasons = {
  verified: "Подходящие SCT проверены",
  "missing-yandex": "Нет действительного SCT Yandex, подходящего по состоянию журнала и сроку сертификата",
  "insufficient-operators": "Недостаточно независимых операторов журналов",
  "verifier-unavailable": "Проверка SCT недоступна",
  "certificate-unreadable": "Не удалось прочитать данные сертификата для проверки SCT",
  "verification-error": "Ошибка проверки SCT",
};
function renderReport(report, parent) {
  const detail = node("details", undefined, parent);
  node("summary", report.state === "blocked" ? "Блокировка политикой УЦ" :
    report.state === "exception" ? "Применено пользовательское разрешение" : "Проверка пройдена", detail);
  if (report.oneShot) node("p", "Применён одноразовый обход для этого перехода.", detail);
  node("p", report.zoneAllowed ? "Домен в .ru / .su / .рф." :
    report.zoneException ? "Домен вне разрешённых зон; применено исключение зоны." : "Домен вне разрешённых зон; запрос блокируется.", detail);
  node("p", (reasons[report.ctReason] || report.ctReason) + (report.ctException ? ". Применено исключение SCT." : "."), detail);
  node("p", `Источники SCT: сертификат ${report.embedded}, TLS ${report.tls}, OCSP ${report.ocsp}. Независимых операторов: ${report.operators}.`, detail);
  node("p", `Ошибки: формат ${report.decodingErrors}, неизвестные журналы ${report.unknownLogs}, подписи ${report.invalidSignatures}, время ${report.invalidTimestamps}, недоверенное время ${report.distrustedTimestamps}.`, detail);
  for (const sct of report.scts || []) {
    const log = RufoxLogMetadata.logs[sct.logId];
    node("p", `${log?.name || sct.logId} · ${new Date(sct.timestamp).toISOString()} · ${sct.source} · ${sct.accepted ? "учтён политикой" : "подпись верна, но срок или состояние журнала не подходят"}`, detail);
  }
  if (report.verifiedCount > (report.scts?.length || 0)) node("p", "Список SCT сокращён; при проверке учитывались все SCT.", detail);
}
function refreshPage() {
  try {
    const browser = window.browsingContext.top.embedderElement;
    snapshot = RufoxProtection.snapshot(browser);
  } catch (_) { snapshot = { available: false, domains: [] }; }
  const serialized = JSON.stringify(snapshot);
  if (serialized === lastSnapshot) return;
  lastSnapshot = serialized;
  $("page-state").textContent = !snapshot.available ? "Состояние исходной вкладки недоступно. Можно разрешить сайт вручную." :
    snapshot.state === "unavailable" ? "Нет результата проверки сертификата страницы. Причину общей ошибки соединения смотрите на странице ошибки." :
    snapshot.total ? `Запросов с этим УЦ: ${snapshot.total}. Заблокировано: ${snapshot.blocked}.` : "Запросов с результатом проверки этого УЦ не обнаружено.";
  if (snapshot.truncated) $("page-state").textContent += " Список ограничен 1000 доменами; счётчик продолжает учитывать запросы.";
  $("domains").replaceChildren();
  for (const domain of snapshot.domains) {
    const section = node("section", undefined, $("domains"));
    const label = node("label", undefined, section);
    const checkbox = node("input", undefined, label);
    checkbox.type = "checkbox"; checkbox.checked = selected.has(domain.host);
    checkbox.dataset.host = domain.host;
    checkbox.addEventListener("change", event => {
      if (!event.isTrusted) return;
      if (checkbox.checked) selected.add(domain.host); else selected.delete(domain.host);
    });
    label.append(document.createTextNode(` ${domain.host} — ${domain.count} запросов, ${domain.blocked} блокировок`));
    for (const report of domain.reports) renderReport(report, section);
    if (!domain.reports.length) node("p", "Подробности вытеснены более новыми запросами. Счётчик и выбор домена сохранены.", section);
  }
}
function updateSelection() {
  for (const input of $("domains").querySelectorAll("input")) input.checked = selected.has(input.dataset.host);
}
$("select-blocked").addEventListener("click", event => {
  if (!event.isTrusted) return;
  snapshot.domains.filter(d => d.blocked).forEach(d => selected.add(d.host)); updateSelection();
});
$("clear-selection").addEventListener("click", event => {
  if (!event.isTrusted) return;
  selected.clear(); updateSelection();
});
$("open-once").addEventListener("click", event => {
  if (!event.isTrusted || !returnURL) return;
  const browser = window.browsingContext.top.embedderElement;
  try {
    RufoxProtection.armOneShot(browser, returnURL, privateMode);
    location.replace(returnURL);
  } catch (error) {
    RufoxProtection.cancelOneShot(browser);
    $("status").textContent = error.message;
  }
});
$("allow").addEventListener("click", event => {
  if (!event.isTrusted) return;
  try {
    const hosts = new Set([...selected, ...$("hosts").value.split(/\s+/).filter(Boolean)].map(normalize));
    if (!hosts.size) throw new Error("Выберите или укажите хотя бы один сайт.");
    const scope = $("scope").value;
    if (!["zone", "ct", "all"].includes(scope)) throw new Error("Некорректное разрешение.");
    const hourly = $("duration").value === "hour";
    const permanent = !privateMode && (hourly || $("duration").value === "permanent");
    const branch = permanent ? Services.prefs : memory;
    const pref = privateMode ? privatePref : permanent ? regularPref : sessionPref;
    const values = entries(branch, pref);
    const expiry = hourly ? `|${Math.floor(Date.now() / 1000) + 3600}` : "";
    for (const host of hosts) values.add(`${host}|${scope}${expiry}`);
    save(branch, pref, values);
    $("status").textContent = "Разрешение сохранено. Вернитесь на сайт для новой проверки.";
    if (returnURL && $("reload").checked) location.replace(returnURL);
  } catch (error) { $("status").textContent = error.message; }
});
$("hardened").checked = Services.prefs.getBoolPref("security.rufox.hardened", false);
$("hardened").addEventListener("change", event => {
  if (!event.isTrusted) return;
  Services.prefs.setBoolPref("security.rufox.hardened", $("hardened").checked);
  Services.obs.notifyObservers(null, "net:cancel-all-connections");
  $("status").textContent = "Режим изменён. Откройте сайт повторно для новой проверки.";
});
$("privacy").textContent = privateMode ? "Приватный режим: разрешения хранятся в памяти до закрытия всех приватных вкладок." :
  "По умолчанию разрешение сохраняется постоянно. Срок и область можно изменить в параметрах исключения.";
if (privateMode) {
  $("duration").value = "session";
  $("duration").options[2].disabled = true;
  $("duration").options[0].textContent = "До закрытия всех приватных вкладок";
}
$("log-version").textContent = `Встроенный список ${RufoxLogMetadata.version}, обновлён ${RufoxLogMetadata.timestamp}. Обновляется вместе с браузером.`;
for (const log of Object.values(RufoxLogMetadata.logs)) node("li", `${log.name} · ${log.state} · срок окончания сертификата: ${log.interval.start_inclusive} — ${log.interval.end_exclusive} (не включая конец)`, $("logs"));
try {
  const target = new URLSearchParams(location.hash.slice(1)).get("url");
  if (target) {
    const host = normalize(target);
    const uri = Services.io.newURI(target);
    refreshPage();
    if (!snapshot.domains.length) $("hosts").value = host;
    else if (snapshot.domains.some(d => d.host === host && d.blocked)) {
      selected.add(host); updateSelection();
    }
    returnURL = uri.spec;
    $("one-shot").hidden = false;
    $("return").href = uri.spec; $("return").hidden = false;
  }
} catch (_) { /* Manual controls remain available without an originating URL. */ }
$("reload").disabled = !returnURL;
renderExceptions(); refreshPage();
const refreshTimer = setInterval(refreshPage, 1000);
window.addEventListener("unload", () => clearInterval(refreshTimer), { once: true });
