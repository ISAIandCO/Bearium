# Bearium: GitHub APK, Google Play и биометрия на сайтах

Проверено по документации Google и Mozilla 12 сентября 2026 года.
Репозиторий: https://github.com/ISAIandCO/Bearium.
PR #19 включает исправление падения страницы CAnttRUst из PR #18.

## Что подготовлено

| Канал | Пакет | Подпись | Автоматизация |
|---|---|---|---|
| GitHub Releases | `app.bearium.browser` | Закрытый app-signing key владельца | Ежедневная проверка новой стабильной версии Mozilla, затем три APK |
| Google Play | `app.bearium.browser` | Тот же app-signing key, импортированный в Play | AAB после GitHub-выпуска; опциональная отправка в выбранный track |
| Локальная development-сборка | `app.bearium.browser.dev` | Публичный debug key | Не является production-релизом |
| Старый Rufox | `app.ruthenium.firefox` | Публичный debug key | Отдельная прежняя установка |

Основное имя — Bearium; deep link scheme — `bearium`; sharedUserId удалён.
Java/Kotlin namespace `org.mozilla.fenix` и внутренние имена CA-политики остаются
техническими именами кода. Векторные foreground/background и monochrome
нарисованы самостоятельно по мотивам концепта медведя с пламенем.

GitHub остаётся самостоятельным каналом: ему не нужны аккаунт Play, service
account, одобрение магазина или доступ Google к passkeys. Нужен только закрытый
ключ подписи. Ошибка Play не отменяет и не задерживает опубликованные APK.

## 1. Решить вопрос взаимозаменяемости до регистрации ключа в Play

Для обновления без удаления приложения нужны совпадающие package и допустимая
Android цепочка сертификатов, а также подходящий versionCode. Одна версия
Firefox или одинаковое имя файла этого не обеспечивают.

**Предлагаемая схема:** создать собственный app-signing key, подписывать им
GitHub APK и импортировать этот же ключ в Play App Signing. Для AAB желательно
создать отдельный upload key. Он удостоверяет загрузку в магазин, но не подпись
установленного приложения. Если отдельный upload key пока не настроен, workflow
умеет использовать app-signing key также для загрузки AAB.

| Выбор | Последствие |
|---|---|
| Свой app-signing key в GitHub и импорт того же ключа в Play | Возможны обновления между каналами без удаления, при совместимых версиях |
| Google генерирует свой app-signing key, GitHub подписывает другим | Эти установки с одним package не обновляют друг друга |
| Разные package у каналов | Устанавливаются рядом, данные раздельные |

APK из Play может состоять из splits, а GitHub APK — быть одним файлом.
Побайтовое совпадение не требуется. Но обновление с Play splits на standalone
APK и обратно нужно проверить на устройствах. Более старую версию Android
может не разрешить установить поверх новой. При ротации app-signing key
совместимость требует отдельной работы с signing lineage и версиями Android;
не включать автоматическую смену ключа без такой проверки.

