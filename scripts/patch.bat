@echo off
setlocal EnableDelayedExpansion

::::::::::::::::
:: Constants  ::
::::::::::::::::
set "FRIDA_VERSION=17.8.2"
set "UBER_APK_SIGNER_VERSION=1.3.0"

::::::::::::::::::::::::::::::::::::
:: Environment and arg validation ::
::::::::::::::::::::::::::::::::::::
echo Checking environment/tools...

:: Validate arguments
if "%~1"=="" (
    echo Missing device argument ^(e.g 192.168.1.1:1234^)!
    exit /b 2
)
set "DEVICE=%~1"

:: Check tools
where adb >nul 2>nul || (echo adb is required! & exit /b 1)
where apktool >nul 2>nul || (echo apktool is required! & exit /b 1)
where java >nul 2>nul || (echo java is required! & exit /b 1)
where 7z >nul 2>nul || (echo 7-Zip ^(7z^) is required to extract .xz files! Make sure it is in your PATH. & exit /b 1)

::::::::::::::::::
:: Folder setup ::
::::::::::::::::::
echo Setting up folders...

set "WORKING_FOLDER=%CD%"
set "DATA_FOLDER=%WORKING_FOLDER%\data"
set "APK_SOURCE_FOLDER=%DATA_FOLDER%\source_apks"
set "APK_DECOMPILED_FOLDER=%DATA_FOLDER%\base_apk_decompiled"
set "APK_PATCHED_FOLDER=%DATA_FOLDER%\patched"
set "APK_SIGNED_FOLDER=%DATA_FOLDER%\signed"
set "TOOLS_FOLDER=%WORKING_FOLDER%\tools"
set "FRIDA_FOLDER=%TOOLS_FOLDER%\frida"

if not exist "%APK_SOURCE_FOLDER%" mkdir "%APK_SOURCE_FOLDER%"
if not exist "%APK_DECOMPILED_FOLDER%" mkdir "%APK_DECOMPILED_FOLDER%"
if not exist "%APK_PATCHED_FOLDER%" mkdir "%APK_PATCHED_FOLDER%"
if not exist "%APK_SIGNED_FOLDER%" mkdir "%APK_SIGNED_FOLDER%"
if not exist "%FRIDA_FOLDER%" mkdir "%FRIDA_FOLDER%"

:::::::::::::::::::::::::
:: Download deps/tools ::
:::::::::::::::::::::::::
echo Downloading dependencies/tools...

if not exist "%FRIDA_FOLDER%\undetected-frida-gadget-%FRIDA_VERSION%-android-arm.so.xz" (
    powershell -Command "Invoke-WebRequest -Uri 'https://github.com/zer0def/undetected-frida/releases/download/%FRIDA_VERSION%/undetected-frida-gadget-%FRIDA_VERSION%-android-arm.so.xz' -OutFile '%FRIDA_FOLDER%\undetected-frida-gadget-%FRIDA_VERSION%-android-arm.so.xz'"
)
if not exist "%FRIDA_FOLDER%\undetected-frida-gadget-%FRIDA_VERSION%-android-arm64.so.xz" (
    powershell -Command "Invoke-WebRequest -Uri 'https://github.com/zer0def/undetected-frida/releases/download/%FRIDA_VERSION%/undetected-frida-gadget-%FRIDA_VERSION%-android-arm64.so.xz' -OutFile '%FRIDA_FOLDER%\undetected-frida-gadget-%FRIDA_VERSION%-android-arm64.so.xz'"
)

if not exist "%FRIDA_FOLDER%\undetected-frida-gadget-%FRIDA_VERSION%-android-arm.so" (
    echo Extracting Frida gadgets...
    cd /d "%FRIDA_FOLDER%"
    7z x -y "undetected-frida-gadget-%FRIDA_VERSION%-android-arm.so.xz" >nul
    7z x -y "undetected-frida-gadget-%FRIDA_VERSION%-android-arm64.so.xz" >nul
    cd /d "%WORKING_FOLDER%"
)

if not exist "%TOOLS_FOLDER%\uber-apk-signer-%UBER_APK_SIGNER_VERSION%.jar" (
    powershell -Command "Invoke-WebRequest -Uri 'https://github.com/patrickfav/uber-apk-signer/releases/download/v%UBER_APK_SIGNER_VERSION%/uber-apk-signer-%UBER_APK_SIGNER_VERSION%.jar' -OutFile '%TOOLS_FOLDER%\uber-apk-signer-%UBER_APK_SIGNER_VERSION%.jar'"
)

::::::::::::::::::::::::::
:: Pull and extract APK ::
::::::::::::::::::::::::::
echo Extracting original APKs from phone...

