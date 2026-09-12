# Public Bearium debug key

`rfirefox-debug.keystore` is an intentionally public Android debug keystore used
only for upstream build configuration and local development builds. Production
GitHub APKs and Play bundles must use private signing material.

Configuration:

- store type: JKS;
- alias: `androiddebugkey`;
- store password: `android`;
- key password: `android`;
- certificate SHA-256:
  `d7a19050129bbb6e7af6f29dc899a123757ca226ea0ee3c7395c43527592035f`.

The workflow passes this file to the Fenix build through the
`RFIREFOX_DEBUG_KEYSTORE` environment variable. It verifies both the keystore
certificate and the certificate in every resulting APK against
`debug-key-lock.json`/the pinned workflow value.

This key provides signature continuity between Bearium debug builds, but no
publisher authentication: anyone who clones the repository has the private key
and can sign an APK accepted as an update. Never reuse this key for production.

Production APK использует закрытый app-signing key из `release-signing`.
Play AAB может использовать отдельный upload key; app-signing key в Play
должен совпадать с GitHub для совместимых обновлений.
[Настройка ключей и публикация](../docs/GOOGLE_PLAY_WEBAUTHN.md).
Публичный ключ из этого каталога запрещён для production.
