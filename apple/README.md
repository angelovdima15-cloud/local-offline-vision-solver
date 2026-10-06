# iPhone + Apple Watch MVP

При отсутствии Mac доступна подготовленная GitHub macOS build-проверка в `.github/workflows/validate.yml`, включая unsigned device IPA с вложенным Watch app. Она ещё не запускалась; IPA требует подписи перед установкой. Для клиента с Windows см. [DELIVERY.md](../DELIVERY.md), включая Sideloadly для iPhone и непроверенную установку Watch.

Исходники native приложений без внешних Swift-пакетов. `LocalVisionSolver.xcodeproj` содержит `VisionPhone` (iOS 17+) и companion `VisionWatch` (watchOS 10+), общую библиотеку чтения пакета и shared schemes. Проект создан детерминированным `scripts/generate_xcode_project.py`; структурная проверка выполнена на Windows, **компиляция Apple SDK ещё не выполнена**.

## Сборка на Mac

1. Перенесите весь проект на Mac с Xcode, подходящим версиям iOS/watchOS устройств.
2. Создайте `apple/Signing.local.xcconfig`:

```xcconfig
VISION_IOS_BUNDLE_ID = your.unique.LocalVisionSolver
VISION_WATCH_BUNDLE_ID = $(VISION_IOS_BUNDLE_ID).watchapp
DEVELOPMENT_TEAM = YOURTEAMID
```

3. Откройте `apple/LocalVisionSolver.xcodeproj`. Проверьте Signing & Capabilities обоих targets. Development Team нужен для установки средствами Apple; приложение не содержит account/login workflow.
4. Подключите iPhone и сопряжённые часы, включите Developer Mode по запросу Xcode. Выберите `VisionPhone` и настоящий iPhone, Build/Run; затем `VisionWatch` и соответствующие часы, Build/Run.
5. Проверьте companion id, установку обоих приложений и разрешения Camera/Local Network/Watch notifications.

Предварительные проверки без подписи устройств:

```bash
bash scripts/check-apple.sh
```

Скрипт выполняет `swift test` для общего пакета и сборку обеих simulator targets. **Симулятор не подтверждает WatchConnectivity file transfer**: это проверяется на настоящей паре устройств. [Apple transferFile documentation](https://developer.apple.com/documentation/watchconnectivity/wcsession/transferfile(_:metadata:)).

После добавления новых Swift-файлов обновите Xcode-проект:

```bash
python3 scripts/generate_xcode_project.py
```

## iPhone workflow

При запуске — camera, Ultra Wide при наличии, JPEG с приоритетом качества и максимальными поддерживаемыми размерами активного формата. Tap-to-focus. Принятый снимок сохраняется без повторного JPEG-кодирования и уменьшения. Preview/Retake/Use Photo, Add Page, удаление и изменение порядка до Solve. На ошибке backend доступно Edit / retake pages с сохранением остальных снимков и новым session id.

Автоматическое обнаружение `_visionsolver._tcp`; статус в Connection. Ручной private LAN IPv4/.local hostname — fallback. HTTP redirects отключены. Сведения о Bonjour и local-network permissions: [Apple local network privacy](https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy).

После Solve порядок фиксируется. Повторная загрузка безопасна: session id и номера страниц сохраняются, сервер сравнивает SHA256. Состояние задачи, фотографии и результаты сохраняются в Application Support, исключённом из cloud backup. Для MVP upload/polling выполняются при открытом приложении; при уходе в background ожидание приостанавливается, затем продолжается при возвращении либо через Resume. Полноценный background URLSession — следующий этап надёжности.

Телефон сохраняет structured result JSON, полный текст, PNG и пакет. Результат можно прочитать на телефоне; Photos integration для MVP не нужна. New Task создаёт UUID, удаляет предыдущие фотографии текущего задания и пытается удалить его серверную сессию. Отложенная доставка Watch сохраняется отдельно.

## Watch delivery

`WCSession.transferFile` отправляет один пакет. Недоступные часы не блокируют просмотр на iPhone. Outbox и receipt state сохраняются; повторная передача допускается, дубли распознаются по session id и хешам. ACK означает, что Watch проверил пакет и сохранил файлы; callback окончания передачи сам по себе не считается ACK.

Watch немедленно копирует временный WCSession file, проверяет весь пакет, SHA256, PNG dimensions, номера карточек и session id, затем сохраняет результат. Старые доставленные пакеты не вытесняют более новый ответ. После принятия новых карточек активный viewer возвращается на первую; полный ответ доступен свайпами и прокруткой.

Открытое приложение даёт haptic и показывает карточки. Для закрытого приложения используется локальное уведомление, если пользователь разрешил его. Принудительно вывести приложение поверх watchOS нельзя гарантировать. Background refresh tasks завершаются после обработки и опустошения connectivity queue. Watch хранит один активный результат.

## Обязательные проверки на устройствах

Camera реального iPhone, actual photo dimensions/focus, Bonjour/ATS, установка companion, file transfers, delivery while one app is inactive, background refresh, haptic/notification, ACK/replay и читаемость на фактическом размере часов. Ни один из этих пунктов не считается пройденным только по исходникам или симулятору.
