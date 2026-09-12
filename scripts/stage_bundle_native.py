#!/usr/bin/env python3
"""Stage only missing Gecko AAR libraries from same-run, verified ABI APKs."""
import argparse
import zipfile
from pathlib import Path
try:
    from .verify_android_apk import validate_apk, REQUIRED_GECKO_LIBRARIES
except ImportError:
    from verify_android_apk import validate_apk, REQUIRED_GECKO_LIBRARIES


def stage(apk_dir, source, objdir, output):
    # Reuse GeckoView's existing jniLibs source directory. No duplicate Fenix
    # source set, fat-AAR flag or substitute engine dependency is necessary.
    native_dir = source / objdir / 'dist/geckoview/lib'
    if output.resolve() != native_dir.resolve():
        raise ValueError('Output must be the rebuilt GeckoView native staging directory')
    names = {p.name for p in (native_dir / 'arm64-v8a').glob('*.so')}
    if not set(REQUIRED_GECKO_LIBRARIES) <= names:
        raise ValueError(f'Cannot find complete rebuilt Gecko inventory in {native_dir}')
    for abi in ('armeabi-v7a', 'x86_64'):
        apks = list(apk_dir.glob(f'*{abi}-release.apk'))
        if len(apks) != 1:
            raise ValueError(f'Expected exactly one same-run {abi} APK')
        validate_apk(apks[0], abi)
        with zipfile.ZipFile(apks[0]) as z:
            for name in sorted(names):
                data = z.read(f'lib/{abi}/{name}')
                target = output / abi / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
    print(f'Staged {len(names)} Gecko libraries per additional ABI')

if __name__ == '__main__':
    p=argparse.ArgumentParser()
    for key in ('apk-dir','source','objdir','output'): p.add_argument('--'+key,required=True)
    a=p.parse_args()
    stage(Path(a.apk_dir),Path(a.source),a.objdir,Path(a.output))
