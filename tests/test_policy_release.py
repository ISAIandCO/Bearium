import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import resolve_policy_release as policy


class PolicyReleaseTest(unittest.TestCase):
    def release(self, tag, **extra):
        return dict(tag_name=tag, **extra)

    def choose(self, tags, old='same', current='same', version='155.0.1'):
        return policy.select_release(version, [self.release(t) for t in tags], current, lambda _: old)

    def test_new_firefox_uses_plain_version(self):
        self.assertEqual(self.choose(['155.0.1_SCTch2'], version='156.0'), ('156.0', False))

    def test_unchanged_data_skips_even_on_new_code_commit(self):
        self.assertEqual(self.choose(['155.0.1']), ('155.0.1', True))
        self.assertEqual(self.choose(['155.0.1', '155.0.1_SCTch']), ('155.0.1_SCTch', True))

    def test_changed_data_gets_distinct_numbered_releases(self):
        self.assertEqual(self.choose(['155.0.1'], current='new'), ('155.0.1_SCTch', False))
        self.assertEqual(self.choose(['155.0.1', '155.0.1_SCTch'], current='new'), ('155.0.1_SCTch2', False))
        self.assertEqual(self.choose(['155.0.1_SCTch9', '155.0.1_SCTch10'], current='new'), ('155.0.1_SCTch11', False))

    def test_compare_latest_policy_including_reversions(self):
        seen = []
        def previous(release):
            seen.append(release['tag_name'])
            return 'changed'
        self.assertEqual(policy.select_release('155.0.1', [self.release('155.0.1_SCTch2'),
            self.release('155.0.1')], 'original', previous), ('155.0.1_SCTch3', False))
        self.assertEqual(seen, ['155.0.1_SCTch2'])

    def test_drafts_reserve_tags_and_debug_releases_are_ignored(self):
        self.assertEqual(self.choose(['155.0.1_debug']), ('155.0.1', False))
        self.assertEqual(policy.select_release('155.0.1', [self.release('155.0.1'),
            self.release('155.0.1_SCTch', draft=True)], 'new', lambda _: 'old'), ('155.0.1_SCTch2', False))

    def test_legacy_without_metadata_migrates_once(self):
        self.assertEqual(self.choose(['155.0.1'], old=None), ('155.0.1_SCTch', False))
        self.assertIsNone(policy.published_fingerprint('owner/repo', self.release('155.0.1', assets=[])))

    def test_hash_ignores_json_format_but_detects_ct_and_root_changes(self):
        a = policy.fingerprint('{"operators": [], "version": "1"}', b'root')
        self.assertEqual(a, policy.fingerprint('{"version":"1","operators":[]}', b'root'))
        self.assertNotEqual(a, policy.fingerprint('{"operators": [], "version": "2"}', b'root'))
        self.assertNotEqual(a, policy.fingerprint('{"operators": [], "version": "1"}', b'new root'))

    def test_existing_source_commit_provides_legacy_fingerprint(self):
        import base64
        logs = (policy.ROOT / policy.LOGS).read_text()
        cert = (policy.ROOT / policy.CERT).read_text()
        def gh(*args):
            if args[0] == 'release':
                Path(args[-1], 'source.json').write_text(json.dumps({'source_commit': 'a' * 40}))
                return ''
            self.assertIn('?ref=' + 'a' * 40, args[1])
            content = logs if policy.LOGS in args[1] else cert
            return json.dumps({'encoding': 'base64', 'content': base64.b64encode(content.encode()).decode()})
        with patch.object(policy, 'gh', side_effect=gh):
            self.assertEqual(policy.published_fingerprint('owner/repo', self.release('155.0.1', assets=[{'name':'source.json'}])),
                policy.fingerprint(logs, policy.load_verified_certificate()))

    def test_outputs_preserve_play_source_and_increasing_version_code(self):
        original = {'version':'155.0.1', 'version_code':42, 'source_commit':'a' * 40, 'revision':'b' * 40}
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, 'source.json')
            source.write_text(json.dumps(original))
            real_read = Path.read_text
            def read(path, *args, **kwargs):
                return real_read(source if str(path) == 'source.json' else path, *args, **kwargs)
            output = io.StringIO()
            with patch.dict(os.environ, GITHUB_REPOSITORY='owner/repo'), patch.object(Path, 'read_text', read), \
                patch.object(policy, 'gh', return_value=json.dumps([[self.release('155.0.1')]])), \
                patch.object(policy, 'published_fingerprint', return_value='old'), contextlib.redirect_stdout(output):
                policy.main()
            values = dict(line.split('=', 1) for line in output.getvalue().splitlines())
            self.assertEqual(values['tag'], '155.0.1_SCTch')
            self.assertEqual(values['exists'], 'false')
            metadata = json.loads(values['source_json'])
            for key, value in original.items():
                self.assertEqual(metadata[key], value)
            self.assertEqual(metadata['release_tag'], values['tag'])
            self.assertRegex(metadata['policy_fingerprint'], '^[0-9a-f]{64}$')

    def test_api_failure_does_not_silently_select_new_release(self):
        with patch.object(policy, 'gh', side_effect=RuntimeError('API unavailable')):
            with self.assertRaises(RuntimeError):
                policy.published_fingerprint('owner/repo', self.release('155.0.1', assets=[{'name':'source.json'}]))


if __name__ == '__main__':
    unittest.main()
