#!/usr/bin/env python3
"""Accept only successful main-branch APK runs; never execute PR artifacts."""
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path


def gh(*args):
    return subprocess.check_output(['gh',*args],text=True)


def validate_source(run, source):
    if (run.get('conclusion')!='success' or run.get('head_branch')!='main'
        or run.get('path','').split('@')[0]!='.github/workflows/build-android.yml'
        or run.get('event') not in ('schedule','workflow_dispatch')):
        raise ValueError('Play accepts only successful production APK runs from main')
    if source.get('source_commit')!=run.get('head_sha') or not re.fullmatch('[0-9a-f]{40}',source['source_commit']):
        raise ValueError('Source artifact does not match originating commit')
    if source.get('version_code')!=run.get('run_number') or not 1<=source['version_code']<=2100000000:
        raise ValueError('Version code does not match APK workflow run number')
    if not re.fullmatch('[0-9a-f]{40}',source.get('revision','')) or not re.fullmatch('[0-9]{14}',source.get('build_date','')):
        raise ValueError('Invalid source revision or build date')
    if not re.fullmatch(r'[1-9][0-9]*\.[0-9]+(?:\.[0-9]+)?',source.get('version','')):
        raise ValueError('Not a stable Firefox version')
    expected='https://hg-edge.mozilla.org/releases/mozilla-release/archive/'+source['revision']+'.zip'
    if source.get('archive_url')!=expected: raise ValueError('Unexpected Mozilla archive URL')


def main():
    run_id=os.environ['BUILD_RUN_ID']
    if not run_id.isdecimal(): raise ValueError('build_run_id must be numeric')
    repo=os.environ['GITHUB_REPOSITORY']
    run=json.loads(gh('api',f'repos/{repo}/actions/runs/{run_id}'))
    # Verify trust before downloading anything from this run.
    if run.get('conclusion')!='success' or run.get('head_branch')!='main' or run.get('path','').split('@')[0]!='.github/workflows/build-android.yml':
        raise ValueError('Not a successful main-branch APK workflow')
    artifacts=json.loads(gh('api',f'repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100'))['artifacts']
    matches=[a for a in artifacts if a['name']=='bearium-release-source' and not a['expired']]
    if not matches:
        print('eligible=false') # Daily no-new-version runs have no release artifact.
        return
    if len(matches)!=1: raise ValueError('Ambiguous release source artifact')
    with tempfile.TemporaryDirectory() as temp:
        gh('run','download',run_id,'--repo',repo,'--name','bearium-release-source','--dir',temp)
        source=json.loads((Path(temp)/'source.json').read_text())
    validate_source(run,source)
    print('eligible=true')
    print('run_id='+run_id)
    print('source_json='+json.dumps(source))
    for key in ('source_commit','version_code','build_date','archive_url','revision','version'):
        print(f'{key}={source[key]}')

if __name__=='__main__': main()
