#!/usr/bin/env python3
"""Export the approved UI artwork. Pillow is needed only when exporting, not building."""
from __future__ import annotations

import base64
import io
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1] / 'branding/android'
SOURCE = ROOT / 'source/ui'
OUTPUT = ROOT / 'ui/res'
# Original 155.0.1 VectorDrawable intrinsic sizes, in dp. Preserve proportions by
# fitting the approved artwork inside the original viewport, never stretching it.
ILLUSTRATIONS = {
    'firefox_as_default_banner_illustration': ('default_browser', 78, 53),
    'expressive_firefox': ('welcome', 35, 31),
    'fox_ai_on_state': ('ai_on', 62, 63),
    'fox_alert_crash_light': ('crash_light', 156, 137),
    'fox_alert_crash_dark': ('crash_dark', 155, 137),
    'fox_exclamation_alert': ('warning', 200, 200),
    'illustration_fox_box_inside_light': ('box', 176, 160),
    'ic_kit_bookmarks_empty_state': ('bookmarks', 200, 178),
    'ic_kit_heart': ('heart', 141, 150),
    'ic_kit_shield_off_state': ('shield_off', 58, 60),
    'ic_kit_shield_on_state': ('shield_on', 58, 60),
    'kit_expressive_full': ('mascot', 66, 62),
    'kit_head_protection_blocker_banner': ('protection_banner', 78, 78),
    'kit_search_error': ('search_error', 120, 139),
    'mozac_ic_kit_tab_groups': ('tab_groups', 144, 80),
    'mozac_ic_kit_tab_groups_list_view': ('tab_groups_list', 78, 68),
    'ic_fx_accounts_avatar': ('welcome', 72, 72),
    'ic_onboarding_welcome': ('welcome', 108, 108),
}
ALTERNATIVES = ('retro_2004', 'pixelated', 'cuddling', 'pride', 'flaming', 'minimal', 'momo', 'cool')
ANDROID = 'http://schemas.android.com/apk/res/android'


