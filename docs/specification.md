# Текущая спецификация · 0.3.0

## Архитектура

iPhone Safari → сайт Windows через LAN HTTP → image quality/неgenerative preprocessing → Qwen3-VL 8B → transcription/classification → полное решение → independent verification/audit → correction/retry → local LaTeX/text PNG renderer → Safari → PNG/TXT/ZIP download.

Модель работает через llama.cpp CUDA на RTX 4060 Laptop 8 ГБ. Windows-программа запускает модель и сервер; все assets устанавливаются заранее, потом inference/site/rendering не требуют Интернета. HTTP сайта слушает LAN 8765, model endpoint только literal loopback 8081. Без аккаунтов, cloud OCR, OpenAI API, telemetry/CDN или remote storage.

## Session

Одна задача — отдельный UUID, исходные фотографии и один логический контекст. Все страницы передаются в пользовательском порядке и реконструируются вместе. Новый Session не наследует прежние сообщения или task data. Идемпотентные create/upload/solve предотвращают дубли при потерянном ответе сети. Один GPU worker и ограниченная очередь; interrupted job после перезапуска становится явной ошибкой, завершённый результат восстанавливается.

## UI

Адаптивный русский интерфейс для ноутбука и телефона. Camera/file picker → полноэкранный preview → использовать/отклонить → несколько страниц → reorder/remove → Solve → этапы → результат. Отдельные виды карточек и полного текста. Скачивание PNG, TXT, ZIP. IndexedDB хранит только текущую задачу/оригиналы для восстановления; New Task очищает браузерное состояние. После submission ноутбук продолжает работу независимо от фонового Safari.

Адрес и локальный QR показываются на ноутбуке. iPhone может раздавать Wi-Fi ноутбуку; также поддерживается общая сеть router. Firewall и реально работающая LAN обязательны. Browser `getUserMedia` не используется на HTTP: объектив/качество системного picker зависят от Safari/устройства. Нет приложения Watch; исходный native UX сохранён в `native-app-concept.md`.

## Надёжность и качество

Языки: английский, русский, казахский; ответ на языке инструкции задания. Категории: математика, физика, информатика, English/IELTS, казахский, география на казахском, multiple choice с объяснением. Полные выводы/расчёты/единицы/запрошенный письменный ответ, без намеренного сокращения ради времени.

JPEG/PNG/HEIC/HEIF/WebP, до 12 страниц, 60 MiB/страницу, 300 MiB/задачу. Оригиналы не уменьшаются и не заменяются генерированными изображениями. EXIF orientation и lossless PNG interpretation variant, обычные quality heuristics/CLAHE, crops при ambiguity. Первое решение не публикуется до independent solve + audit; повторное чтение/исправление при расхождении. Безопасный арифметический checker не исполняет произвольный код модели.

Внутренний результат: session/language/subject/task_type/problem_text/solution/final_answer/confidence/warnings/cards/metrics. Confidence — самооценка модели, не гарантия. PNG 832×992, крупный текст, контраст, logical pagination; главный результат первым, writing начинается текстом. Формулы используют только mathtext; неподдерживаемая запись передаётся в correction loop до audit. TeX-ветка удалена.

Цель 10–30 секунд, 60 секунд для обычных задач; correctness выше latency, verification не пропускается. Эти цифры пока не измерены на RTX 4060. Q4_K_M — стартовый кандидат; выбор квантования требует реальных задач и оценки правильности, не только скорости.

Приоритеты: correctness → interpretation → session isolation → offline → LAN delivery → readability → speed → polish.