Старый Rufox автоматически в Bearium не превратится. До удаления прежней
установки перенести доступные данные штатным экспортом/синхронизацией.
[Официальная документация Android о подписи](https://developer.android.com/studio/publish/app-signing).

## 2. Создать ключи и настроить GitHub

Команды для PowerShell; нужен JDK с `keytool`. Пароли вводятся интерактивно.

```powershell
keytool -genkeypair -v -keystore bearium-app-signing.jks -storetype JKS -alias bearium -keyalg RSA -keysize 3072 -validity 10000
keytool -list -v -keystore bearium-app-signing.jks -alias bearium
keytool -exportcert -rfc -keystore bearium-app-signing.jks -alias bearium -file bearium-app-signing-certificate.pem
```

Сохранить `.jks` и пароли в двух защищённых резервных копиях вне GitHub.
Скопировать SHA-256 из второй команды. Публичный `.pem` допустимо передать
Google; приватный `.jks`, его Base64 и пароли не коммитить и не класть в release.

В **Settings → Environments** создать `release-signing`, разрешить deployment
только из доверенной ветки `main`. В окружение добавить:

| Тип | Имя | Значение |
|---|---|---|
| Secret | `BEARIUM_KEYSTORE_BASE64` | Base64 нового app-signing keystore |
| Secret | `BEARIUM_STORE_PASSWORD` | Пароль хранилища |
| Secret | `BEARIUM_KEY_ALIAS` | `bearium` |
| Secret | `BEARIUM_KEY_PASSWORD` | Пароль ключа |
| Variable | `BEARIUM_SIGNING_CERT_SHA256` | SHA-256 app-signing certificate, с двоеточиями или без |

Получить Base64 в буфер обмена и после вставки очистить его:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes((Resolve-Path .\bearium-app-signing.jks))) | Set-Clipboard
# После вставки в GitHub Secret:
Set-Clipboard -Value ''
```

Base64 не является шифрованием. Production-сборка прекращается при отсутствующем
секрете, неверном SHA-256 или известном публичном debug certificate. Ключ
распаковывается временно с правами 0600 и удаляется после шага подписания.
Публичный debug keystore остаётся только для конфигурации upstream и локальных
dev-сборок; production artifact обязан пройти проверку закрытого сертификата.

Для отдельного upload key повторить команды с `bearium-upload.jks` и alias
`bearium-upload`. В **том же** окружении добавить все четыре secrets:
`BEARIUM_UPLOAD_KEYSTORE_BASE64`, `BEARIUM_UPLOAD_STORE_PASSWORD`,
`BEARIUM_UPLOAD_KEY_ALIAS`, `BEARIUM_UPLOAD_KEY_PASSWORD`, и variable
`BEARIUM_UPLOAD_CERT_SHA256`. Не задавать только часть этого набора.

## 3. Запустить GitHub APK и впервые загрузить Play

1. Слить PR #19. Он уже включает код исправления #18; отдельное повторное
   применение патча не нужно. PR #18 можно слить первым либо закрыть как
   включённый после принятия #19 — сам workflow PR не сливает.
2. Открыть **Actions → Build and release Bearium for Android → Run workflow**, `main`.
3. Дождаться трёх APK и GitHub Release с тегом версии Firefox, без `_debug`.
4. Скачать нужный APK, проверить SHA-256 и сертификат из соседнего отчёта.
5. Сохранить числовой ID workflow run из URL `actions/runs/…`.
6. Открыть **Build Bearium for Google Play → Run workflow**, указать этот ID
   в `build_run_id`, оставить `publish=false`.
7. Скачать artifact `Bearium-play-<versionCode>`: AAB, manifest, SHA-256,
   JSON-отчёт и сведения об исходниках.
8. В [Play Console](https://play.google.com/console/) создать приложение Bearium,
   пройти проверку аккаунта и заполнить сведения о реальном издателе.
9. При настройке **Play App Signing** выбрать использование/экспорт **существующего
   ключа**. Не выбирать генерацию нового Google key, если нужна взаимозаменяемость.
10. Скачать из консоли PEPK и предоставленный Google encryption key. Выполнить
    точную команду, показанную консолью, указав `bearium-app-signing.jks` и alias
    `bearium`; загрузить зашифрованный результат. Обычный `.jks` не публиковать.
11. Проверить совпадение SHA-256 **App signing key certificate** в Play с
    `BEARIUM_SIGNING_CERT_SHA256`. Если используется отдельный upload key,
    зарегистрировать его публичный сертификат по запросу консоли.
12. Загрузить AAB в **Testing → Internal testing**, добавить release notes
    и тестировщиков, открыть opt-in ссылку и установить приложение из Play.
13. Проверить сертификат установленного APK и обновление между каналами на
    тестовом устройстве. Internal app sharing для этой проверки не подходит:
    его сертификат может отличаться от app-signing certificate.

`versionCode` формируется автоматически из `github.run_number` APK workflow.
APK всех ABI и AAB используют одно число; `versionName` остаётся версией Firefox.
Не назначать независимые коды вручную в другом pipeline и не удалять/создавать
заново APK workflow со сбросом счётчика. Каждый новый ручной запуск APK workflow
увеличивает код; rerun существующего запуска сохраняет его. Для исправления уже
опубликованной версии запускать новый workflow, а не менять бинарник под прежним кодом.

AAB берёт **тот же commit Bearium, ревизию Mozilla и MOZ_BUILD_DATE** из
подтверждённого успешного запуска `main`. Другие ветки, PR-запуски и несовпадающие
сведения об исходниках отвергаются. APK-артефакты хранятся 30 дней: для более
поздней повторной сборки запустить новый APK workflow.

## 4. Включить автоматизацию Google Play

Ежедневный GitHub cron сохранён: **23:00 UTC**, то есть 04:00 UTC+5 следующего дня.
При уже выпущенной стабильной версии компиляция пропускается. При новой версии
формируются production APK и GitHub Release. Затем срабатывает Play workflow.
Если в проверке новой версии не было, у запуска нет release artifact и Play
также пропускается. Ошибка/задержка Play не меняет GitHub Release.

### Только автоматическая сборка AAB

В **Settings → Secrets and variables → Actions → Variables** установить
repository variable `BEARIUM_PLAY_ENABLED=true`. После каждого нового GitHub
выпуска будет автоматически собран проверенный AAB. Его можно загрузить вручную.

### Автоматическая отправка AAB

После первой успешной ручной публикации и заполнения деклараций:

1. Создать Google Cloud project и включить **Google Play Android Developer API**.
2. Создать service account. В Play Console → Users and permissions добавить его
   email, ограничить доступ приложением Bearium и выдать права на выбранную
   дорожку. Для Internal testing достаточно необходимых прав на тестовые releases;
   для production нужны соответствующие права публикации, не billing/admin.
3. Создать JSON key service account. В GitHub создать окружение `google-play`,
   ограничить веткой `main`, положить JSON целиком в secret
   `BEARIUM_PLAY_SERVICE_ACCOUNT_JSON`.
4. В окружении `google-play` задать переменные:

| Variable | Начальное значение | Назначение |
|---|---|---|
| `BEARIUM_PLAY_TRACK` | `internal` | Track ID: internal, alpha, beta, production или свой ID |
| `BEARIUM_PLAY_RELEASE_STATUS` | `completed` | Публикация на выбранной дорожке; `draft` оставляет черновик |
| `BEARIUM_PLAY_USER_FRACTION` | пусто | Только для `inProgress`, например `0.1` = 10% |

5. В repository variables установить `BEARIUM_PLAY_AUTO_UPLOAD=true`.
   `BEARIUM_PLAY_ENABLED=true` также должен быть включён.
6. Для первой проверки можно вручную запустить Play workflow с `build_run_id`
   и `publish=true`, не дожидаясь следующей версии Mozilla.
7. После тестирования и допуска аккаунта в production сменить track на
   `production`. Для постепенной раскатки установить status `inProgress` и
   fraction. Наличие другого незавершённого staged rollout останавливает новую
   публикацию, чтобы не заменить его автоматически.

Используется официальный `google-auth` и Android Publisher API: upload bundle,
update track, validate edit, commit. Повторная отправка не откатывает более новую
версию и не создаёт повторный release для уже установленного состояния track.
Активная проверка Google не отменяется: применяется `ERROR_IF_IN_REVIEW`.
При сетевой ошибке или незавершённой проверке повторить Play workflow с тем же
`build_run_id` после устранения причины. GitHub APK уже остаются доступными.
Проверка Google, первые декларации и допуск production не обходятся API.

[Настройка Android Publisher API](https://developers.google.com/android-publisher/getting_started),
[загрузка AAB](https://developers.google.com/android-publisher/api-ref/rest/v3/edits.bundles/upload),
[обновление track](https://developers.google.com/android-publisher/api-ref/rest/v3/edits.tracks/update),
[commit и поведение при review](https://developers.google.com/android-publisher/api-ref/rest/v3/edits/commit).

### Проверки production-сборки

Проверяются закрытый сертификат и целостность подписи, package, versionCode,
versionName, отсутствие debuggable/testOnly/sharedUserId, комплектность Gecko
для arm64/armv7/x86_64, ELF-архитектуры, 16 КБ PT_LOAD всех 64-битных `.so`,
bundletool validation, 16 КБ ZIP alignment и label временного APK. Временный
APK используется только для проверки; доставляемый AAB подписан закрытым ключом.
SHA-256 AAB повторно сверяется с отчётом перед отправкой в Google.

На 12.09.2026 обычному новому Android-приложению нужен **target SDK 36+**.
Проверяется реальный manifest. Для 16 КБ требуется также запуск на устройстве/
эмуляторе с `adb shell getconf PAGE_SIZE = 16384`; статические проверки не
заменяют тест загрузок, вкладок, CA-предупреждения и passkeys.
[Target API Google Play](https://support.google.com/googleplay/android-developer/answer/11926878?hl=en),
[Android 16 КБ](https://developer.android.com/guide/practices/page-sizes).

## 5. Заполнить карточку и декларации

1. Название: **Bearium**. Короткое описание, например:
   «Браузер с контролем сертификатов и понятными исключениями».
2. Описать отличие: ограничение Russian Trusted Root CA, проверка SCT,
   предупреждения и исключения. Не обещать абсолютную защиту, независимый
   аудит либо гарантированный вход по биометрии на любом сайте.
3. Загрузить `branding/android/bearium-play-512.png` как значок магазина.
   Сделать настоящие screenshots установленного приложения и feature graphic
   требуемого консолью размера. Коллаж концептов не является screenshot.
4. Указать контактный email владельца и доступный сайт поддержки.
5. Проверить и опубликовать `docs/PRIVACY.md`: ссылка в приложении уже ведёт
   на этот документ в `main`. При переносе политики на свой домен изменить
   `patch_support()` и ту же ссылку в Play Console.
6. В **App content** заполнить Privacy policy, Data safety, Ads, Content rating,
   Target audience и App access. Ответы брать из реальной сборки и сетевой
   проверки, а не из деклараций оригинального Firefox.
7. Просмотреть permissions в `Bearium.manifest.xml`. Если Google требует
   декларацию для разрешения, обосновать именно функцию браузера или убрать
   ненужное разрешение в исходниках. Проверить отдельно импорт/скачивание,
   доступ к файлам, камере, микрофону, геолокации и списку приложений.
8. Если включены сторонние аккаунты/сервисы, проверить их условия, данные,
   механизмы удаления аккаунта и необходимость соответствующих деклараций.
   Собственный аккаунт Bearium приложению для просмотра сайтов не нужен.
9. Проверить весь onboarding, настройки и экран «О приложении»: технические
   упоминания Firefox/Mozilla допустимы как атрибуция, но интерфейс не должен
   выдавать Bearium за продукт Mozilla или принятие договора с Mozilla.
10. Пройти pre-launch report и исправить выявленные crashes/ANR/ошибки доступа.

### Mozilla и лицензии

Самостоятельные название и знак устраняют очевидную зависимость брендинга от
логотипа Firefox, но не дают юридической гарантии отсутствия любых претензий.
Не заявлять связь, поддержку или одобрение Mozilla. Сохранять MPL-2.0,
third-party notices и доступ к точной версии исходников модифицированного
движка. Для каждого выпущенного AAB сохранять commit Bearium и ревизию Mozilla
из artifact; лучше делать отдельный git tag. Название Bearium отдельно
проверить на конфликты товарных знаков в целевых странах.
[Правила товарных знаков Mozilla](https://www.mozilla.org/en-US/foundation/trademarks/policy/),
[MPL 2.0 FAQ](https://www.mozilla.org/en-US/MPL/2.0/FAQ/).

Сохранённые Mozilla Accounts/Sync, AMO, поисковые провайдеры и их торговые марки
не становятся сервисами Bearium после переименования. Для их использования
могут требоваться собственные клиентские идентификаторы и согласование условий.

### Доступ в production

Для личных аккаунтов, созданных после 13.11.2023, Google требует закрытый тест:
минимум **12 тестировщиков, непрерывно подключённых 14 дней**, затем отдельную
заявку на production access. Internal testing этот этап не заменяет.
Для других аккаунтов следовать требованиям своей консоли.
[Официальные условия тестирования](https://support.google.com/googleplay/android-developer/answer/14151465?hl=en).

После допуска создать production release, выбрать страны, отправить на review
и начать с ограниченного rollout. Успешная CI-сборка не означает одобрения магазина.

## 6. Получить доступ к passkeys Google Password Manager

Веб-сайт вызывает WebAuthn; отпечаток/лицо/PIN подтверждает операцию у провайдера
ключей. Сайт получает криптографическое подтверждение, а не биометрические данные.
Публикация в Play сама по себе не включает privileged browser access.

1. После настройки Play App Signing открыть **App integrity / App signing**
   (название раздела может отличаться).
2. Скопировать **SHA-256 App signing key certificate**. Не SHA-256 upload key!
   При ротации ключа зарегистрировать все сертификаты, которыми Play подписывает
   версии для поддерживаемых Android. Их может быть больше одного.
3. Подготовить: `app.bearium.browser`, отпечатки, ссылку на Play listing/internal
   test, репозиторий, описание Gecko/WebAuthn flow, privacy policy и контакт.
4. Открыть [документацию privileged apps](https://developer.android.com/identity/sign-in/privileged-apps)
   и [форму Google](https://docs.google.com/forms/d/e/1FAIpQLScRuk9tTg0QPfSWl9SbpbIorX8xx2FCXlmoUYftCX2MxG4qyg/viewform).
5. Запросить доступ **Google Password Manager** для стороннего браузера,
   выполняющего `createCredential`/`getCredential` от origin посещаемого сайта.
6. В этой же заявке явно запросить/уточнить **legacy FIDO2 privileged browser API**
   для Android 13 и ниже, а также совместимость недискаверируемых credentials.
   Одобрение Credential Manager не следует считать автоматически одобрением
   всех старых API — это должен подтвердить Google.
7. Дождаться подтверждения регистрации нужных package/certificate. Для другого
   провайдера passkeys может потребоваться его собственное одобрение.
8. Проверить установленную через Internal testing сборку. Дополнительный
   `assetlinks.json` на каждом чужом сайте для браузерного origin не нужен.

Пример содержимого заявки (добавить реальные отпечатки и ссылки):

> Bearium is an independent Gecko-based Android web browser. Package:
> app.bearium.browser. We request privileged browser access to Google Password
> Manager for WebAuthn requests on behalf of HTTPS website origins. The browser
> uses upstream Gecko origin and RP ID validation and Android Credential Manager.
> App-signing certificate SHA-256: [Play app-signing fingerprint]. Source:
> https://github.com/ISAIandCO/Bearium. Please also confirm the approval process
> for the Google FIDO2 privileged browser API on Android 13 and earlier.

## 7. Что делает патч WebAuthn

Upstream `WebAuthnCredentialManager.java` уже использует Android 14+ API и
`setOrigin(origin)`. В `WebAuthnTokenManager.java` legacy API и проверка
наличия credentials ограничены `BuildConfig.MOZILLA_OFFICIAL`.

Патч разрешает выбор браузерного FIDO2 API также для package
`app.bearium.browser`, сохраняя официальный флаг Mozilla неизменным.
Dev-пакет это условие не проходит. Проверку сертификата и выдачу привилегий
по-прежнему выполняет Google; патч не обходит её, не подменяет origin и не
создаёт собственный аутентификатор. Отдельное Android-разрешение на отпечаток
не превращает браузер в привилегированный WebAuthn-клиент.

Путь на Android 14+: сайт → Gecko → Credential Manager → провайдер → системное
подтверждение. Старый GMS FIDO2 остаётся штатным fallback там, где upstream его
выбирает. Без Google Play Services/Credential Manager конкретный путь может
быть недоступен; наличие датчика отпечатка само по себе этого не исправляет.

[Исходник Gecko WebAuthn](https://github.com/mozilla-firefox/firefox/blob/release/mobile/android/geckoview/src/main/java/org/mozilla/geckoview/WebAuthnTokenManager.java),
[Credential Manager в Gecko](https://github.com/mozilla-firefox/firefox/blob/release/mobile/android/geckoview/src/main/java/org/mozilla/gecko/WebAuthnCredentialManager.java).

## 8. Проверить биометрию пошагово

1. На Android включить блокировку PIN/паролем и зарегистрировать отпечаток либо
   поддерживаемую сильную биометрию. Не всякая разблокировка лицом допустима
   для криптографических операций; возможен системный запрос PIN.
2. Обновить Google Play Services и выбранный провайдер passkeys, включить его
   в системных настройках паролей/ключей доступа.
3. Установить Bearium из Play Internal testing и проверить package/подпись.
4. На HTTPS-сайте с WebAuthn зарегистрировать новый passkey, завершить
   биометрическое подтверждение и проверить успешную регистрацию на сервере.
5. Выйти из аккаунта и войти этим ключом. Повторить после перезапуска браузера.
6. Проверить уже существующий passkey, созданный другим браузером в том же
   провайдере. Проверить выбор аккаунта при нескольких credentials.
7. Проверить отмену диалога, отсутствие credential, PIN fallback, обычный и
   приватный режимы. Браузер не должен падать или сообщать об успехе при отмене.
8. Повторить на Android 14/15/16, отдельно Android 13 для legacy API, и на всех
   заявленных ABI. На 16 КБ устройстве проверить не только запуск, но и создание
   ключа/вход, загрузки, вкладки и страницу CA-предупреждения.
9. Проверить целевой банковский сайт. Если его код скрывает кнопку по User-Agent,
   не использует WebAuthn либо ограничивает поддерживаемые браузеры, одобрение
   Google не заставит эту кнопку появиться. Такой случай исследовать отдельно.

Для диагностики с компьютера (PowerShell, установлен Android SDK platform-tools):

```powershell
adb shell pm path app.bearium.browser
# Скопировать путь к base.apk из вывода предыдущей команды:
adb pull /data/app/ПУТЬ_ИЗ_ВЫВОДА/base.apk bearium-installed.apk
# apksigner находится в Android SDK build-tools:
apksigner verify --print-certs bearium-installed.apk
adb logcat -c
# Воспроизвести ошибку, затем:
adb logcat -d -v threadtime | Select-String 'WebAuthn|Fido|CredentialManager|WebAuthnCredMan' | Set-Content -Encoding utf8 bearium-webauthn.log
```

Полный logcat может содержать адреса сайтов и идентификаторы аккаунта. Для
issue оставлять только относящийся к ошибке фрагмент без токенов и личных данных.

`NotAllowedError` не доказывает отсутствие allowlist: это также отмена, таймаут,
несовпадение RP/origin или отсутствие подходящего credential. Сначала сравнить
подпись установленного приложения с заявкой, затем проверить логи и запрос сайта.
Не ослаблять TLS, origin/RP ID validation или проверки CA ради появления диалога.

## Граница готовности

Код и автоматические проверки подготавливают выпуск, но окончательная готовность
подтверждается только успешным AAB, установкой из Play, тестами на устройствах,
заполненными декларациями и решениями Google по магазину и privileged access.
Закрытые ключи, аккаунт Play и заявку Google владелец оформляет сам по шагам выше.
При отказе Google собственный authenticator на Keystore/BiometricPrompt — отдельный
проект с аудитом безопасности, а не безопасный однострочный обход.
