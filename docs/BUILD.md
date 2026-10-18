# Сборка APK

Приложение собирается инструментом [Buildozer](https://github.com/kivy/buildozer) (python-for-android).
Собирать нужно на **Linux** (Ubuntu 22.04 / 24.04) или в **WSL2**. На чистой Windows и macOS напрямую не собирается.

| Способ | Когда выбрать |
|---|---|
| [A. GitHub Actions](#a-github-actions-без-установки-чего-либо) | Нет Linux, не хочется ставить SDK/NDK |
| [B. Вручную (Linux / WSL2)](#b-ручная-сборка-linux--wsl2) | Нужен контроль, отладка, локальные правки |

Первая сборка скачивает Android SDK/NDK и компилирует Python и зависимости — это **20–60 минут и несколько ГБ**.
Повторные сборки быстрые (кэш в `~/.buildozer` и `.buildozer/`).

---

## A. GitHub Actions (без установки чего-либо)

В репозитории есть готовый workflow `.github/workflows/build-apk.yml`.

1. Форкните/загрузите репозиторий на GitHub (вместе с папкой `.github/`).
2. Вкладка **Actions** → **Build APK** → **Run workflow**. Сборка также стартует при `git push` в `main` и при теге `v*`.
3. По завершении скачайте артефакт **tg-ws-proxy-launcher-apk** (внутри `.apk`).
4. При публикации релиза (тег `v1.0.0` и т.п.) APK автоматически прикладывается к релизу GitHub.

Перед сборкой workflow прогоняет юнит-тесты; при их падении APK не собирается.

---

## B. Ручная сборка (Linux / WSL2)

### 1. WSL2 (только для Windows)

```powershell
wsl --install -d Ubuntu-24.04
```

Дальнейшие команды выполняйте **внутри Ubuntu**. Важно:

- Держите проект в файловой системе Linux (`~/tg-ws-proxy-android`), **не** в `/mnt/c/...`: сборка там очень медленная и ломается из-за прав.
- Отключите подмешивание путей Windows в `PATH` — иначе сборка `libffi`/`autoreconf` падает с `Permission denied`.
  В Ubuntu создайте/отредактируйте `/etc/wsl.conf`:
  ```ini
  [interop]
  appendWindowsPath = false
  ```
  затем в PowerShell: `wsl --shutdown` и откройте Ubuntu заново.

### 2. Системные пакеты

```bash
sudo apt update
sudo apt install -y git zip unzip openjdk-17-jdk python3-pip python3-venv \
  autoconf automake libtool libtool-bin m4 pkg-config cmake build-essential \
  zlib1g-dev libncurses-dev libffi-dev libssl-dev libltdl-dev
```

Нужна **JDK 17** (`java -version` должен показать 17). Если установлено несколько версий:
`sudo update-alternatives --config java`.

### 3. Python-окружение и Buildozer

```bash
cd ~
git clone <URL-вашего-репозитория> tg-ws-proxy-android
cd tg-ws-proxy-android

python3 -m venv ~/.venvs/buildozer
source ~/.venvs/buildozer/bin/activate
pip install --upgrade pip wheel
pip install buildozer==1.5.0 "cython==0.29.36" setuptools
```

(На Ubuntu 24.04 `pip` вне виртуального окружения откажется ставить пакеты — поэтому venv.)

### 4. Сборка

```bash
buildozer -v android debug
```

Готовый файл: `bin/tgwsproxy-<версия>-<архитектуры>-debug.apk`.
SDK/NDK и лицензии Buildozer скачает и примет сам (`android.accept_sdk_license = True`).

### 5. Установка на телефон

```bash
# по USB, с включённой отладкой
adb install -r bin/tgwsproxy-*-debug.apk
```

Или скопируйте APK на телефон и откройте его.

### 6. Если что-то пошло не так

Очистка и повтор:

```bash
buildozer android clean          # сброс сборки приложения
rm -rf .buildozer/android/platform/build-*   # если менялись Java/манифест/рецепты
buildozer -v android debug
```

Полный сброс (скачает всё заново): `rm -rf .buildozer ~/.buildozer`.

| Ошибка | Причина и решение |
|---|---|
| `autoreconf: Permission denied` / сбой сборки libffi в WSL | В `PATH` попали пути Windows. Задайте `appendWindowsPath = false` (см. выше), перезапустите WSL; установите `autoconf automake libtool`. |
| `Aidl not found` / `Cannot find ... build-tools` | Прервалась загрузка SDK. Удалите `~/.buildozer/android/platform/android-sdk` и повторите. |
| Ошибки `javac` / «Unsupported class file» | Нужна JDK 17 (не 11 и не 21). |
| `No space left on device` | Нужно 10–15 ГБ свободного места. |
| Плитка не появилась в шторке после обновления | Манифест не перегенерирован: выполните `rm -rf .buildozer/android/platform/build-*` и пересоберите. В логе должна быть строка `[p4a_hook] manifest ... patched: True`. |
| Падение на `cryptography` / Rust | Приложение **не** использует `cryptography`; убедитесь, что `buildozer.spec` не менялся в части `requirements`. |
| Сборка зависла на загрузке | Сеть/прокси: повторите, при необходимости задайте `HTTPS_PROXY`. |

Приложите последние ~50 строк лога, если создаёте issue.

### 7. Релизная (подписанная) сборка — по желанию

Debug-APK подходит для личного использования. Для публикации с постоянной подписью:

```bash
keytool -genkey -v -keystore ~/tgwsproxy.keystore -alias tgwsproxy -keyalg RSA -keysize 2048 -validity 10000
export P4A_RELEASE_KEYSTORE=~/tgwsproxy.keystore
export P4A_RELEASE_KEYALIAS=tgwsproxy
export P4A_RELEASE_KEYSTORE_PASSWD='***'
export P4A_RELEASE_KEYALIAS_PASSWD='***'
buildozer -v android release
```

Храните keystore в безопасности и **не добавляйте его в репозиторий**: потеря ключа означает, что обновить установленное приложение будет нельзя.

---

## Что внутри сборки

- `buildozer.spec` — параметры: пакет `org.tgwsproxy.tgwsproxy`, Android API 33, minAPI 26, NDK 25b, архитектуры arm64-v8a и armeabi-v7a, разрешения, сервис `proxysvc`.
- `android.add_src = java` и `res/` — Java-код плитки быстрых настроек и её иконка.
- `p4a.hook = p4a_hook.py` — добавляет `<service>` плитки в `AndroidManifest.xml` перед сборкой Gradle (штатного способа в p4a нет).
- Зависимости Python закреплены в `requirements` (чистый Python: httpx, h2, anyio и др.); `cryptography` не нужна — используется запасной путь ядра поверх OpenSSL из APK.
