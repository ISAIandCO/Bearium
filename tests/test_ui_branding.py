"""Guard resource-merger precedence and non-vector Compose artwork."""
import base64
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from scripts import patch_firefox


class UIBrandingTest(unittest.TestCase):
    def test_no_fox_survives_a_density_night_or_release_override(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / 'mobile/android/fenix/app/src'
            # Deliberately conflicting source-set, density and theme qualifiers:
            # anydpi vectors and nodpi release artwork win over plain bitmaps.
            names = ('ic_firefox', 'expressive_firefox', 'fox_ai_on_state',
                     'fox_alert_crash_light', 'fox_alert_crash_dark', 'fox_exclamation_alert',
                     'illustration_fox_box_inside_light', 'ic_kit_bookmarks_empty_state',
                     'ic_kit_heart', 'ic_kit_shield_on_state', 'ic_kit_shield_off_state',
                     'kit_expressive_full', 'kit_search_error', 'kit_head_protection_blocker_banner',
                     'mozac_ic_kit_tab_groups', 'mozac_ic_kit_tab_groups_list_view',
                     'firefox_as_default_banner_illustration', 'ic_wordmark_logo',
                     'ic_wordmark_text_normal', 'ic_wordmark_text_private',
                     'ic_logo_wordmark_normal', 'ic_logo_wordmark_private',
                     'ic_fx_accounts_avatar', 'ic_launcher_private_foreground')
            for variant in ('main', 'release', 'beta'):
                for folder in ('drawable', 'drawable-anydpi', 'drawable-mdpi',
                               'drawable-nodpi', 'drawable-night', 'drawable-night-xxhdpi'):
                    target = app / variant / 'res' / folder
                    target.mkdir(parents=True, exist_ok=True)
                    for name in names:
                        (target / f'{name}.xml').write_text('<vector/>')
                (app / variant / 'res/drawable/ic_high_five.xml').write_text('unchanged')
            patch_firefox.rebrand_resources(root)
            for variant in ('main', 'release'):
                res = app / variant / 'res'
                for name in names:
                    matches = list(res.glob(f'drawable*/{name}.*'))
                    self.assertTrue(matches, name)
                    self.assertTrue(all(path.suffix == '.webp' for path in matches), name)
                self.assertEqual((res / 'drawable/ic_high_five.xml').read_text(), 'unchanged')
                self.assertTrue((res / 'drawable-night-xxxhdpi/ic_logo_wordmark_normal.webp').exists())
            self.assertEqual((app / 'beta/res/drawable-anydpi/ic_firefox.xml').read_text(), '<vector/>')
            self.assertEqual(patch_firefox.rebrand_resources(root), [])

    def test_picker_artwork_and_adaptive_foregrounds_are_both_present(self):
        res = patch_firefox.UI_RESOURCE_DIR
        for name in ('retro_2004', 'pixelated', 'cuddling', 'pride', 'flaming', 'minimal', 'momo', 'cool'):
            for resource in (f'ic_{name}', f'ic_launcher_foreground_{name}'):
                path = res / f'drawable-xxxhdpi/{resource}.webp'
                data = path.read_bytes()
                self.assertEqual(data[:4], b'RIFF')
                self.assertEqual(data[8:12], b'WEBP')
                self.assertEqual(int.from_bytes(data[4:8], 'little') + 8, len(data))
            # Foregrounds need safe-area padding unlike icon-picker previews.
            self.assertNotEqual((res / f'drawable-xxxhdpi/ic_{name}.webp').read_bytes(),
                                (res / f'drawable-xxxhdpi/ic_launcher_foreground_{name}.webp').read_bytes())
        status = ET.parse(res / 'drawable/ic_status_logo.xml').getroot()
        self.assertEqual(status.tag, 'vector')
        self.assertEqual(status.get('{http://schemas.android.com/apk/res/android}width'), '24dp')

    def test_animated_path_embeds_the_bear_and_needs_no_remote_assets(self):
        path = patch_firefox.UI_RESOURCE_DIR / 'raw/mozac_ic_kit_tab_groups_animation.json'
        data = json.loads(path.read_text())
        self.assertEqual(data['nm'], 'Bearium tab groups')
        self.assertEqual(data['layers'][0]['refId'], data['assets'][0]['id'])
        self.assertEqual(data['assets'][0]['e'], 1)
        embedded = data['assets'][0]['p']
        self.assertTrue(embedded.startswith('data:image/png;base64,'))
        self.assertEqual(base64.b64decode(embedded.split(',', 1)[1])[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual((data['w'], data['h']), (576, 320))
        self.assertNotIn('http', embedded)


if __name__ == '__main__':
    unittest.main()
