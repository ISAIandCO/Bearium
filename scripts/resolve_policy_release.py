"""Select a release tag from the Firefox version and reviewed CT/root data."""
import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from scripts.patch_firefox import decode_pem, load_verified_certificate

ROOT = Path(__file__).resolve().parents[1]
LOGS = 'native/ct-log-list.json'
CERT = 'certificates/russian_trusted_root_ca.pem'


def fingerprint(logs, certificate):
    # Ignore JSON indentation and PEM wrapping, but include all reviewed log data.
    canonical = json.dumps(json.loads(logs), sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(canonical + b'\0' + certificate).hexdigest()


def release_number(version, tag):
    if tag == version:
        return 0
    match = re.fullmatch(re.escape(version) + r'_SCTch([2-9][0-9]*|1[0-9]+)?', tag)
    return int(match[1] or 1) if match else None


def select_release(version, releases, current, previous):
    matching = [(release_number(version, r['tag_name']), r) for r in releases]
    matching = [(n, r) for n, r in matching if n is not None]
    published = [(n, r) for n, r in matching if not r.get('draft') and not r.get('prerelease')]
    if not published:
        if matching:
            raise ValueError('A matching draft/prerelease must be resolved before publishing')
        return version, False
    _, latest = max(published, key=lambda pair: pair[0])
    if previous(latest) == current:
        return latest['tag_name'], True
    number = max(n for n, _ in matching) + 1
    return version + '_SCTch' + (str(number) if number > 1 else ''), False


def gh(*args):
    return subprocess.check_output(['gh', *args], text=True)


def published_fingerprint(repo, release):
    if not any(a['name'] == 'source.json' for a in release.get('assets', [])):
        # Old releases without provenance receive one migration rebuild.
        return None
    with tempfile.TemporaryDirectory() as directory:
        gh('release', 'download', release['tag_name'], '--repo', repo,
           '--pattern', 'source.json', '--dir', directory)
        source = json.loads((Path(directory) / 'source.json').read_text())
    if 'policy_fingerprint' in source:
        value = source['policy_fingerprint']
        if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
            raise ValueError('Invalid published policy fingerprint')
        return value
    # Existing Bearium releases already record the exact build commit. Compare
    # its data rather than rebuilding merely because the new field is absent.
    commit = source.get('source_commit', '')
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('Invalid published source commit')
    def read(path):
        data = json.loads(gh('api', f'repos/{repo}/contents/{path}?ref={commit}'))
        if data.get('encoding') != 'base64':
            raise ValueError('Unexpected repository file encoding')
        return base64.b64decode(data['content']).decode()
    return fingerprint(read(LOGS), decode_pem(read(CERT)))


def main():
    repo = os.environ['GITHUB_REPOSITORY']
    source = json.loads(Path('source.json').read_text())
    version = source['version']
    if not re.fullmatch(r'[1-9][0-9]*\.[0-9]+(?:\.[0-9]+)?', version):
        raise ValueError('Not a stable Firefox version')
    certificate = load_verified_certificate()
    current = fingerprint((ROOT / LOGS).read_text(), certificate)
    pages = json.loads(gh('api', '--paginate', '--slurp', f'repos/{repo}/releases?per_page=100'))
    releases = [release for page in pages for release in page]
    tag, exists = select_release(version, releases, current, lambda r: published_fingerprint(repo, r))
    source.update(policy_fingerprint=current, release_tag=tag,
                  certificate_sha256=hashlib.sha256(certificate).hexdigest())
    print('tag=' + tag)
    print('exists=' + str(exists).lower())
    print('source_json=' + json.dumps(source))


if __name__ == '__main__':
    main()
