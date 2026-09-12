# Bearium for Android

![Bearium](branding/android/bearium-xxxhdpi.webp)

**Google Play и WebAuthn:** [пошаговая инструкция](docs/GOOGLE_PLAY_WEBAUTHN.md).
Production: `app.bearium.browser`, dev: `app.bearium.browser.dev`.

Независимая Android-сборка стабильного Firefox с ограниченной поддержкой
`Russian Trusted Root CA`. По умолчанию корень принимается для HTTPS-сайтов
в `.ru`, `.рф` и `.su` при наличии подходящего SCT. Пользователь может разрешить
сайт, который блокирует эта дополнительная политика.

> Нативная интеграция CAnttRUst реализуется в этой ветке; сборка и отладка отложены. Это описание
> изменений ветки, а не возможностей ранее опубликованных APK.

Проект не является форком всего дерева Firefox. В репозитории хранятся
проверяемый сертификат, скрипты патчирования, тесты и GitHub Actions. При каждом
релизном запуске workflow получает свежий стабильный исходный changeset Mozilla,
накладывает патч и собирает отдельное Android-приложение.

> [!IMPORTANT]
> Проект не связан с Mozilla, командой Ruthenium Chromium или Минцифры России.
> Добавление центра сертификации меняет модель доверия браузера. Используйте
> сборку только если понимаете последствия и доверяете исходникам и CI этого
> репозитория.

## Что именно изменено

| Область | Изменение |
|---|---|
| Дополнительный CA | В Gecko встраивается закреплённая копия `Russian Trusted Root CA` |
| Назначение доверия | Корень добавляется только для `VerifyUsage::TLSServer`; проверки клиентских и почтовых сертификатов не изменяются |
| Ограничение имён | Проверяется адрес запроса: `.ru`, `.xn--p1ai`, `.su`; другие адреса требуют исключения |
| Прозрачность сертификатов | SCT из сертификата, TLS и stapled OCSP проверяются по отдельному списку журналов; требуется Yandex |
| Решение пользователя | «Щит» → «Защита сертификатов»: одноразовый переход для вкладки и URL, выбор доменов галочками, массовые исключения на сеанс/час/постоянно; приватные разрешения хранятся в памяти |
| Диагностика | Счётчик вкладки с `99+`, причины отказов, операторы и сведения о SCT; усиленный режим в настройках защиты |
| Повторные соединения | Для этого УЦ отключено использование сохранённых TLS-токенов и объединение разных имён в одном соединении |
| Обычная PKI-проверка | Проверки имени хоста, подписей, срока, EKU и отзыва Firefox остаются включёнными |
| Android-пакет | `applicationId` production — `app.bearium.browser`, поэтому приложение устанавливается отдельно от официального Firefox |
| Брендинг приложения | Имя приложения — `Bearium`, deep-link scheme — `bearium`; общий UID с Firefox не используется |
| Иконка | Самостоятельный медведь с пламенем; предусмотрены square, round, adaptive и monochrome-варианты |
| Релиз | APK подписываются закрытым ключом владельца; AAB для Play использует тот же пакет и согласованный versionCode |

Патч изменяет в полученном дереве Mozilla следующие файлы:

- `security/certverifier/CertVerifier.h` и `.cpp` — отдельный список корней
  только для TLS server verification;
- `security/certverifier/RutheniumRoot.h` и `BeariumCTLogs.h` — закреплённый
  корень и отдельные ключи журналов;
- `security/manager/ssl/nsNSSComponent.cpp`, `CommonSocketControl.cpp` и
  `netwerk/base/SSLTokensCache.cpp` — обновление политики и повторные соединения;
- `docshell`, `toolkit/content` и панель доверия Fenix — внутренняя страница
  `about:rufox-protection` и переход к ней из «щита» и страницы ошибки;
- `mobile/android/fenix/app/build.gradle` — независимый application ID,
  shared user ID и deep-link scheme;
- `mobile/android/fenix/app/src/main/res/values/static_strings.xml` и release-
  вариант файла — имя приложения;
- `mobile/android/fenix/app/src/main/res/drawable/ic_launcher_foreground.xml`,
  release-foreground, monochrome drawable и release WebP по всем Android
  density — векторная иконка медведя с пламенем.

Готовые normal/round legacy-ресурсы находятся в `branding/android/`. Для
adaptive icon патчер устанавливает прозрачный цветной foreground в безопасной
зоне, а для themed icon — отдельный monochrome-силуэт, который Android окрашивает
системной палитрой. Альтернативные иконки встроенной функции выбора Fenix не
изменяются.

Скрипт `scripts/patch_firefox.py` применяет каждую замену только при однозначном
совпадении ожидаемого upstream-кода. Если Mozilla изменила соответствующий
участок, патч завершается ошибкой вместо молчаливой сборки с неполной политикой.

## Граница доверия сертификату

