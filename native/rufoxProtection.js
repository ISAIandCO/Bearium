/* MPL-2.0. Runs only in the privileged, non-linkable about page. */
"use strict";
const { PrivateBrowsingUtils } = ChromeUtils.importESModule(
  "resource://gre/modules/PrivateBrowsingUtils.sys.mjs"
);
const privateMode = PrivateBrowsingUtils.isContentWindowPrivate(window);
const pref = privateMode ? "security.rufox.private_exceptions" : "security.rufox.exceptions";
const branch = privateMode ? Services.prefs.getDefaultBranch("") : Services.prefs;
if (privateMode) {
  const clearPrivate = () => {
    branch.setStringPref(pref, "");
    Services.obs.notifyObservers(null, "net:cancel-all-connections");
    Services.obs.removeObserver(clearPrivate, "last-pb-context-exited");
  };
  Services.obs.addObserver(clearPrivate, "last-pb-context-exited");
}
const $ = id => document.getElementById(id);
function entries() {
  return new Set(branch.getStringPref(pref, "").split(",").filter(Boolean));
}
function normalize(value) {
  const uri = Services.io.newURI(value.includes("://") ? value : `https://${value}`);
  if (uri.scheme !== "https" || uri.userPass || !uri.asciiHost) {
    throw new Error("Укажите HTTPS-сайт без имени пользователя и пароля.");
  }
  const host = uri.asciiHost.toLowerCase().replace(/\.$/, "");
  if (!/^[a-z0-9.:[\]-]+$/.test(host) || host.length > 253) {
    throw new Error("Некорректное имя сайта.");
  }
  return host;
}
function save(values) {
  if (values.size > 1000) throw new Error("Допускается не более 1000 исключений.");
  branch.setStringPref(pref, [...values].sort().join(","));
  // nsNSSComponent rebuilds the verifier and flushes TLS sessions for this pref.
  Services.obs.notifyObservers(null, "net:cancel-all-connections");
  render();
}
function render() {
  $("exceptions").replaceChildren();
  for (const entry of entries()) {
    const [host, scope] = entry.split("|");
    const item = document.createElement("li");
    item.append(document.createTextNode(`${host} — ${scope === "zone" ? "зона" : scope === "ct" ? "SCT" : "зона и SCT"} `));
    const remove = document.createElement("button");
    remove.textContent = "Удалить";
    remove.addEventListener("click", event => {
      if (!event.isTrusted) return;
      const values = entries(); values.delete(entry); save(values);
      $("status").textContent = "Исключение удалено. Защита снова действует.";
    });
    item.append(remove); $("exceptions").append(item);
  }
}
$("allow").addEventListener("click", event => {
  if (!event.isTrusted) return;
  try {
    const hosts = $("hosts").value.split(/\s+/).filter(Boolean).map(normalize);
    if (!hosts.length) throw new Error("Укажите хотя бы один сайт.");
    const scope = $("scope").value;
    if (!["zone", "ct", "all"].includes(scope)) throw new Error("Некорректное разрешение.");
    const values = entries();
    for (const host of hosts) values.add(`${host}|${scope}`);
    save(values);
    $("status").textContent = "Разрешение сохранено. Можно вернуться на сайт.";
  } catch (error) { $("status").textContent = error.message; }
});
$("privacy").textContent = privateMode
  ? "Приватный режим: разрешения хранятся в памяти до закрытия всех приватных вкладок."
  : "Разрешения сохраняются постоянно, пока вы их не удалите.";
if (privateMode) $("allow").textContent = "Разрешить в приватном режиме";
try {
  const target = new URLSearchParams(location.hash.slice(1)).get("url");
  if (target) {
    const host = normalize(target);
    const uri = Services.io.newURI(target);
    if (uri.scheme === "https" && !uri.userPass) {
      $("hosts").value = host;
      $("return").href = uri.spec;
      $("return").hidden = false;
    }
  }
} catch (_) { /* The page also works without a valid originating URL. */ }
render();
