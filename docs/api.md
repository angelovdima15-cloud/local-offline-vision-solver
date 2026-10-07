# Локальный API 0.4

API выбирает порт 8765–8775; inference — 8081–8091 только на loopback. Desktop передаёт admin credential через stdin. Admin requests требуют Bearer credential и loopback source. Телефоны получают только HttpOnly, SameSite=Strict cookie; credentials хранятся в SQLite как digest. Host ограничен фактическими LAN IPv4, 127.0.0.1, localhost и ::1 с фактическим API port. Browser mutations проверяют Origin; произвольный совпадающий Host/Origin не разрешён.

| Endpoint | Назначение |
| --- | --- |
| `GET /health`, `GET /ready` | Health worker/storage/model; readiness 503 при отказе |
| `POST /v1/admin/pairing` | Одноразовый QR token, TTL 120 s |
| `POST /v1/pairing/exchange` | JSON `{token,name?}`, HttpOnly cookie на 30 дней |
| `GET /v1/admin/clients` | Сопряжённые устройства без credentials |
| `DELETE /v1/admin/clients/{id}` | Отозвать доступ телефона |
| `GET /v1/admin/sessions` | Desktop: список всех задач |
| `POST /preview` | Временный JPEG ≤1600×1600; исходник не изменяется |
| `POST /v1/sessions` | Создать UUID; необязательное `session_id`, 201 |
| `PUT /v1/sessions/{id}/pages/{number}` | Исходные bytes; одинаковый replay идемпотентен |
| `GET /v1/sessions/{id}/pages/{number}/preview` | Авторизованный preview сохранённой страницы |
| `POST /v1/sessions/{id}/solve` | `{page_count,page_order}`, 202 после durable commit |
| `GET /v1/sessions/{id}` | Основное state, stage, доступность ответа/файлов |
| `POST /v1/sessions/{id}/render` | Только сохранённый verified answer; модель не вызывается |
| `GET /v1/sessions/{id}/result` | Полный structured result после COMPLETE |
| `GET /v1/sessions/{id}/answer.txt` | Проверенный TXT начиная с ANSWER_READY |
| `GET /v1/sessions/{id}/cards/{index}?download=true` | PNG после COMPLETE |
| `GET /v1/sessions/{id}/package` | Проверенный ZIP после COMPLETE |
| `DELETE /v1/sessions/{id}` | Не выполняется во время upload/processing/download |

Session принадлежит client ID; чужой телефон получает 404. UUID не является credential. Фото, preview, задачи и результаты требуют сопряжения либо desktop-admin. Авторизация выполняется до чтения upload body. Pairing exchange: 5/min/IP; create: 10/min/client; preview: 10/min/client. 429 включает Retry-After.

Основные состояния: RECEIVING → QUEUED → RUNNING → ANSWER_READY → RENDERING → PACKAGING → COMPLETE. UNDERSTANDING, SOLVING, VERIFYING_* и CORRECTING — stage. Ошибка inference даёт ERROR; ошибка renderer/package возвращает ANSWER_READY с `output_error`. Status содержит `answer_available`, `cards_available`, `result_available`. 409 `page_content_conflict` означает иной набор bytes для занятого номера; создайте новый UUID. Новая страница после submit: 409 `session_already_submitted`.

SQLite WAL + synchronous FULL + foreign keys + busy_timeout 5000; queue является частью БД. RECEIVING idle timeout 3600 s, cleanup 60 s, retention завершённых 24 h, active sessions 32, queue 8. Upload: 60 MiB/page, 300 MiB/session, 12 страниц, 64 млн pixels, minimum side 160, idle 30 s, total 180 s. Один decode/preprocessing, два preview, четыре uploads; слот preview ожидается 2 s; preview timeout 60 s. Prepared views ограничены 512 MiB; резерв диска 2 GiB.

Manifest ZIP schema 2: UUID, UTC epoch timestamp, language, text, demo и ordered PNG index/file/bytes/dimensions/SHA256. Inspector проверяет уникальность имён, последовательность индексов, типы, PNG dimensions/CRC/SHA256, соответствие text и structured result. Manifest ≤8 MiB; ZIP и распакованный пакет ≤300 MiB. Файлы защищены lease во время отправки. Legacy job.json импортируется без удаления исходных метаданных; повреждения регистрируются в recovery, RUNNING после аварии становится ERROR/interrupted.
