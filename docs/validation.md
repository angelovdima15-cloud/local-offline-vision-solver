# Проверка прототипа и MVP

Дата: 2026-10-06. Windows, Python 3.14.5, RTX 3050 Laptop 4 ГБ. Целевая RTX 4060 8 ГБ находится на другом ноутбуке; по указанию пользователя запуск Qwen там будет позже.

Последний прогон: **45 passed**. Одна deprecation warning от Starlette TestClient/httpx; функциональные проверки проходят. Это не ошибка runtime и не доказательство готовности Apple-сборки.

## Выполнено

- Установка Python-зависимостей в `.venv` проекта.
- Автоматические тесты solver и MVP: полный pipeline с детерминированным локальным HTTP transport, все страницы в каждом этапе, изоляция двух сессий, независимый solver без первого ответа, numeric failures, corrections/re-audit, missing subquestions, recovery crops, retake после повторной попытки, truncated output, обязательная очистка KV context.
- LAN API/serial queue: idempotent session/upload/submit, input limits, atomic package, failure states, restart recovery и checksum corruption.
- Настоящий HTTP transport demo с двумя JPEG-страницами, progress, download/result checksum, PNG и удалением сессии; отчёт `.cache/transport-smoke/report.json`.
- Native iOS/watchOS sources, общий пакет, Xcode targets, schemes/plists и structural tests. Swift unit tests для Python-generated binary fixture подготовлены для запуска на Mac.
- Запрет remote/proxy inference endpoints, ограниченный арифметический AST-интерпретатор, невозможность исполнения произвольного model-generated Python.
- Прозрачность математических растров, отсутствие потери символов при пагинации Kazakh, отклонение слишком широких и неподдерживаемых формул.
- Отдельный реальный рендеринг математического и казахского примеров; визуальная проверка карточек.
- Компиляция Python-модулей и синтаксическая проверка трёх PowerShell-скриптов.
- `doctor`: правильно сообщил отсутствующие model/runtime/projector и неготовность локального inference.

В тестах **нет настоящего Qwen inference**: transport возвращает фиксированные structured answers. Такие тесты проверяют управление пайплайном, а не академическую точность.

## Ещё не проверено

- Первичная загрузка больших runtime/model assets на целевую машину и запуск pinned llama.cpp binary.
- Совместимость фактической сборки с моделью, JSON grammar и выбранным CUDA memory profile.
- Полные реальные фотографии по восьми категориям, карты, diagrams и complex LaTeX.
- Верность транскрипции, академических ответов, language detection и meaning-level audit.
- Сравнение Q4/Q5/Q6/Q8, projectors/KV и CPU offload на RTX 4060.
- Цели 10–30/60 секунд, пик VRAM и стабильность при многостраничном задании.
- Full TeX path: локальные `latex`/`dvipng` отсутствуют в текущем окружении.
- Apple-компиляция `swift test`/`xcodebuild`, native iOS/Watch на устройствах, Bonjour в фактической сети, WatchConnectivity и полный offline end-to-end scenario.

Код MVP и проверки Windows транспорта готовы. Phase 1 по академическому качеству и конечный MVP на устройствах принимаются только после указанных реальных прогонов. Подробности: [MVP acceptance](mvp-acceptance.md).
