#!/usr/bin/env python3
"""Validate the signed AAB, metadata, all Gecko ABIs and 16 KB ELF/ZIP alignment."""
import argparse
import hashlib
import json
import os
import re
import struct
import subprocess
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
try:
    from .prepare_play_signing import normalize
except ImportError:
    from prepare_play_signing import normalize
try:
    from .verify_android_apk import ABI_ELF_IDENTITIES, REQUIRED_GECKO_LIBRARIES, MINIMUM_XUL_SIZE, _read_elf_identity
except ImportError:
    from verify_android_apk import ABI_ELF_IDENTITIES, REQUIRED_GECKO_LIBRARIES, MINIMUM_XUL_SIZE, _read_elf_identity

BUNDLETOOL_URL='https://github.com/google/bundletool/releases/download/1.18.3/bundletool-all-1.18.3.jar'
BUNDLETOOL_SHA256='a099cfa1543f55593bc2ed16a70a7c67fe54b1747bb7301f37fdfd6d91028e29'
ANDROID='{http://schemas.android.com/apk/res/android}'
ABIS={'arm64-v8a','armeabi-v7a','x86_64'}

def run(*args):
    return subprocess.check_output(args,text=True,stderr=subprocess.STDOUT)

def validate_elf(data,abi):
    if _read_elf_identity(data[:20])!=ABI_ELF_IDENTITIES[abi][:2]:
        raise ValueError(f'Wrong ELF architecture for {abi}')
    if abi=='armeabi-v7a': return
    phoff=struct.unpack_from('<Q',data,32)[0]
    entsize,num=struct.unpack_from('<HH',data,54)
    if entsize<56 or phoff+entsize*num>len(data): raise ValueError('Invalid ELF program headers')
    loads=0
    for i in range(num):
        p=phoff+i*entsize
        if struct.unpack_from('<I',data,p)[0]!=1: continue
        loads+=1
        offset,vaddr=struct.unpack_from('<QQ',data,p+8)
        align=struct.unpack_from('<Q',data,p+48)[0]
        if align<16384 or align & (align-1) or (vaddr-offset)%16384:
            raise ValueError(f'{abi}: PT_LOAD is not aligned for 16 KB pages')
    if not loads: raise ValueError('ELF has no loadable segments')

def validate_manifest(xml,code,version):
    root=ET.fromstring(xml)
    if root.get('package')!='app.bearium.browser': raise ValueError('Wrong production package')
    if root.get(ANDROID+'versionCode')!=str(code): raise ValueError('Wrong versionCode')
    if root.get(ANDROID+'versionName')!=version: raise ValueError('Wrong Firefox versionName')
    if int(root.find('uses-sdk').get(ANDROID+'targetSdkVersion','0'))<36: raise ValueError('Google Play requires targetSdk >= 36 as of 2026-08-31')
    if root.get(ANDROID+'sharedUserId'): raise ValueError('Production must not share an Android UID')
    app=root.find('application')
    if app.get(ANDROID+'debuggable','false')!='false': raise ValueError('Debuggable production application')
    if app.get(ANDROID+'testOnly','false')!='false': raise ValueError('testOnly production application')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--aab',type=Path,required=True)
    p.add_argument('--version-code',type=int,required=True)
    p.add_argument('--version-name',required=True)
    p.add_argument('--certificate',required=True)
    a=p.parse_args();expected=normalize(a.certificate)
    # keytool reads the signer; jarsigner verifies entry integrity separately.
    cert=run('keytool','-J-Duser.language=en','-printcert','-jarfile',str(a.aab))
    fingerprints=re.findall(r'SHA256:\s*([0-9A-F:]+)',cert)
    if len(fingerprints)!=1 or normalize(fingerprints[0])!=expected: raise ValueError('Unexpected AAB signer')
    verification=run('jarsigner','-J-Duser.language=en','-verify','-verbose','-certs',str(a.aab))
    if 'jar verified.' not in verification or 'unsigned entries' in verification.lower(): raise ValueError('AAB signature verification failed')
    with tempfile.TemporaryDirectory() as temp:
        temp=Path(temp);jar=temp/'bundletool.jar'
        urllib.request.urlretrieve(BUNDLETOOL_URL,jar)
        if hashlib.sha256(jar.read_bytes()).hexdigest()!=BUNDLETOOL_SHA256: raise ValueError('bundletool checksum mismatch')
        def bundle(*args): return run('java','-jar',str(jar),*args)
        bundle('validate','--bundle='+str(a.aab))
        manifest=bundle('dump','manifest','--bundle='+str(a.aab),'--module=base')
        validate_manifest(manifest,a.version_code,a.version_name)
        config=bundle('dump','config','--bundle='+str(a.aab))
        if 'PAGE_ALIGNMENT_16K' not in config: raise ValueError('Bundle does not request 16 KB ZIP alignment')
        with zipfile.ZipFile(a.aab) as z:
            names=[n for n in z.namelist() if n.startswith('base/lib/') and n.endswith('.so')]
            if {n.split('/')[2] for n in names}!=ABIS: raise ValueError('Bundle ABI set is incomplete')
            for abi in ABIS:
                for lib in REQUIRED_GECKO_LIBRARIES:
                    info=z.getinfo(f'base/lib/{abi}/{lib}')
                    if lib=='libxul.so' and info.file_size<MINIMUM_XUL_SIZE: raise ValueError('Gecko engine is truncated')
            for n in names:
                try: validate_elf(z.read(n),n.split('/')[2])
                except ValueError as e: raise ValueError(f'{n}: {e}') from e
        # This temporary APK is only an inspection product, signed by bundletool's
        # local test key. The distributed AAB signer was checked above.
        apks=temp/'inspection.apks'
        bundle('build-apks','--bundle='+str(a.aab),'--output='+str(apks),'--mode=universal', '--ks='+os.environ['RFIREFOX_DEBUG_KEYSTORE'], '--ks-key-alias=androiddebugkey', '--ks-pass=pass:android', '--key-pass=pass:android')
        with zipfile.ZipFile(apks) as z: z.extract('universal.apk',temp)
        sdk=Path.home()/'.mozbuild'
        def tool(name):
            paths=sorted(sdk.rglob(name))
            if not paths: raise ValueError(f'Missing Android SDK tool {name}')
            return str(paths[-1])
        badging=run(tool('aapt2'),'dump','badging',str(temp/'universal.apk'))
        if "application-label:'Bearium'" not in badging: raise ValueError('Incorrect launcher label')
        run(tool('zipalign'),'-c','-P','16','-v','4',str(temp/'universal.apk'))
        report={'aabSha256':hashlib.sha256(a.aab.read_bytes()).hexdigest(),'package':'app.bearium.browser','versionCode':a.version_code,'versionName':a.version_name,'uploadCertificateSha256':expected,'abis':sorted(ABIS),'nativeLibraries':len(names),'static16KBChecks':'passed','deviceTesting':'required'}
        a.aab.with_suffix('.validation.json').write_text(json.dumps(report,indent=2)+'\n')
        a.aab.with_suffix('.manifest.xml').write_text(manifest)
        print(json.dumps(report,indent=2))

if __name__=='__main__': main()
