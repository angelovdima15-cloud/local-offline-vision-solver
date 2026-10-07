# Реализованный web MVP

- Существующий solver pipeline, fresh contexts, verification, retry, arithmetic checks и local renderer сохранены.
- Native Apple код/сборки удалены. Замысел UX сохранён в `native-app-concept.md`.
- Сайт встроен в Windows backend: мобильный capture picker, preview, HEIC, страницы/reorder/remove, stages, retries, восстановление через IndexedDB, PNG/TXT/ZIP downloads.
- Точка подключения: адреса адаптеров и local QR, старт обоих процессов и открытие сайта через Start.cmd.
- Offline ресурсы без внешних запросов. Python API tests, настоящий HTTP/browser-flow и упаковка EXE.

Definition of done на аппаратуре: реальная задача с iPhone через hotspot решена Qwen на RTX 4060, независимо проверена, полный ответ получен в Safari и скачан. Локальные demo tests не заменяют этот шаг.
