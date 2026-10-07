# Приёмка локального сайта

## На Windows с настоящим iPhone

1. Распаковать сборку, выполнить initial setup, включить iPhone hotspot и подключить ноутбук.
2. `Transport-Demo.cmd` → открыть адрес/QR в Safari, убедиться в явной пометке demo.
3. Снять фото, проверить preview, отклонить плохой снимок, добавить две страницы; gallery HEIC также должен работать.
4. Reorder/remove, Solve, stages, PNG-карточки, полный текст, скачивание PNG/ZIP/TXT в Safari Files. Для Photos использовать share меню изображения.
5. Разорвать Wi-Fi после upload и восстановить; повтор не создаёт duplicate job. Закрыть/вернуть Safari после submit и восстановить результат по тому же адресу.
6. New Task → иной UUID и чистая задача; предыдущие страницы/ответ не становятся контекстом следующей.
7. После disconnect/reconnect ноутбука проверить актуальный адрес и Firewall profile. Router LAN — запасной вариант.

## На RTX 4060 и Qwen

1. `Check.cmd`, `Start.cmd`, health=model ready. Успешный запуск не равен правильному решению.
2. Math, physics, CS, English/IELTS, Kazakh, Kazakh geography, multiple choice и multi-page reading+questions с эталонами.
3. Верные символы/цифры/units, все подпункты, независимая проверка, ответы на языке задания, полный writing.
4. Две разные темы подряд с New Task; ambiguous crop/retry и реальный случай retake.
5. Записать quantization/projector/VRAM/page count/full pipeline latency и ручную correctness. Сравнить кандидатов без сокращения ответа или отключения verification.
6. После первоначальной установки отключить внешний Интернет, сохранив LAN; проверить весь сценарий без CDN/telemetry/cloud inference.

Windows-development машина имеет RTX 3050 4 ГБ. Настоящие iPhone/hotspot/RTX 4060 прогоны пока не выполнены. Доказательства автоматических проверок — в `validation.md`.
