# Реализация desktop 0.4

| Требование | Реализация | Проверка |
| --- | --- | --- |
| Независимые пути данных | app_paths.py, config.py, `--data-dir` | test_desktop.py |
| Durable queue / recovery / leases | job_repository.py, server.py | test_job_repository.py, test_api.py |
| Photo limits / IO | image_policy.py, image_service.py | test_image_policy.py, test_io_concurrency.py |
| Verified answer / one finalizer | pipeline.py, job_service.py, package.py | test_pipeline.py, test_job_repository.py |
| Safari recovery / epoch / pairing | web/app.js | check_browser.py, browser_recovery.py |
| Owner / Host / Origin / token expiry | security.py | test_security.py |
| Windows owned process lifecycle | process_supervisor.py, runtime_lock.py | test_process_supervisor.py |
| Pinned resumable assets | asset_installer.py, assets.lock.json | test_asset_installer.py |
| Qt Quick Russian GUI / tray | desktop/* | check_desktop.py |
| AC lid journal / execution request | windows_power.py | test_windows_power.py |
| Frozen payload / one installer | package_windows.py, installer/Vision.iss | frozen HTTP/browser/GUI, check_installer.py |

Pinned metadata получены из официальных API: Hugging Face commit `f982a07559d4a2f6c8744d840bf6fccab30eea96`, model 5 027 784 800 bytes, projector 1 159 029 824 bytes. llama.cpp b11429 archive 264 478 423 bytes, CUDA 12.4 archive 391 443 627 bytes. SHA256 runtime сверены с GitHub release metadata; большие assets не загружались и не запускались на RTX 3050.

Файлы GUI и сайта находятся в immutable payload, данные — в AppPaths. Настройки сохраняются атомарно. Pipeline возвращает VerifiedAnswer и хранит каждую candidate/independent/audit версию; общий job service сохраняет verified TXT до renderer. Формулы проверяются mathtext перед audit и включаются в correction feedback. Пустые numeric checks требуют явного not_applicable и объяснения.

Супервизор назначает дочерний процесс Windows Job Object до возобновления исполнения; остальные процессы компьютера не затрагиваются. Startup health проверяет живой PID и принадлежность listening port; model startup timeout 300 s. Runtime restart ограничен тремя попытками, без снижения качества. Suspend останавливает backend; resume запускает новый runtime/context, обновляет сеть и QR. Второй desktop активирует первое окно; source backend использует отдельный OS lock.

Работа с крышкой использует AC Power APIs и один живущий поток SetThreadExecutionState без ES_DISPLAY_REQUIRED. Journal записывается до изменения; восстановление сравнивает актуальное значение с применённым и сохраняет пользовательские изменения. Установка firewall и NVIDIA-драйвера — отдельные действия с UAC. Драйвер проверяется по версии; downloaded installer принимается только с действительной подписью NVIDIA.

Официальные основания: [PySide6 6.11.2](https://pypi.org/project/PySide6/6.11.2/), [CUDA 12.4 release notes](https://docs.nvidia.com/cuda/archive/12.4.0/cuda-toolkit-release-notes/index.html), [Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects), [SetThreadExecutionState](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-setthreadexecutionstate), [lid action](https://learn.microsoft.com/en-us/windows-hardware/customize/power-settings/power-button-and-lid-settings-lid-switch-close-action), [Inno Setup](https://jrsoftware.org/isinfo.php).

Остающаяся приёмка: чистая Windows без Python/исходников, initial multi-GB download и network interruption, реальные задачи на RTX 4060 8 GB (1/3/12 страниц и все предметы), Safari/hotspot/downloads на iPhone, отсутствие Интернета после setup, AC/DC/suspend/resume и охлаждение с закрытой крышкой 30 минут. Автоматические тесты используют demo либо simulated inference. `acceptance-report.json` не объявляет аппаратную приёмку выполненной.
