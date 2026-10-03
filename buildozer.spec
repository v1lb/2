[app]
title = Чистильщик
package.name = cleaner
package.domain = org.example
source.dir = .
source.include_exts = py,png,jpg,kv
version = 1.0
requirements = python3,kivy==2.3.0,kivymd==1.2.0,pillow,pyjnius,android
orientation = portrait
fullscreen = 0

# Android 11+ (API 30+). Интернет НЕ запрашиваем: приложение полностью офлайн.
android.api = 34
android.minapi = 30
android.archs = arm64-v8a
android.accept_sdk_license = True
android.permissions = MANAGE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE

[buildozer]
log_level = 2
warn_on_root = 0
