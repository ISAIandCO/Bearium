# Запросы подготовки иллюстраций, 13 октября 2026

Режим: встроенный imagegen, редактирование существующего рисунка,
`transparent_background=true`. Финальные исходники: `../source/ui/*.webp`;
ресурсы Android: `res/`. Pillow используется для изменения разрешения,
сохранения альфа-канала и экспорта WebP без потерь, а не для вырезания фона.
У крупного Android-ресурса виджета RGB экспортируется с quality=95,
альфа-канал сохраняется без потерь. Его исходник остаётся lossless WebP.

## Очистка краёв

Исходники: `sleeping`, `welcome`, `warning`, `default_browser`, `tab_groups`,
`shield_off`, `shield_on`, `mascot`, `protection_banner`, `crash_dark`, `heart`,
`search_error`, `ai_on`, `bookmarks`, `box`, `tab_groups_list`.

```text
Use case: background-extraction
Asset type: existing Bearium Android UI illustration; input image is the edit target.
Primary request: Clean only the cutout and alpha boundary. Remove every residual white/gray matte halo, jagged white edge, and rectangular colored/white background streak outside the actual bear and its props. Produce real transparent background and smooth antialiased edges that work on a dark purple UI.
Constraints: preserve the exact red-orange bear identity, rounded bear ears, expression, pose, flame-shaped fur, proportions, colors, cream muzzle and intentional highlights. Preserve all existing props and their design, positions and colors. Do not add or remove actual objects. Keep original composition. No new outline, shadow, glow, text, backdrop, checkerboard, or white border. Transparency must extend between separate elements.
All cream muzzle areas and highlights INSIDE the bear/props must stay fully
opaque; no holes inside objects. Remove all stray isolated speckles outside
objects. Only actual background outside silhouette is transparent.
```

Для `sleeping` дополнительно сохранены закрытые глаза, поза, красный ноутбук
и знак медведя на его крышке. Для `mascot` и `default_browser` отдельной
итерацией восстановлен случайно прозрачный участок переносицы:

```text
Repair ONLY the small accidental transparent triangular hole on the bridge
of the muzzle between the forehead and dark nose, just below the far eye.
Fill that hole with fully opaque warm ivory/cream matching the adjacent
muzzle highlight, giving one continuous natural solid muzzle. Keep the
bear design, expression, pose, props, palette and composition unchanged.
Preserve transparent background and no white halo.
```

Светлый вариант сбоя с розовым кругом не заменён результатом генерации:
при проверке сохранён существующий исходник `crash_light.webp`.

## Сцены устройств

Исходники: `devices_sync`, `devices_sync_error`, `onboarding_sync`,
`onboarding_sync_qr`, `onboarding_widget`, `onboarding_search_widget`.
Вход 1 — соответствующая иллюстрация Firefox 157.0.1, вход 2 — существующий
медведь Bearium (`mascot` либо основной `ic_firefox` для логотипа виджета).
Сцена QR является декоративной подсказкой, а не кодом авторизации.

```text
Use case: precise-object-edit
Asset type: Bearium Android onboarding / sync illustration.
Input image 1 is the edit target, image 2 is the approved Bearium bear identity reference.
Primary request: Replace every orange pointed-ear FOX mascot in image 1, including its visible head, body or tail on device screens, with the red-orange rounded-ear BEAR from image 2. Replace any Firefox product logo with a small Bearium bear logo in exactly that logo location, and replace the word Firefox with Bearium if that product name appears.
Constraints: preserve the rest of image 1's exact composition, device shapes, rounded rectangles, search fields, icons, hands, arrow/error marks, scanning frame and QR illustration. Do not replace the instructional scene with a generic bear portrait. Keep original flat device UI style and purple palette; preserve the bear's red-orange fur, cream muzzle and rounded ears. No new objects, no unrelated text. Cream muzzle and device screens are solid opaque. Preserve genuinely transparent area outside the illustrated scene, clean antialiased cutout, no white edge, no glow, no matte background, no stray speckles.
```
