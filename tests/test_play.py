import struct
import unittest
from scripts.prepare_play_signing import normalize, PUBLIC_DEBUG_SHA256
from scripts.verify_play_bundle import validate_elf, validate_manifest
from scripts.patch_firefox import patch_webauthn, patch_release_manifest

class PlayTests(unittest.TestCase):
    def test_public_or_invalid_signer_is_rejected(self):
        for value in (PUBLIC_DEBUG_SHA256, 'bad', ':'.join(PUBLIC_DEBUG_SHA256[i:i+2] for i in range(0,64,2))):
            with self.assertRaises(ValueError): normalize(value)
        self.assertEqual(normalize('AB'*32),'ab'*32)

    def test_16kb_elf_alignment(self):
        elf=bytearray(120);elf[:6]=b'\x7fELF\x02\x01'
        struct.pack_into('<H',elf,18,183)
        struct.pack_into('<Q',elf,32,64)
        struct.pack_into('<HH',elf,54,56,1)
        struct.pack_into('<I',elf,64,1)
        struct.pack_into('<Q',elf,112,16384)
        validate_elf(elf,'arm64-v8a')
        struct.pack_into('<Q',elf,112,4096)
        with self.assertRaises(ValueError): validate_elf(elf,'arm64-v8a')
        struct.pack_into('<Q',elf,112,16384)
        struct.pack_into('<Q',elf,72,1)
        with self.assertRaises(ValueError): validate_elf(elf,'arm64-v8a')

    def test_production_metadata(self):
        xml='<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="app.bearium.browser" android:versionCode="5" android:versionName="155.0.1"><uses-sdk android:targetSdkVersion="36"/><application android:debuggable="false"/></manifest>'
        validate_manifest(xml,5,'155.0.1')
        for bad in (xml.replace('browser"','browser.dev"'),xml.replace('="36"','="35"'),xml.replace('="false"','="true"'),xml.replace('="5"','="4"')):
            with self.assertRaises(ValueError): validate_manifest(bad,5,'155.0.1')

    def test_browser_api_is_independent_of_official_build_flag(self):
        original='\n'.join(['if (BuildConfig.MOZILLA_OFFICIAL) {}']*3+['if (!BuildConfig.MOZILLA_OFFICIAL) {}'])
        patched=patch_webauthn(original)
        self.assertEqual(patched.count('"app.bearium.browser"'),4)
        self.assertEqual(patch_webauthn(patched),patched)
        self.assertNotIn('browser.dev',patched)
        with self.assertRaises(ValueError): patch_webauthn('upstream changed')

    def test_new_packages_do_not_share_uid(self):
        xml='<manifest xmlns:android="http://schemas.android.com/apk/res/android"\n    android:sharedUserId="${sharedUserId}"></manifest>'
        self.assertNotIn('android:sharedUserId',patch_release_manifest(xml))

if __name__=='__main__': unittest.main()
