import base64
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import native_policy, patch_firefox


class NativePolicyTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('g++'), 'g++ required for native policy checks')
    def test_actual_cpp_host_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = directory + '/policy-test'
            subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            '-I', str(native_policy.NATIVE), 'tests/native-policy-hosts.cpp',
                            '-o', binary], cwd=native_policy.ROOT, check=True)
            subprocess.run([binary], check=True)

    def test_log_snapshot_is_self_consistent(self):
        data = json.loads((native_policy.NATIVE / 'ct-log-list.json').read_text())
        ids = []
        for operator in data['operators']:
            for log in operator['logs']:
                key = base64.b64decode(log['key'], validate=True)
                identity = base64.b64decode(log['log_id'], validate=True)
                self.assertEqual(hashlib.sha256(key).digest(), identity)
                ids.append(identity)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn('kRufoxCTLogs', native_policy.log_header())

    def test_bad_log_identity_stops_generation(self):
        data = json.loads((native_policy.NATIVE / 'ct-log-list.json').read_text())
        data['operators'][0]['logs'][0]['log_id'] = base64.b64encode(bytes(32)).decode()
        with patch.object(native_policy.json, 'loads', return_value=data):
            with self.assertRaises(ValueError):
                native_policy.log_header()

    def test_upstream_change_does_not_silently_skip_patch(self):
        for transform in (native_policy.verifier_cpp, native_policy.verifier_h,
                          native_policy.common_socket, native_policy.token_cache,
                          native_policy.request_interceptor, native_policy.trust_panel):
            with self.subTest(transform=transform.__name__):
                with self.assertRaises(ValueError):
                    transform('upstream source changed')

    def test_no_imposed_name_constraints_remain(self):
        self.assertNotIn(patch_firefox.TRUST_DOMAIN_CPP, patch_firefox.TRANSFORMS)
        self.assertNotIn(patch_firefox.TRUST_DOMAIN_H, patch_firefox.TRANSFORMS)

    @unittest.skipUnless(shutil.which('node'), 'Node.js required for UI checks')
    def test_privileged_permission_ui(self):
        subprocess.run(['node', 'tests/native-policy-ui.cjs'], cwd=native_policy.ROOT, check=True)

    @unittest.skipUnless(shutil.which('node'), 'Node.js required for service checks')
    def test_tab_diagnostics_and_permission_expiry(self):
        subprocess.run(['node', 'tests/native-policy-service.cjs'], cwd=native_policy.ROOT, check=True)
