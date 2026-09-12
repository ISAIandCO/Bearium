# Notices

Bearium is an independent modification of Mozilla Firefox for
Android. It is not produced, endorsed, or supported by Mozilla, the Firefox
project, the Ruthenium Chromium project, or the Russian Ministry of Digital
Development.

Mozilla Firefox source code is made available under the Mozilla Public License
2.0 and other licenses recorded in the upstream source tree. Firefox and the
Firefox logo are trademarks of the Mozilla Foundation. The Bearium launcher
icon is an independently drawn bear-and-flame vector illustration; it does not
use Firefox logo paths. Mozilla service names and source-code notices retain
their original owners. This project does not claim Mozilla endorsement or a
trademark license. Preserve upstream notices when redistributing binaries and
make the corresponding modified source available under its applicable licenses.

The Russian Trusted Root CA certificate is public certificate material. Its
expected DER SHA-256 fingerprint and official distribution URLs are recorded in
`certificates/ministry-ca-lock.json`.

The Android debug keystore in `signing/` is intentionally public. It provides
signature continuity only and does not authenticate the publisher: anyone can
use its private key to produce an APK accepted as a Bearium debug update.
