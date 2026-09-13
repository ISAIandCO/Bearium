"""Exercise the patched Firefox 155 load-error actor, not a separate UI model."""
from pathlib import Path
import shutil
import subprocess
import unittest

from scripts.patch_firefox import TRANSFORMS


class ErrorPageTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js required')
    def test_native_warning_and_generic_error_routing(self):
        original = Path('tests/fixtures/LoadURIDelegateParent.sys.mjs').read_text()
        transform = TRANSFORMS[Path('mobile/shared/actors/LoadURIDelegateParent.sys.mjs')]
        patched = transform(original)
        self.assertEqual(transform(patched), patched)
        executable = '\n'.join(line for line in patched.splitlines() if not line.startswith('import '))
        executable = executable.replace('export class ', 'class ')
        program = '''
const assert = require('node:assert/strict');
class GeckoViewActorParent {}
let warning = 'about:bearium-protection#warning=1', calls = 0, retained = 0;
const pending = [], loads = [], principal = {};
const browser = {isConnected:true, loadURI(uri, options) {loads.push({uri,options});}};
const Cr = {NS_ERROR_ABORT:123};
const Ci = {nsIWebNavigation:{LOAD_FLAGS_REPLACE_HISTORY:1,LOAD_FLAGS_BYPASS_LOAD_URI_DELEGATE:2}};
const Components = {Exception(message, result) {return Object.assign(new Error(message),{result});}};
const Services = {
  tm:{dispatchToMainThread(fn) {pending.push(fn);}},
  io:{newURI(spec) {return {spec};}},
  scriptSecurityManager:{getSystemPrincipal() {return principal;}},
};
const RufoxProtection = {
  errorPage(b, target) {assert.equal(b,browser); assert.equal(target,'https://blocked.com/'); return warning;},
  retainErrorPage(b, target, uri) {assert.equal(uri,'data:text/html,error');retained++;},
};
''' + executable + '''
(async () => {
  const actor = new LoadURIDelegateParent();
  actor.browsingContext = {top:{embedderElement:browser},parent:null};
  actor.eventDispatcher = {async sendRequestForResult() {calls++;return 'data:text/html,error';}};
  const message = {name:'GeckoView:OnLoadError',data:{uri:'https://blocked.com/'}};
  await assert.rejects(actor.receiveMessage(message),error => error.result === Cr.NS_ERROR_ABORT);
  assert.equal(loads.length,0,'navigation is scheduled outside the failing load stack');
  pending.shift()();
  assert.equal(loads[0].uri.spec,warning);
  assert.equal(loads[0].options.triggeringPrincipal,principal);
  assert.equal(loads[0].options.loadFlags,3);
  await assert.rejects(actor.receiveMessage(message));
  browser.isConnected=false; pending.shift()();
  assert.equal(loads.length,1,'closed browser must not navigate');
  browser.isConnected=true;
  await assert.rejects(actor.receiveMessage(message));
  const savedWarning=warning; warning=null; pending.shift()(); warning=savedWarning;
  assert.equal(loads.length,1,'a superseding navigation cancels the warning');
  assert.equal(calls,0,'native block must not use generic Fenix page');
  actor.browsingContext.parent = {};
  assert.equal(await actor.receiveMessage(message),'data:text/html,error');
  assert.equal(retained,0,'subframe must not replace top-level warning');
  actor.browsingContext.parent = null; warning = null;
  assert.equal(await actor.receiveMessage(message),'data:text/html,error');
  assert.equal(retained,1,'retain the exact app error URI');
})().catch(error => {console.error(error);process.exitCode=1;});
'''
        subprocess.run(['node', '-e', program], check=True)
