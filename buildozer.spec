[app]
title = TG WS Proxy
package.name = tgwsproxy
package.domain = org.tgwsproxy
version = 1.0.0

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,json,pem,txt
source.include_patterns = assets/*,src/*,services/*,src/BUNDLED_CORE_VERSION
source.exclude_dirs = tests,docs,java,res,bin,.buildozer,.github,__pycache__
source.exclude_patterns = LICENSE*,*.md,*.pyc

icon.filename = %(source.dir)s/assets/icons/icon.png
presplash.filename = %(source.dir)s/assets/icons/presplash.png
android.presplash_color = #1a1a1a

orientation = portrait
fullscreen = 0

# Все зависимости чисто-python, кроме kivy/pyjnius/openssl (у них есть рецепты p4a).
# pip в p4a ставит пакеты без зависимостей, поэтому цепочка httpx[http2] перечислена целиком.
# `cryptography` не нужна: ядро само использует ctypes-обёртку над libcrypto (proxy/_aes.py),
# а src/core/libcrypto_shim.py подсказывает ей путь к libcrypto из APK.
requirements = python3,kivy==2.3.0,pyjnius,android,openssl,certifi,httpx==0.28.1,httpcore==1.0.9,h11==0.16.0,h2==4.2.0,hpack==4.1.0,hyperframe==6.1.0,anyio==4.9.0,sniffio==1.3.1,idna==3.10,typing_extensions==4.13.2

# foreground-сервис с прокси; sticky - система перезапустит его, если убьёт
services = proxysvc:services/proxy_service.py:foreground:sticky

android.permissions = INTERNET,FOREGROUND_SERVICE,WAKE_LOCK,POST_NOTIFICATIONS,REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,QUERY_ALL_PACKAGES,PACKAGE_USAGE_STATS,READ_DEVICE_CONFIG

android.add_src = java
android.add_resources = res/drawable:drawable
p4a.hook = p4a_hook.py
android.api = 33
android.minapi = 26
android.ndk = 25b
android.ndk_api = 26
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True
# в config.json лежит secret прокси - в облачный бэкап его не отдаём
android.allow_backup = False
# оставить .py в APK: версия встроенного ядра читается из proxy/__init__.py
android.no-byte-compile-python = True
android.logcat_filters = *:S python:D
android.debug_artifact = apk

p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 1
