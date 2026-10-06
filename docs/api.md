# LAN API v1

Windows слушает `0.0.0.0:8765`; модель остаётся на loopback `127.0.0.1:8081`. `scripts/start-backend.ps1` запускает оба компонента. `-ExternalModel` использует уже работающий локальный llama-server, `-Demo` проверяет транспорт без inference.

Bonjour service `_visionsolver._tcp.local.` с TXT `api_version=1`, `path=/health`. Service label из исходного примера слишком длинный; применено имя в пределах DNS-SD 15 символов. [RFC 6335](https://www.rfc-editor.org/rfc/rfc6335.html).

| Endpoint | Назначение |
|---|---|
| `GET /health` | service/version/model ready/loading/unavailable/demo, лимиты |
| `POST /v1/sessions` | `{session_id: UUID}`; создание либо возврат той же сессии |
| `PUT /v1/sessions/{id}/pages/{n}` | Raw JPEG/PNG bytes, без multipart/resize; idempotent SHA256 replay |
| `POST /v1/sessions/{id}/solve` | `{page_count: N, page_order: [1,…,N]}`; HTTP 202, ровно одно вычисление |
| `GET /v1/sessions/{id}` | stage/progress, result_available, error, demo |
| `GET /v1/sessions/{id}/result` | Полный structured JSON |
| `GET /v1/sessions/{id}/package` | Один `.lvsp` файл для iPhone/Watch |
| `GET /v1/sessions/{id}/cards/{index}` | Отдельный PNG, нумерация с 1 |
| `DELETE /v1/sessions/{id}` | Удаление незапущенной либо завершённой сессии; не во время upload/processing |

Session id всегда UUID, page number 1..max_pages, текущий лимит 12 страниц, 60 MiB на страницу и 300 MiB на задачу. Все страницы должны присутствовать до Solve. Повтор PUT с другим содержимым после присвоения номера запрещён; для изменения требуется новая сессия.

CPU/GPU worker последовательно обрабатывает jobs. Очередь ограничена; 429 позволяет повторить submit позже. При потере HTTP-ответа повторяется тот же session id/PUT/Solve. На перезапуске незапущенная очередь восстанавливается, прерванная обработка становится `ERROR/interrupted`, а завершённый результат остаётся доступен. Failed task повторяется с новым UUID.

Состояния: RECEIVING, QUEUED, VALIDATING_IMAGES, UNDERSTANDING, SOLVING, VERIFYING, CORRECTING, RENDERING, SENDING, COMPLETE, ERROR. Подробные технические подэтапы могут включать UNDERSTANDING_RETRY и VERIFYING_INDEPENDENT/AUDIT. `COMPLETE` в API появляется только после формирования пакета, даже если сам pipeline уже закончил inference/render.

Ошибки HTTP: 404 неизвестная сессия/card, 409 конфликт состояния, 413 upload limit, 422 неверные данные/страницы, 425 результат ещё не готов, 429 очередь занята. Ошибка processing сохраняется в status с code/message; непроверенные результаты через result/package не выдаются.

`retain_sessions=true` сохраняет сессии до явного удаления. При false завершённые/ошибочные/незавершённые upload-сессии старше retention_hours удаляются при старте и после job. Очередь и активный inference не удаляются автоматической очисткой.

## Формат Watch package

1. 8 ASCII bytes `LVSPKG01`.
2. 4-byte unsigned big-endian длина UTF-8 JSON header.
3. Header: schema_version, session_id, created_at (Unix seconds), detected_language, plain_text_answer, demo, cards.
4. PNG bytes каждой карточки подряд в порядке cards; entry содержит index/file/byte_count/sha256/width/height.

Максимум header 8 MiB, package 300 MiB. Проверяется вся последовательность, длина каждого файла, SHA256 и отсутствие trailing bytes. iPhone/Watch дополнительно проверяют PNG dimensions. Коммит происходит после полной проверки, поэтому частично доставленная пачка не показывается.

`created_at` — время создания session на ноутбуке. Поздно доставленная старая сессия не заменяет новую на Watch. Следовательно, системные часы ноутбука не следует резко переводить назад между задачами; устойчивое глобальное упорядочивание при смене ноутбуков относится к следующему этапу.

## Сеть Windows

Одна local Wi-Fi сеть без client/AP isolation. Разрешите Python-процессу TCP 8765 и multicast UDP 5353 в Windows Firewall для Private network. Эти права/правила не изменяются установщиком молча. Если обнаружение выбирает VPN/virtual adapter, задайте `server.advertise_address` равным LAN IPv4 ноутбука.

Проверка с другого устройства: `http://<laptop-LAN-IP>:8765/health`. Сначала transport demo, затем реальный Qwen. Swagger/ReDoc отключены, чтобы не подтягивать CDN assets. Приложение не требует авторизации, облачных сервисов или Интернета.

