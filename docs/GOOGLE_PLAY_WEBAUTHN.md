# Bearium: Google Play и вход на сайты по биометрии

Проверено по документации Google и Mozilla 12 сентября 2026 года.
Репозиторий: https://github.com/ISAIandCO/Bearium

## Что подготовлено в коде

| Вариант | Пакет | Подпись | Назначение |
|---|---|---|---|
| Google Play | `app.bearium.browser` | Закрытый upload key для AAB; Play app signing key для установки | Production и Play testing |
| GitHub development | `app.bearium.browser.dev` | Старый публичный debug key | Тестирование, не Google Play |
| Старый Rufox | `app.ruthenium.firefox` | Старый публичный debug key | Отдельная прежняя установка |

Имя приложения — Bearium. Deep link scheme — `bearium`. Java/Kotlin namespace
`org.mozilla.fenix` и внутренние имена CA-политики сохранены: они являются
частью кода, а не идентификатором устанавливаемого приложения. Общий Android UID
удалён: production и dev не должны делить UID при разных подписях.

Новая векторная иконка содержит медведя и пламя, отдельные foreground/background,
монохромный VectorDrawable и SVG. Заменены launcher, splash и основные логотипы
приложения. Авторские и лицензионные уведомления Mozilla сохранены.

В сборке выключены Fenix `TELEMETRY` и `CRASH_REPORTING`. Это не утверждение
«браузер вообще никуда не обращается»: сайты, поиск, обновления расширений,
Safe Browsing, удалённые настройки и включаемая пользователем синхронизация
требуют отдельного учёта в декларации данных.

`Build Bearium for Google Play` сначала собирает проверенные APK трёх ABI из
одной ревизии с одним `MOZ_BUILD_DATE`. Затем отдельно собирает arm64 Gecko и
AAB, добавляя только недостающие Gecko-библиотеки двух других архитектур из
APK этого же запуска. Сторонние библиотеки включаются штатными зависимостями
Gradle. Это четыре компиляции Gecko, три из них параллельные; сборка затратная.
Подмена движка готовым официальным AAR не используется: CA-патчи сохраняются.

Проверки AAB: сертификат и целостность подписи, package, версия, target SDK,
отсутствие debuggable/testOnly, комплектность Gecko для arm64/armv7/x86_64,
ELF-архитектура, 16 КБ PT_LOAD для 64-битных библиотек, bundletool validation,
16 КБ ZIP alignment и имя приложения в временном APK. Этот APK предназначен
только для проверки; он не публикуется. Результат — `Bearium.aab` и отчёты.

## 1. Подготовить аккаунт и окончательную identity