Сертификат хранится в `certificates/russian_trusted_root_ca.pem`. Перед генерацией
C++-заголовка проверяется его DER SHA-256:

```text
d26d2d0231b7c39f92cc738512ba54103519e4405d68b5bd703e9788ca8ecf31
```

Ожидаемый хэш и две исходные ссылки закреплены в
`certificates/ministry-ca-lock.json`. Сетевой сертификат во время сборки не
скачивается: используется проверенная копия из репозитория. Несовпадение хэша
останавливает патч.

Ограничения относятся только к цепочке, построенной через этот дополнительный
корень. Они не сужают обычное хранилище Mozilla. Сертификат также не добавляется
в системное хранилище Android и не даёт другим приложениям нового доверия.

### Если сайт заблокирован

Откройте в «щите» **Защита сертификатов · CAnttRUst** или воспользуйтесь ссылкой
на странице ошибки. Выберите, что разрешить: выход за российские зоны,
отсутствие подходящего SCT или оба ограничения. Нажмите **Разрешить постоянно**
и вернитесь на сайт. Несколько адресов можно внести по одному в строке.

Исключение не распространяется на поддомены и другие УЦ. Оно не отменяет
самостоятельные ошибки TLS — например, просроченный сертификат или неверное
имя. HSTS не запрещает изменение дополнительной политики Bearium.

При изменении разрешений браузер закрывает сетевые соединения, чтобы новая
политика начала действовать. Текущие загрузки могут прерваться. Техническое
описание и проверки — в [native/README.md](native/README.md).

## Выбор стабильных исходников

`https://hg-edge.mozilla.org/mozilla-central` — основное дерево разработки
Mozilla и источник Firefox Nightly. Его `tip` не равен последнему стабильному
Firefox, поэтому непосредственно собирать `tip` и называть результат stable
нельзя.

`scripts/resolve_firefox_source.py` выполняет строгую последовательность:

1. читает `LATEST_FIREFOX_VERSION` из официального Firefox Product Details;
2. строит имя Android-тега вида `FIREFOX-ANDROID_153_0_4_RELEASE`;
3. находит ровно этот тег в официальной release-ветке
   `https://hg-edge.mozilla.org/releases/mozilla-release`;
4. проверяет 40-символьный Mercurial changeset и скачивает архив именно этой
   ревизии;
5. после распаковки сверяет `browser/config/version.txt` с выбранной версией.

Таким образом, код остаётся кодом официального монорепозитория Firefox
(GeckoView, Fenix и Android Components), но берётся из стабилизированной ветки,
а не из движущегося Nightly tip. При отсутствии согласованного release-тега
сборка останавливается.

## Автоматизация и релизы

GitHub и Google Play — два канала распространения одного production-приложения.
GitHub не зависит от проверки и доступности магазина.

| Workflow | Запуск | Результат |
|---|---|---|
| Validate Ruthenium patches | PR, push main, вручную | Тесты и совместимость патчей с текущим stable |
| Build and release Bearium for Android | Каждый день в 23:00 UTC, вручную | При новой версии Mozilla — подписанные APK arm64/armv7/x86_64 и GitHub Release |
| Build Bearium for Google Play | После нового APK-выпуска при включённой настройке; вручную по ID выпуска | Проверенный AAB из той же ревизии; опционально отправка в Play |

Если версия Firefox уже опубликована, ежедневная проверка не компилирует её
повторно. Ручной запуск позволяет пересобрать текущую версию после исправления.
Тег и имя GitHub Release соответствуют версии Firefox, без `_debug`.
`versionCode` берётся из счётчика запусков APK workflow и совпадает между ABI
и Play. APK каждого ABI содержит собственный заново собранный Gecko.

Перед первым production-выпуском настроить закрытый ключ в окружении
`release-signing`. Публичный ключ `signing/rfirefox-debug.keystore` используется
только при конфигурации upstream и для локальной разработки; production APK
с этим сертификатом не проходит проверку.

По умолчанию Play не отправляет ничего в магазин. Автоматическую сборку AAB
включает `BEARIUM_PLAY_ENABLED=true`, отправку — `BEARIUM_PLAY_AUTO_UPLOAD=true`.
Начальная дорожка — Internal testing. Ключи, service account, production track
и правила поэтапной раскатки описаны в [пошаговой инструкции](docs/GOOGLE_PLAY_WEBAUTHN.md).

## Установка и обновление

В GitHub Releases выбрать APK своей архитектуры, скачать и открыть на Android.
Рядом публикуются SHA-256 и отчёт о сертификате подписи. APK доступен независимо
от Google Play. Для установки из магазина приложение сначала должно пройти
тестирование и review Google.

Для обновлений между каналами без удаления приложения импортировать собственный
app-signing key в Play App Signing: Google Play и GitHub должны подписывать
установку одним сертификатом. Upload key может быть отдельным. Совместимость
перехода между Play splits и GitHub APK проверить на устройстве; более старый
versionCode не предназначен для установки поверх нового.

