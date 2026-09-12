#!/usr/bin/env python3
"""Validate the private signing identity before invoking Gradle; never print secrets."""
import base64
import hashlib
import os
import re
import subprocess
from pathlib import Path

PUBLIC_DEBUG_SHA256='d7a19050129bbb6e7af6f29dc899a123757ca226ea0ee3c7395c43527592035f'

def normalize(value):
    digest=value.replace(':','').lower().strip()
    if not re.fullmatch('[0-9a-f]{64}',digest): raise ValueError('Expected a SHA-256 certificate fingerprint')
    if digest == PUBLIC_DEBUG_SHA256: raise ValueError('Public debug certificate is forbidden for Play')
    return digest

def main():
    for name in ('BEARIUM_KEYSTORE_BASE64','BEARIUM_KEYSTORE','BEARIUM_STORE_PASSWORD','BEARIUM_KEY_PASSWORD','BEARIUM_KEY_ALIAS','BEARIUM_EXPECTED_CERT_SHA256'):
        if not os.environ.get(name): raise ValueError(f'Missing {name}')
    expected=normalize(os.environ['BEARIUM_EXPECTED_CERT_SHA256'])
    path=Path(os.environ['BEARIUM_KEYSTORE'])
    path.write_bytes(base64.b64decode(os.environ['BEARIUM_KEYSTORE_BASE64'],validate=True))
    path.chmod(0o600)
    result=subprocess.run(['keytool','-exportcert','-keystore',str(path),'-storepass:env','BEARIUM_STORE_PASSWORD','-alias',os.environ['BEARIUM_KEY_ALIAS']],capture_output=True,check=True)
    if hashlib.sha256(result.stdout).hexdigest()!=expected: raise ValueError('Signing certificate does not match the pinned fingerprint')
    print('Private signing certificate matches the pinned SHA-256')

if __name__=='__main__': main()
