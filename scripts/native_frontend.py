"""GeckoView bridge for the native per-request CA diagnostics."""
from pathlib import Path


def install(transforms, once):
    def progress(s):
        s = once(s, 'import { GeckoViewModule }', 'import { RufoxProtection } from "resource://gre/modules/RufoxProtection.sys.mjs";\nimport { GeckoViewModule }')
        s = once(s, '    this._fireInitialLoad();', '    RufoxProtection.attach(this.browser);\n    this._fireInitialLoad();')
        s = once(s, '      Ci.nsIWebProgress.NOTIFY_STATE_NETWORK |', '      Ci.nsIWebProgress.NOTIFY_STATE_REQUEST |\n      Ci.nsIWebProgress.NOTIFY_STATE_NETWORK |')
        s = once(s, '    this.registerListener("GeckoView:GetQWACStatus");', '    this.registerListener("GeckoView:GetRufoxProtection");\n    this.registerListener("GeckoView:GetQWACStatus");')
        s = once(s, '    this.unregisterListener("GeckoView:GetQWACStatus");', '    RufoxProtection.detach(this.browser);\n    this.unregisterListener("GeckoView:GetRufoxProtection");\n    this.unregisterListener("GeckoView:GetQWACStatus");')
        s = once(s, '      case "GeckoView:GetQWACStatus":', '      case "GeckoView:GetRufoxProtection":\n        aCallback.onSuccess(JSON.stringify(RufoxProtection.snapshot(this.browser)));\n        break;\n      case "GeckoView:GetQWACStatus":')
        return once(s, '  onStateChange(...args) {', '  onStateChange(...args) {\n    RufoxProtection.progress(this.browser, ...args);\n    if (!(args[2] & Ci.nsIWebProgressListener.STATE_IS_NETWORK)) return;')
    def session(s):
        anchor = "  /**\n   * Determine if the current page uses a qualified website authentication certificate (QWAC)."
        return once(s, anchor, """  /**
   * Returns native CA policy diagnostics for requests observed in this session.
   *
   * @return JSON with the current page's domains, blocked count and SCT results.
   */
  @UiThread
  public @NonNull GeckoResult<String> rufoxProtectionStatus() {
    return mEventDispatcher.queryString("GeckoView:GetRufoxProtection");
  }

""" + anchor)
    transforms[Path('mobile/shared/modules/geckoview/GeckoViewProgress.sys.mjs')] = progress
    transforms[Path('mobile/shared/modules/geckoview/moz.build')] = lambda s: once(s, 'EXTRA_JS_MODULES += [', 'EXTRA_JS_MODULES += [\n    "RufoxProtection.sys.mjs",')
    transforms[Path('mobile/android/geckoview/src/main/java/org/mozilla/geckoview/GeckoSession.java')] = session

    def engine(s):
        return once(s, '    internal lateinit var geckoSession: GeckoSession', """    /** Returns this session's native CA diagnostics to trusted browser UI. */
    fun requestRufoxProtection(onResult: (String?) -> Unit) {
        geckoSession.rufoxProtectionStatus().accept(
            { value -> onResult(value) },
            { _ -> onResult(null) },
        )
    }

    internal lateinit var geckoSession: GeckoSession""")
    transforms[Path('mobile/android/android-components/components/browser/engine-gecko/src/main/java/mozilla/components/browser/engine/gecko/GeckoEngineSession.kt')] = engine

    transforms[Path('mobile/android/geckoview/api.txt')] = lambda s: once(s,
        '    method @AnyThread public void restoreState(@NonNull GeckoSession.SessionState);',
        '    method @AnyThread public void restoreState(@NonNull GeckoSession.SessionState);\n    method @NonNull @UiThread public GeckoResult<String> rufoxProtectionStatus();')