1. Создать или открыть [Google Play Console](https://play.google.com/console/).
2. Выбрать корректный тип аккаунта, пройти предложенную Google проверку
   личности/организации и устройства. Указывать реальные данные и страну;
   доступность регистрации и платежей проверять в своей консоли.
3. Создать приложение **Bearium**, тип «Приложение», категорию «Связь» либо
   другую подходящую категорию браузера, выбрать основной язык и бесплатность.
4. До первой загрузки зафиксировать пакет `app.bearium.browser`: после
   публикации заменить package существующего приложения нельзя.
5. Выбрать **Play App Signing → ключ подписи генерирует Google**.
   Ни публичный debug key, ни его копия не подходят для production.

Это новое приложение: Android не перенесёт автоматически историю, пароли,
закладки и исключения из Rufox. До удаления старой установки перенести
доступные данные штатным экспортом/синхронизацией. Dev и production могут
стоять рядом; их данные изолированы.

## 2. Создать upload key у себя

Нужен JDK с `keytool`. Команды ниже подходят для PowerShell; пароли вводятся
интерактивно и не попадают в историю команды.

```powershell
keytool -genkeypair -v -keystore bearium-upload.jks -storetype JKS -alias bearium-upload -keyalg RSA -keysize 3072 -validity 10000
keytool -list -v -keystore bearium-upload.jks -alias bearium-upload
keytool -exportcert -rfc -keystore bearium-upload.jks -alias bearium-upload -file bearium-upload-certificate.pem
```

1. Задать сильные пароли хранилища и ключа. Сохранить их в менеджере паролей.
2. Скопировать SHA-256 из второй команды. Это **upload certificate**, не
   будущий сертификат установленного из Play приложения.
3. Сделать две защищённые резервные копии `.jks` и паролей вне репозитория.
4. Получить Base64 для GitHub Secret:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes((Resolve-Path .\bearium-upload.jks))) | Set-Clipboard
```

Base64 — тот же секретный ключ, а не шифрование. После вставки очистить буфер:

```powershell
Set-Clipboard -Value ''
```

`.pem` с публичным сертификатом допустимо передать Google. `.jks`, пароли и
Base64 нельзя коммитить, отправлять в issue или прикладывать к релизу.

[Разница между upload key и app signing key](https://developer.android.com/studio/publish/app-signing).

## 3. Настроить GitHub

В **Bearium → Settings → Environments** создать окружение `google-play`.
Ограничить deployment branches доверенной веткой `main`. Это окружение
выбирает финальный job; произвольной ветке не следует выдавать signing secrets.

В нём создать **Environment secrets**:

| Имя | Значение |
|---|---|
| `BEARIUM_KEYSTORE_BASE64` | Base64 содержимого нового `.jks`, без переносов |
| `BEARIUM_STORE_PASSWORD` | Пароль хранилища |
| `BEARIUM_KEY_ALIAS` | `bearium-upload` |
| `BEARIUM_KEY_PASSWORD` | Пароль ключа |

Создать **Environment variable**, не secret:

| Имя | Значение |
|---|---|
| `BEARIUM_UPLOAD_CERT_SHA256` | SHA-256 upload certificate; с двоеточиями или без |

Production-сборка прекращается при отсутствующих секретах, неверном отпечатке
или попытке использовать известный публичный debug certificate. Ключ временно
распаковывается с правами 0600 и удаляется после шага. В artifact он не входит.

## 4. Собрать и загрузить AAB

1. Слить PR с подготовкой Bearium в `main`.
2. Открыть **Actions → Build Bearium for Google Play → Run workflow**.
3. Выбрать `main`. Для первой загрузки указать `version_code = 1`.
4. Для следующей загрузки указать 2, затем 3 и так далее. Число обязано быть
   больше всех уже загруженных в Play кодов, включая тестовые дорожки.
   Повторный запуск неудавшейся сборки допустим с прежним кодом, если AAB ещё
   не загружался. Версия Firefox остаётся в `versionName`.
5. Дождаться завершения `native` и `bundle`. Скачать artifact
   `Bearium-play-<version_code>`. В нём должны быть AAB, SHA-256, manifest,
   JSON-отчёт проверок, ревизия Mozilla и commit Bearium.
6. В Play Console открыть **Testing → Internal testing → Create new release**.
7. Завершить настройку Play App Signing, загрузить `Bearium.aab`, добавить
   release notes и сохранить выпуск.
8. Добавить свой Google-аккаунт в список тестировщиков, открыть opt-in ссылку
   на устройстве и установить приложение именно через Google Play.

Не брать для этой проверки APK из обычных GitHub Releases. Не использовать
**Internal app sharing** вместо Internal testing: у app sharing может быть
другая подпись, не та, которую нужно заявлять для WebAuthn.

На 12.09.2026 для новых обычных Android-приложений требуется **target SDK 36+**.
Сборка проверяет фактический manifest и остановится при меньшем значении;
не маскировать несовместимый upstream заменой числа в готовом manifest.
[Требования Google к target API](https://support.google.com/googleplay/android-developer/answer/11926878?hl=en).

16 КБ проверяются для всех 64-битных `.so`, включая сторонние зависимости.
При отказе проверка укажет библиотеку: её нужно пересобрать/обновить, а не
отключать проверку. Статического выравнивания недостаточно — запуск и WebAuthn
проверить также на устройстве/эмуляторе с `adb shell getconf PAGE_SIZE = 16384`.
[Документация Android по 16 КБ](https://developer.android.com/guide/practices/page-sizes).

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
Закрытый ключ, аккаунт Play и заявку Google владелец оформляет сам по шагам выше.
При отказе Google собственный authenticator на Keystore/BiometricPrompt — отдельный
проект с аудитом безопасности, а не безопасный однострочный обход.
