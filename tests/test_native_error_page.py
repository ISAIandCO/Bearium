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
let warning = 'about:rufox-protection#warning=1', calls = 0, retained = 0;
const browser = {};
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
  assert.equal(await actor.receiveMessage(message),warning);
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