def fit(image: Image.Image, size: tuple[int, int], fraction: float = 1, pixelated: bool = False) -> Image.Image:
    image = image.convert('RGBA')
    image = image.crop(image.getbbox())
    scale = min(size[0] * fraction / image.width, size[1] * fraction / image.height)
    image = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                         Image.Resampling.NEAREST if pixelated else Image.Resampling.LANCZOS)
    canvas = Image.new('RGBA', size)
    canvas.alpha_composite(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
    return canvas


def adaptive(image: Image.Image, pixelated: bool = False) -> Image.Image:
    image = image.convert('RGBA')
    image = image.crop(image.getbbox())
    cx, cy = (image.width - 1) / 2, (image.height - 1) / 2
    alpha = image.getchannel('A')
    radius = max(((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                 for y in range(image.height) for x in range(image.width)
                 if alpha.getpixel((x, y)) > 8)
    # Fit the actual silhouette inside a 64dp circle in the 108dp canvas.
    # Unlike a fixed square inset, this preserves visual size for rounded art.
    scale = 128 / radius
    size = (round(image.width * scale), round(image.height * scale))
    image = image.resize(size, Image.Resampling.NEAREST if pixelated else Image.Resampling.LANCZOS)
    canvas = Image.new('RGBA', (432, 432))
    canvas.alpha_composite(image, ((432 - size[0]) // 2, (432 - size[1]) // 2))
    return canvas


def save(image: Image.Image, name: str, folder: str = 'drawable-xxxhdpi') -> None:
    path = OUTPUT / folder / f'{name}.webp'
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = io.BytesIO()
    image.save(encoded, format='WEBP', lossless=True, method=4)
    data = encoded.getvalue()
    if data[:4] != b'RIFF' or data[8:12] != b'WEBP':
        raise ValueError(f'WebP export failed: {name}')
    path.write_bytes(data)


def vector_background(name: str, color: str) -> None:
    # Compose's icon picker requires a vector/bitmap, not a <shape> wrapper.
    path = OUTPUT / 'drawable' / f'{name}.xml'
    path.write_text(f'<vector xmlns:android="{ANDROID}" android:width="108dp" android:height="108dp" '
                    f'android:viewportWidth="108" android:viewportHeight="108">'
                    f'<path android:fillColor="{color}" android:pathData="M0,0H108V108H0Z"/></vector>\n')


def export() -> None:
    (OUTPUT / 'drawable').mkdir(parents=True, exist_ok=True)
    for resource, (art, width, height) in ILLUSTRATIONS.items():
        save(fit(Image.open(SOURCE / f'{art}.webp'), (width * 4, height * 4)), resource)
    # Keep nodpi for existing nodpi bitmaps; their callers already size them.
    save(fit(Image.open(SOURCE / 'sleeping.webp'), (540, 309)), 'kit_sleeping_under_laptop', 'drawable-nodpi')
    logo = Image.open(ROOT / 'source/bearium-color.png')
    save(fit(logo, (432, 451)), 'ic_firefox')
    save(fit(logo, (432, 436), 0.61), 'ic_splash_logo')
    save(fit(logo, (160, 160)), 'ic_wordmark_logo', 'drawable-nodpi')
    for name in (*ALTERNATIVES, 'private'):
        image = Image.open(SOURCE / f'{name}.webp')
        if name != 'private':
            save(fit(image, (432, 432), pixelated=name == 'pixelated'), f'ic_{name}')
        foreground = 'ic_launcher_private_foreground' if name == 'private' else f'ic_launcher_foreground_{name}'
        save(adaptive(image, name == 'pixelated'), foreground)
    private_icon = OUTPUT / 'mipmap-anydpi/ic_launcher_private_round.xml'
    private_icon.parent.mkdir(parents=True, exist_ok=True)
    private_icon.write_text(f'<adaptive-icon xmlns:android="{ANDROID}">'
                            '<background android:drawable="@drawable/ic_launcher_private_background"/>'
                            '<foreground android:drawable="@drawable/ic_launcher_private_foreground"/>'
                            '<monochrome android:drawable="@drawable/ic_launcher_monochrome"/>'
                            '</adaptive-icon>\n')
    vector_background('ic_launcher_private_background', '#30030B')
    vector_background('ic_launcher_background_cool', '#FFF7EA')
    vector_background('ic_launcher_background_cuddling', '#FFF0DF')

    # Real vector monochrome, preserving the existing approved geometry. Status
    # icons have a 24dp intrinsic size, unlike the 108dp adaptive foreground.
    mono = ET.parse(ROOT / 'bearium-monochrome.xml')
    mono.getroot().set(f'{{{ANDROID}}}width', '24dp')
    mono.getroot().set(f'{{{ANDROID}}}height', '24dp')
    ET.register_namespace('android', ANDROID)
    mono.write(OUTPUT / 'drawable/ic_status_logo.xml', encoding='unicode')

    # Wordmark lettering is rasterized once with the bundled open-source font.
    # No runtime fonts, image generation, or network requests are needed in CI.
    font = ImageFont.truetype(str(ROOT / 'source/DejaVuSans-Bold.ttf'), 160)
    box = font.getbbox('Bearium')
    for theme, color in [('normal', '#19121F'), ('private', '#FFFFFF')]:
        text = Image.new('RGBA', (box[2] - box[0], box[3] - box[1]))
        ImageDraw.Draw(text).text((-box[0], -box[1]), 'Bearium', font=font, fill=color)
        save(text, f'ic_wordmark_text_{theme}', 'drawable-nodpi')
        wordmark = Image.new('RGBA', (1140, 320))
        wordmark.alpha_composite(fit(logo, (300, 300)), (0, 10))
        wordmark.alpha_composite(fit(text, (800, 205)), (330, 57))
        save(wordmark, f'ic_logo_wordmark_{theme}')
        if theme == 'private':
            save(wordmark, 'ic_logo_wordmark_normal', 'drawable-night-xxxhdpi')

    # The tab-group onboarding uses Lottie when animations are enabled. Replacing
    # only its static fallback leaves the animated fox visible. Reuse the same
    # approved bear with a gentle scale pulse; reduced motion keeps the WebP.
    art = Image.open(OUTPUT / 'drawable-xxxhdpi/mozac_ic_kit_tab_groups.webp')
    png = io.BytesIO()
    art.save(png, format='PNG')
    animation = {
        'v': '5.7.4', 'fr': 30, 'ip': 0, 'op': 60, 'w': 576, 'h': 320, 'nm': 'Bearium tab groups', 'ddd': 0,
        'assets': [{'id': 'bearium_tabs', 'w': 576, 'h': 320, 'u': '', 'e': 1,
                    'p': 'data:image/png;base64,' + base64.b64encode(png.getvalue()).decode()}],
        'layers': [{'ddd': 0, 'ind': 1, 'ty': 2, 'nm': 'Bearium', 'refId': 'bearium_tabs',
                    'ks': {'o': {'a': 0, 'k': 100}, 'r': {'a': 0, 'k': 0},
                           'p': {'a': 0, 'k': [288, 160, 0]}, 'a': {'a': 0, 'k': [288, 160, 0]},
                           's': {'a': 1, 'k': [
                               {'t': 0, 's': [98, 98, 100], 'e': [100, 100, 100], 'i': {'x': [0.67], 'y': [1]}, 'o': {'x': [0.33], 'y': [0]}},
                               {'t': 30, 's': [100, 100, 100], 'e': [98, 98, 100], 'i': {'x': [0.67], 'y': [1]}, 'o': {'x': [0.33], 'y': [0]}},
                               {'t': 60, 's': [98, 98, 100]}]}},
                    'ip': 0, 'op': 60, 'st': 0, 'sr': 1, 'bm': 0}],
    }
    (OUTPUT / 'raw').mkdir(exist_ok=True)
    (OUTPUT / 'raw/mozac_ic_kit_tab_groups_animation.json').write_text(json.dumps(animation, separators=(',', ':')) + '\n')


if __name__ == '__main__':
    export()
