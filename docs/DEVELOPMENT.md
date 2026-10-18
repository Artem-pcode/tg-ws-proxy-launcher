# Разработка

## Структура

```
main.py                    точка входа Kivy (процесс UI)
services/proxy_service.py  точка входа фонового сервиса (отдельный процесс)
src/ui/                    экраны Kivy: status, settings, core, logs, system, adb
src/core/                  логика без UI: config_store, service_runner, saver, core_loader,
                           update_manager, launch_flow, bg_status, android_utils, i18n ...
src/proxy/                 встроенная копия ядра Flowseal/tg-ws-proxy (версия в src/BUNDLED_CORE_VERSION)
java/…/ProxyTileService.java, TileHelper.java   плитка быстрых настроек
res/drawable/ic_tile.xml   иконка плитки
p4a_hook.py                правка манифеста при сборке
tests/                     юнит- и интеграционные тесты (запускаются на ПК)
```

## Как устроено

- **UI и сервис — два процесса.** Обмен идёт через файлы в `files/tgwsproxy/proxy/`:
  `config.json`, `status.json` (состояние `starting/running/paused/error/stopped`, считается устаревшим через 5 с),
  `stop.signal`, `reload.signal`, `resume.signal`, `proxy.log`, `launcher.log`.
- **Сервис** (`service_runner.py`): поток `ProxyRunner` с asyncio-циклом ядра, автоперезапуск (5 с, не более 5 падений за 300 с),
  фатальные ошибки (порт занят/запрещён), откат ядра при неудачной загрузке, перезагрузка конфига без убийства процесса.
- **Ядро**: `proxy_core/current` и `backup` во внутреннем хранилище, иначе встроенное из APK.
  Обновление — `update_manager.py` (HTTPS, проверка архива, AST-сканирование импортов).
- **Экономия батареи** (`saver.py`): события `UsageStatsManager` по паре (пакет, класс), чистая политика `SaverPolicy`,
  пауза останавливает сетевое ядро, сервис остаётся жить.
- **Плитка**: Java `TileService` читает `status.json` и теми же файлами/`ServiceProxysvc.start/stop` управляет сервисом,
  поэтому поведение совпадает с кнопкой в приложении.
- **Ярлык**: `ShortcutManager` (закреплённый ярлык), действие `<пакет>.LAUNCH_FROM_SHORTCUT`; `launch_flow.py` гарантирует,
  что прокси реально принимает соединения (проверка порта), прежде чем открыть Telegram.
- **pyjnius**: классы приложения (`ServiceProxysvc`, `TileHelper`) разрешаются только из главного потока.

## Запуск на ПК (отладка UI)

```bash
pip install kivy==2.3.0 httpx==0.28.1 h2==4.2.0 certifi
TGWSP_HOME=/tmp/tgwsp python main.py
```

Переменная `TGWSP_HOME` задаёт папку данных. Для проверки режима экономии без телефона можно задать `TGWSP_FAKE_FG` (файловый провайдер окна).

## Тесты

```bash
pip install httpx==0.28.1 h2==4.2.0 certifi pytest
python -m pytest -q tests
```

Покрыто: конфиг и валидация, загрузка/обновление/откат ядра, запуск настоящего сервиса и ядра, политика экономии,
оценка статуса ADB, наличие и согласованность Java-плитки, правка манифеста хуком.
Java и работа на устройстве (плитка, ShortcutManager, UsageStats) в CI не проверяются — только на телефоне.

## Добавление строк интерфейса

Все строки — в `src/core/i18n.py` (словари `ru` и `en` должны иметь одинаковый набор ключей — это проверяет тест).
