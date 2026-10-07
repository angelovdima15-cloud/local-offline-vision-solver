# Проверки 0.4

Актуальные evidence находятся в `.cache/dev-checks`, `.cache/browser-checks`, `.cache/desktop-checks`, `.cache/windows-build`, `.cache/installer-checks`; итоговый статус — `dist/acceptance-report.json`. Аппаратная приёмка не подменяется demo.

Проверки реализации 0.4 от 7 октября 2026:

- **80 passed**, exit 0, 23.39 s. Отказы SQLite/записи, восстановление очереди, leases, slow upload, авторизация и owner, пределы изображений, verified answer/render retry, ZIP, assets, процессы Windows, power journal и desktop. Лог: `.cache/dev-checks/20261007-203743-49dbef.log`.
- Source browser: **PASS**, без внешних запросов и JavaScript errors. Включены New Task во время сохранения, 404, конечные повторы result 500, изменение частично отправленных фото, освобождение URL, TXT при render failure и повторное сопряжение. Отчёт: `.cache/browser-checks/20261007-203959-75e972/report.json`.
- Frozen backend HTTP: **PASS**, загрузка оригиналов, двухстраничная demo-задача и проверка SHA256 результата. Отчёт: `.cache/acceptance-http/20261007-204335-3f42f4/report.json`.
- Frozen browser: **PASS** с теми же сценариями восстановления. Отчёт: `.cache/browser-checks/20261007-204341-f2a34f/report.json`.
- Frozen GUI setup/demo: **PASS**, exit 0. Логи: `.cache/desktop-checks/20261007-204359-2ccea8/check.log`, `.cache/desktop-checks/20261007-204403-688e87/check.log`.
- Все пять QML-экранов проверены при масштабах **100%, 125%, 150%, 200%**, включая минимальный размер окна. Evidence: `.cache/desktop-view-checks/20261007-202948-0b9385`, `20261007-203002-6895db`, `20261007-203007-fbdd32`, `20261007-203013-c3d866`.

Inference в этих проверках simulated/demo. Реальные Qwen-задачи на RTX 4060 Laptop 8 GB, iPhone/Safari, чистая Windows без Python, многогигабайтная первоначальная загрузка, offline solve, driver/reboot и 30 минут работы с закрытой крышкой остаются отдельной приёмкой.

## Исторические проверки 0.3

# Проверки · 7 октября 2026

- 46 Python tests: pipeline/context isolation/verification/retry, арифметика, renderer, LAN queue/upload/restart/limits, ZIP integrity, local site, Origin policy, QR decode, HEIC original preservation/preview и downloads.
- Pytest: **46 passed, 1 warning**, 9.78 s; exit 0. Полный лог `.cache/dev-checks/20261007-175849-09eb08.log`.
- Browser Chromium на Windows, desktop 1360×960 и phone viewport 430×932: preview двух фото, reorder, потерянный ACK после принятого upload, idempotent retry, результат, ZIP, reload restore, новая независимая задача. **PASS**, без JS errors/внешних HTTP-запросов. Report/screenshots: `.cache/browser-checks/20261007-175809-391af0/`.
- QR декодирован через OpenCV; HEIC bytes/SHA256 сохранены без изменения, preview JPEG создан локально и не заменяет исходник.
- Переносимый Windows EXE собран локально PyInstaller 6.22.3. Через этот EXE повторён browser-flow, включая HEIC preview/raw bytes, reorder, lost upload ACK, ZIP download, восстановление после потери polling/reload, новый UUID. **PASS**: `.cache/browser-checks/20261007-180736-f40b00/report.json`; полный вывод `.cache/frozen-browser-check.log`.
- ZIP готовой программы: `dist/LocalVisionSolver-Web-Windows-x64.zip`, 112851164 bytes. SHA256 `685439344b8204483142bc4103322da939e7542353f200e5f876ae138d3d5b0b`. Model assets не включены: первоначальный installer скачает их на целевом ноутбуке.
- Native код/пакеты/CI Apple удалены после сохранения UX-идеи; очищено около 528.5 MiB старых исходников, артефактов и развёрнутых пакетов.

Demo flow не решает задания, pytest inference adapters детерминированы. Фактическое качество Qwen, VRAM/latency RTX 4060, камера Safari, downloads iOS и маршрут через настоящий iPhone hotspot остаются аппаратной приёмкой. Проверка phone viewport не является тестом настоящего iPhone или WebKit/Safari.
