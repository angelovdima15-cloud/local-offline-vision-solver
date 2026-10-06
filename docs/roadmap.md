# Последовательность разработки и приёмка

После запроса пользователя реализовать конечный продукт сначала подготовлен сквозной MVP. Инфраструктурные тесты по-прежнему не доказывают качество модели. План: [MVP](mvp-plan.md), проверка устройств: [acceptance](mvp-acceptance.md).

| Phase | Содержание | Текущее состояние / условие перехода |
|---|---|---|
| 1 | Manual images → Qwen → solution → verification → render | Код CLI и тесты готовы; нужны реальные фото, эталоны и RTX 4060. Продуктовая приёмка ещё впереди. |
| 2 | Полная поддержка многостраничного документа и isolation | Базовая передача всех страниц и изоляция уже нужны Phase 1. Приёмка отдельно: четыре страницы текста + финальные вопросы, Physics → CS. |
| 3 | Image quality, understanding, verification, retry | Базовые механизмы есть; требуется настройка на реальных неидеальных фото, проверка перспективы, missing pages, ambiguous symbols. |
| 4 | Watch renderer | Базовые PNG/text/math есть. Полный TeX, сложные формулы и читаемость на реальных часах ещё требуют приёмки. |
| 5 | Windows LAN API | Реализованы upload/status/result/cards/package, serial queue, replay, recovery, limits; пройдены тесты и настоящий HTTP demo. |
| 6 | iPhone app | Swift/AVFoundation workflow, persistent task, progress/results/outbox и Xcode target подготовлены; фактическая сборка/установка на Mac впереди. |
| 7 | LAN discovery | Zeroconf + iOS Bonjour `_visionsolver._tcp`, local-network permissions/manual fallback реализованы. Проверка на реальной LAN впереди. |
| 8 | Watch app | Atomic package, SHA256/PNG checks, receipts/replay, viewer/haptic/notification и background handler реализованы в Swift; нужен paired-device test. |
| 9 | End-to-end | Windows HTTP demo пройден; полная camera → Qwen → Watch цепочка ещё требует настоящих устройств/модели. |

## Приёмка Phase 1 на целевой машине

1. Установить зависимости и проверенные модельные файлы; зафиксировать runtime/model hashes, драйвер, RAM и GPU.
2. Проверить solve при отключённом Интернете.
3. Подготовить реальные фото и эталонные решения: mathematics, physics, CS, IELTS, Kazakh, Kazakh geography, multiple choice, multi-page task.
4. Проверить распознавание исходных условий и все подпункты, язык и отсутствие придуманных данных.
5. Сравнить Q4_K_M, более точный кандидат Q5/Q6 при наличии, Q8 с CPU offload; отдельно F16/Q8 projector и F16/Q8 KV.
6. Измерить полный pipeline, пиковую VRAM, OOM/errors, обычные и сложные сценарии. Не отключать verifier ради 60 секунд.
7. Выбрать стабильный профиль по ручной оценке корректности, затем памяти и времени.
8. Зафиксировать результаты и оставшиеся ограничения перед переходом к LAN/iPhone.

Пока реальные фотографии и RTX 4060 недоступны в этой рабочей среде, нельзя честно подтвердить эти пункты или назвать квантование окончательно выбранным.
