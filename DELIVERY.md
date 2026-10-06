# Передача Local Offline Vision Solver заказчику

**Статус: исходники MVP, не принятый конечный продукт.**

Это Windows-backend и исходники native-приложений iPhone/Watch. Готовая подписанная IPA и веса модели в архив не включены. На 6 октября 2026 года подтверждены 45 Python-тестов и настоящий HTTP transport demo. Реальные решения Qwen на RTX 4060, Apple-компиляция и связка iPhone → Windows → iPhone → Watch пока не приняты.

## Если у заказчика только Windows, iPhone и Apple Watch

Windows запускает backend. Для native iOS/watchOS нужна сборка в Xcode на macOS: локальный Mac или macOS runner GitHub Actions. Windows не собирает Apple SDK targets непосредственно. [Требования Xcode](https://developer.apple.com/xcode/system-requirements), [GitHub macOS runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).

Workflow `.github/workflows/validate.yml` проверяет Swift package и обе simulator targets без подписи, затем собирает device target и упаковывает `LocalVisionSolver-unsigned.ipa` с вложенным Watch-приложением. Артефакт `unsigned-device-ipa-needs-resigning` требует переподписи перед установкой. Сам workflow здесь ещё не запускался: проект пока не опубликован в GitHub; готовой IPA пока нет.

Для передачи через TestFlight нужен Apple Developer Program, подпись и App Store Connect. У пользователя/заказчика сейчас такого членства нет. Бесплатная Personal Team подходит для установки в целях разработки через Xcode с ограничениями; это требует доступа к Mac/Xcode и не является маршрутом постоянной клиентской дистрибуции. [Варианты членства Apple](https://developer.apple.com/support/compare-memberships/), [TestFlight](https://developer.apple.com/testflight/).

Для iPhone есть дополнительный вариант: скачать успешно собранную IPA и переподписать/установить с Windows через Sideloadly с бесплатным Apple Account. Подпись действует 7 дней и требует обновления; бесплатная постоянная установка без повторной подписи не обеспечивается. [Официальный Sideloadly](https://sideloadly.io/), [FAQ](https://sideloadly.io/faq.html). Установка встроенного Watch app и сохранение companion identifiers этим способом **не проверены и не гарантируются**. Этот вариант годится для проверки iPhone, но его нельзя считать приёмкой всей offline-системы.

**Без решения вопроса Apple-сборки и установки отправка файлов через GitHub не завершает поставку продукта.** В само приложение login/account не добавлены; требования Apple относятся к сборке и первичной установке. После установки фотографии и решения остаются локальными.

## Первый запуск Windows

Нужны Windows x64, Python (проверено на 3.14), NVIDIA driver и целевой RTX 4060 Laptop 8 GB. Python должен быть доступен командой `python`.

Из папки проекта, первоначально с Интернетом:

```powershell
.\setup.cmd -DownloadAssets
```

Установщик создаёт `.venv`, устанавливает версии из `requirements.lock.txt`, скачивает CUDA llama.cpp и Qwen/projector с проверкой хешей. Веса занимают несколько ГБ. Затем Интернет для backend не нужен.

Обычная работа:

```powershell
.\start-backend.cmd
```

Проверка transport без модели:

```powershell
.\setup.cmd
.\start-demo.cmd
```

Демо выдаёт явно обозначенные демонстрационные карточки и не решает сфотографированные задания. Для сети необходимы private Wi-Fi и соответствующие правила Windows Firewall; см. `docs/api.md`.

## Передача через GitHub

1. Создать репозиторий и загрузить исходники, включая `.github/workflows/validate.yml`, `requirements.lock.txt` и Apple Xcode project. В ZIP они находятся внутри `LocalVisionSolver/` — содержимое этой папки должно стать корнем репозитория.
2. Не загружать `.venv`, `.cache`, `sessions`, приватные фотографии/эталоны, `models`, `runtime` и файлы локальной подписи. Source archive уже исключает эти данные.
3. Открыть Actions → **Validate Windows and Apple source** → Run workflow либо отправить commit в main/master.
4. Получить успешные Windows и Apple jobs. Ошибки Apple-компиляции сначала исправить; одного Windows job недостаточно.
5. Согласовать способ Apple-подписи/установки. Затем выполнить приёмку на устройствах и целевом GPU.

GitHub используется для исходников и сборочных проверок. Runtime не загружает туда фотографии и не обращается к облаку для решения заданий.

## Проверки заказчика

```powershell
.venv\Scripts\python.exe scripts/dev.py check tests
.venv\Scripts\python.exe scripts/acceptance_http.py
```

Вторая команда сама поднимает отдельный loopback demo server, загружает две синтетические страницы, скачивает пакет/PNG, проверяет SHA256 и останавливает только свой сервер. Она не проверяет внешний Wi-Fi, камеру, Watch или точность Qwen.

## Условия приёмки конечного продукта

| Условие | Текущее состояние |
| --- | --- |
| Windows unit/integration tests | 45 passed, 1 стороннее предупреждение |
| Настоящий HTTP demo | Пройден, 2 страницы, package/PNG/SHA256 |
| Apple SDK compilation | Требует первого GitHub macOS или локального Xcode запуска |
| Подписанная установка на iPhone/Watch | Способ установки ещё не обеспечен |
| Реальные фото по восьми категориям | Не проверены на Qwen |
| Квантование/VRAM/латентность RTX 4060 | Не измерены |
| Весь маршрут без Интернета на трёх устройствах | Не проверен |

Полный checklist: `docs/mvp-acceptance.md`. Готовность к клиентской эксплуатации нельзя подтверждать по исходникам или зелёным тестам с имитацией inference.

Watch показывает результат сразу в активном viewer; в background используется уведомление при разрешении пользователя. iPhone upload/polling в этом MVP требует открытого приложения и поддерживает Resume. Рендерер по умолчанию поддерживает математическое подмножество LaTeX; полный локальный TeX требует отдельной установки и проверки. Это реальные границы текущей реализации.

Контроль содержимого архива: `SOURCE_MANIFEST.json` перечисляет SHA256 каждого файла; рядом с ZIP находится его `.sha256`.
