# Приёмка сквозного MVP

## Выполнено на текущей Windows-машине

- 45 Python-тестов: исходный solver, LAN API, serial queue, idempotent retries, лимиты, ошибки, restart, package integrity, Bonjour type, Xcode references/plists/schemes и Python/Swift binary fixture; API также проверен вместе с настоящим pipeline-кодом и детерминированными ответами inference adapter.
- Настоящий HTTP smoke: две JPEG-страницы → submit → QUEUED/RENDERING/COMPLETE → download package → SHA256 verification → download PNG → delete session.
- Swift sources, два native targets, companion identifiers и shared schemes подготовлены. На Windows нет Apple SDK; `swift test`/`xcodebuild` успешно выполнены в GitHub macOS CI.

## На Mac и настоящей паре iPhone/Watch

1. Запустить `bash scripts/check-apple.sh`; исправить ошибки фактической Apple-компиляции, если выявятся.
2. Установить оба targets с корректной подписью и companion id.
3. Запустить Windows `start-backend.ps1 -Demo`, разрешить локальную сеть/камеру/Watch notifications.
4. Открыть iPhone app; camera должна быть первым workflow. Снять фото, увидеть full-screen preview, Retake, Use Photo.
5. Добавить вторую страницу, изменить порядок, удалить пробную страницу. Убедиться, что принят JPEG исходного качества.
6. Solve; дождаться помеченной TRANSPORT DEMO карточки на телефоне и Watch. Haptic при активном viewer, уведомление при разрешениях и неактивном app.
7. Отключить Watch/закрыть viewer при новом запросе; ответ остаётся на iPhone и доставляется после восстановления. Проверить ACK и Retry Watch.
8. Перейти на iPhone в background во время upload/polling, открыть снова; Resume не создаёт вторую вычислительную сессию.
9. Перезапустить backend: готовый пакет доступен, interrupted task даёт понятную ошибку и новый retry id.
10. Проверить чтение длинного текста/формул, все карточки, первую страницу нового результата и устойчивость к поздней доставке старого.

## На целевом RTX 4060 с моделью

1. Установка model/runtime assets; старт без `-Demo`, после загрузки health=model ready.
2. Пройти восемь категорий исходной спецификации с эталонами, включая многостраничный документ.
3. Проверить strict Physics → New Task → CS isolation, signs/fractions/units/options/Kazakh characters и полноту writing.
4. Сравнить квантования/projectors/KV и перенести окончательный выбор в config по correctness-first бенчмарку.
5. Измерить полный путь, VRAM/OOM и latency. При превышении 60 секунд сохранить verification, зафиксировать несоответствие цели.
6. Отключить Internet на ноутбуке и телефоне, сохранив LAN и iPhone/Watch connectivity, повторить полный маршрут.

До этих проверок формулировка «готовый работающий продукт на устройствах» не подтверждена. Текущий результат — реализация MVP в исходниках с проверенным Windows transport и подготовленной Apple-сборкой.

## Повторная проверка перед передачей, 6 октября 2026

- Полный Windows run после исправления test helper: **45 passed, 1 warning**, 10.87 s pytest; лог `.cache/dev-checks/20261006-230324-7c6dbf.log`.
- Изолированный HTTP run: две синтетические JPEG-страницы, пакет/PNG и SHA256 проверены; лог/отчёт `.cache/acceptance-http/20261006-230828-8ec45c/`. Сервер остановлен самим runner.
- Исправлены временный каталог test helper и UTF-8 вывода.
- В Apple-коде исправлены гонка unpack/prune на Watch и неполная проверка replay metadata. Добавлены Swift regression tests для конфликтующего текста и восстановления отсутствующей карточки. **Все 5 Swift-тестов успешно выполнены.**
- GitHub CI успешно выполнен: [run 37511112828](https://github.com/angelovdima15-cloud/local-offline-vision-solver/actions/runs/37511112828). Пройдены Windows tests/HTTP, Swift tests, обе simulator-сборки и unsigned device IPA. В IPA проверены наличие обоих executables, device platforms и соответствие companion ID. Установка на настоящие устройства пока не проверена.

## Готовые сборки для установки — 6 октября 2026

- [CI run 37513507857](https://github.com/angelovdima15-cloud/local-offline-vision-solver/actions/runs/37513507857) завершён успешно: Windows backend, 45 Python-тестов, настоящий HTTP, PyInstaller EXE, 5 Swift-тестов, Apple simulator/device builds.
- `LocalVisionSolver-Windows-x64.zip`: переносимый EXE с Python/dependencies внутри; отдельный EXE скачивает runtime/model при первичной установке. Проверка frozen backend выполняется автоматически до создания ZIP.
- Скачанный EXE повторно запущен на текущей Windows-машине: две страницы через настоящий HTTP, проверка SHA256 пакета, два математических и два казахских PNG. Образцы проверены визуально. Локальный HTTP report: `.cache/acceptance-http/20261006-234907-df8d89/report.json`.
- `LocalVisionSolver-unsigned.ipa`: iPhoneOS/watchOS device binaries, вложенный Watch bundle, совпадающий companion ID. Подпись Apple и установка на устройства остаются необходимыми.
- `LocalVisionSolver-Customer.zip` содержит только готовые ZIP/IPA, их SHA256 и инструкцию. Исходники, модели, личные фотографии, токены и development tools в клиентский пакет не входят.
- Аппаратная приёмка Qwen/RTX 4060/iPhone/Watch остаётся невыполненной; эти сборки не подтверждают качество ответов, VRAM, целевую задержку или установленное приложение на часах.
- `doctor` подтверждает отсутствие локальных llama executable/model/projector; здесь AI mode не готов. Это согласуется с прежним решением запускать модель позже на RTX 4060.
- У заказчика Windows/iPhone/Watch, нет Mac и Apple Developer Program. Маршрут подписанной установки не завершён; см. `DELIVERY.md`.