:: Use PowerShell to cleanly strip package prefixes and hidden whitespace without breaking extensions
powershell -Command "$paths = adb -s '%DEVICE%' shell pm path com.anker.charging | ForEach-Object { $_ -replace '^package:', '' } | ForEach-Object { $_.Trim() }; foreach ($path in $paths) { if ($path) { adb -s '%DEVICE%' pull $path '%APK_SOURCE_FOLDER%' } }"

echo Decompiling main APK...
call apktool d "%APK_SOURCE_FOLDER%\base.apk" -o "%APK_DECOMPILED_FOLDER%" -f

::::::::::::::::::
:: Inject Frida ::
::::::::::::::::::
echo Injecting Frida gadget into main APK...

:: Copy Frida gadget binaries
mkdir "%APK_DECOMPILED_FOLDER%\lib\armeabi" 2>nul
mkdir "%APK_DECOMPILED_FOLDER%\lib\armeabi-v7a" 2>nul
mkdir "%APK_DECOMPILED_FOLDER%\lib\arm64-v8a" 2>nul

copy /y "%FRIDA_FOLDER%\undetected-frida-gadget-%FRIDA_VERSION%-android-arm.so" "%APK_DECOMPILED_FOLDER%\lib\armeabi\libnative-utils.so" >nul
copy /y "%FRIDA_FOLDER%\undetected-frida-gadget-%FRIDA_VERSION%-android-arm.so" "%APK_DECOMPILED_FOLDER%\lib\armeabi-v7a\libnative-utils.so" >nul
copy /y "%FRIDA_FOLDER%\undetected-frida-gadget-%FRIDA_VERSION%-android-arm64.so" "%APK_DECOMPILED_FOLDER%\lib\arm64-v8a\libnative-utils.so" >nul

:: Inject the JSON config
copy /y "%WORKING_FOLDER%\frida_config.json" "%APK_DECOMPILED_FOLDER%\lib\armeabi\libnative-utils.config.so" >nul
copy /y "%WORKING_FOLDER%\frida_config.json" "%APK_DECOMPILED_FOLDER%\lib\armeabi-v7a\libnative-utils.config.so" >nul
copy /y "%WORKING_FOLDER%\frida_config.json" "%APK_DECOMPILED_FOLDER%\lib\arm64-v8a\libnative-utils.config.so" >nul

:: Add Frida gadget to app startup (Replacing Line 34)
set "SMALI_FILE=%APK_DECOMPILED_FOLDER%\smali\s\h\e\l\l\A.smali"
powershell -Command "$c = Get-Content -Path '%SMALI_FILE%'; $c[33] = 'const-string v0, \"native-utils\"' + [char]10 + 'invoke-static {v0}, Ljava/lang/System;->loadLibrary(Ljava/lang/String;)V'; Set-Content -Path '%SMALI_FILE%' -Value $c"

:: Modify manifest to enable Frida loading
set "MANIFEST_FILE=%APK_DECOMPILED_FOLDER%\AndroidManifest.xml"
powershell -Command "(Get-Content -Path '%MANIFEST_FILE%') -replace 'android:allowBackup=\"false\"', 'android:allowBackup=\"true\"' | Set-Content -Path '%MANIFEST_FILE%'"
powershell -Command "(Get-Content -Path '%MANIFEST_FILE%') -replace 'android:extractNativeLibs=\"false\"', 'android:extractNativeLibs=\"true\" android:debuggable=\"true\"' | Set-Content -Path '%MANIFEST_FILE%'"

::::::::::::::::::::::::::::
:: Re-package and re-sign ::
::::::::::::::::::::::::::::
echo Re-packaging and re-signing APK...

:: Re-package base/main APK
call apktool b -o "%APK_PATCHED_FOLDER%\base.apk" "%APK_DECOMPILED_FOLDER%"

:: Copy all original split APKs into the patched folder so we can batch-sign them
for %%f in ("%APK_SOURCE_FOLDER%\split_*.apk") do (
    copy /y "%%f" "%APK_PATCHED_FOLDER%\" >nul
)

:: Sign all APKs in the patched folder dynamically
java -jar "%TOOLS_FOLDER%\uber-apk-signer-%UBER_APK_SIGNER_VERSION%.jar" -a "%APK_PATCHED_FOLDER%" -o "%APK_SIGNED_FOLDER%" --allowResign

echo Uninstalling existing app...
adb -s %DEVICE% uninstall com.anker.charging

echo Installing patched APKs...
:: Build a dynamic list of all signed APKs for the install-multiple command
set "APK_LIST="
for %%f in ("%APK_SIGNED_FOLDER%\*.apk") do (
    set "APK_LIST=!APK_LIST! "%%f""
)

adb -s %DEVICE% install-multiple !APK_LIST!

echo Done!