Старый Rufox (`app.ruthenium.firefox`) и локальная dev-сборка
(`app.bearium.browser.dev`) имеют другие package и отдельные данные.

## Локальная проверка патчей

Быстрые тесты и определение текущего стабильного источника:

```bash
python3 -m unittest discover -v
python3 scripts/resolve_firefox_source.py --format json
```

Проверка точек патча на удалённом release-теге без скачивания всего архива:

```bash
python3 scripts/patch_firefox.py \
  --check-remote \
  https://hg-edge.mozilla.org/releases/mozilla-release/raw-file/FIREFOX-ANDROID_153_0_4_RELEASE
```

Применение к уже полученному исходному дереву:

```bash
python3 scripts/patch_firefox.py --source /path/to/firefox-source
```

Полная сборка Firefox может потребовать 8+ CPU, 32 ГБ RAM, около 100 ГБ
свободного SSD и несколько часов. GitHub workflow ограничен шестью часами и
чистит только известные крупные каталоги одноразового GitHub-hosted runner.

Шаг Mozilla bootstrap не имеет отдельного таймаута и может использовать всё
время сборочного job. Во время его работы workflow раз в минуту выводит
heartbeat, использование диска и памяти, а также снимок процессов. Полный вывод
и итоговая диагностика всегда сохраняются на семь дней в artifact
`bootstrap-diagnostics-<версия>-<run id>`. Heartbeat только наблюдает за
процессом и не прерывает его.

Перед запуском `mach bootstrap` wrapper временно снимает экспортированный
`MOZCONFIG`: bootstrap должен сам создать стандартный
`firefox-source/mozconfig`. Путь снова доступен следующему шагу workflow, где в
него добавляются release-настройки. Это не даёт `mach` остановиться на проверке
ещё не существующего файла до установки toolchain.

После полного `mach build` workflow останавливает оставшиеся Gradle daemon-процессы.
При сборке release APK выставляется штатный флаг Mozilla
`GRADLE_INVOKED_WITHIN_MACH_BUILD=1`: поскольку Gecko уже полностью собран и
разложен в object directory, это исключает вложенный повторный `mach build faster`.
Fenix запускается с `--no-daemon --max-workers=2`, чтобы R8 и сжатие ресурсов не
соседствовали со вторым Gradle heap на 16-ГБ GitHub-hosted runner.

## Ограничения и риски

- Это не официальный Firefox и не результат аудита Mozilla.
- Патч покрыт unit-тестами и fail-closed проверками якорей, но полноценная
  интеграционная TLS-матрица на реальных цепочках ещё должна быть добавлена.
- Сборка не является воспроизводимой побитово: toolchain и часть зависимостей
  устанавливаются Mozilla bootstrap/Gradle во время job.
- Публичный debug-ключ локальной разработки обеспечивает совместимость dev-обновлений, но не
  подтверждает издателя: подписать совместимое обновление может любой владелец
  копии репозитория. Это осознанное временное ограничение.

## Источники и референсы

- [Ruthenium for Android](https://github.com/rutheniumteam/ruthenium-android) —
  исходный Chromium-проект и референс идеи ограниченного доверия;
- [статья на Habr](https://habr.com/ru/articles/1070548/) — описание задачи и
  мотивации;
- [Mozilla `mozilla-central`](https://hg-edge.mozilla.org/mozilla-central) —
  основное development-дерево;
- [Mozilla `mozilla-release`](https://hg-edge.mozilla.org/releases/mozilla-release) —
  источник точного stable changeset;
- [Firefox Product Details](https://product-details.mozilla.org/1.0/firefox_versions.json) —
  официальный номер актуального стабильного Firefox;
- [Firefox for Android source docs](https://firefox-source-docs.mozilla.org/mobile/android/) и
  [сборка Fenix](https://firefox-source-docs.mozilla.org/mobile/android/fenix.html);
- [Russian Trusted Root CA (PEM)](https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt) —
  первичный источник сертификата;
- [RFC 5280, Name Constraints](https://www.rfc-editor.org/rfc/rfc5280#section-4.2.1.10) —
  формат ограничений имён;
- [NekoBox_SF release workflow](https://github.com/ISAIandCO/NekoBox_SF/blob/main/.github/workflows/android-release-to-github-release.yml) —
  референс схемы публикации артефактов;
- [Mozilla Trademark Guidelines](https://www.mozilla.org/foundation/trademarks/policy/).

## Лицензия и уведомления

Код этого репозитория распространяется по MPL-2.0. Исходный код Firefox имеет
MPL-2.0 и другие лицензии, перечисленные в его дереве. Дополнительные юридические
уведомления находятся в `NOTICE.md`. Firefox и логотип Firefox являются
товарными знаками Mozilla Foundation.
