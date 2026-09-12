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
    def load_error(s):
        s = once(s, 'import { GeckoViewActorParent }',
            'import { RufoxProtection } from "resource://gre/modules/RufoxProtection.sys.mjs";\nimport { GeckoViewActorParent }')
        return once(s, '''        return this.eventDispatcher.sendRequestForResult(
          "GeckoView:OnLoadError",
          data
        );''', '''        const browser = this.browsingContext.top.embedderElement;
        const topLevel = !this.browsingContext.parent;
        if (topLevel) {
          const warning = RufoxProtection.errorPage(browser, data.uri);
          if (warning) {
            // Never return a parent-only about URI to the content process:
            // nsDocShellLoadState rejects such loads as an IPDL protocol error.
            Services.tm.dispatchToMainThread(() => {
              if (!browser.isConnected ||
                  RufoxProtection.errorPage(browser, data.uri) !== warning) return;
              browser.loadURI(Services.io.newURI(warning), {
                triggeringPrincipal: Services.scriptSecurityManager.getSystemPrincipal(),
                loadFlags: Ci.nsIWebNavigation.LOAD_FLAGS_REPLACE_HISTORY |
                  Ci.nsIWebNavigation.LOAD_FLAGS_BYPASS_LOAD_URI_DELEGATE,
              });
            });
            // LoadURIDelegate.handleLoadError handles a rejected query by setting
            // NS_ERROR_ABORT, so the old docshell does not load a fallback error.
            throw Components.Exception("Rufox warning handled by browser chrome", Cr.NS_ERROR_ABORT);
          }
        }
        const response = await this.eventDispatcher.sendRequestForResult(
          "GeckoView:OnLoadError",
          data
        );
        if (topLevel) RufoxProtection.retainErrorPage(browser, data.uri, response);
        return response;''')
    transforms[Path('mobile/shared/actors/LoadURIDelegateParent.sys.mjs')] = load_error

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
    transforms[Path('mobile/shared/modules/geckoview/moz.build')] = lambda s: once(s, '    "Messaging.sys.mjs",', '    "Messaging.sys.mjs",\n    "RufoxProtection.sys.mjs",')
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
