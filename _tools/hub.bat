@echo off
rem hub.bat -- Windows 用ランチャ。ダブルクリックで対話メニューが開く。
rem   正本は _tools/hub.py。ここは「python を探して呼ぶ」だけ。
chcp 65001 >nul 2>&1
setlocal
cd /d "%~dp0.."

set "PY="
for %%P in ("py -3" "python" "python3") do (
  if not defined PY (
    %%~P -c "import sys; sys.exit(0 if sys.version_info>=(3,8) else 1)" >nul 2>&1
    if not errorlevel 1 set "PY=%%~P"
  )
)

if not defined PY (
  echo.
  echo   Python 3.8 以上が見つかりませんでした。
  echo   https://www.python.org/downloads/ からインストールしてください。
  echo.
  pause
  exit /b 2
)

%PY% "_tools\hub.py" %*
set "RC=%ERRORLEVEL%"

rem 引数なし（メニュー）のときは、閉じる前に結果が読めるよう止める
if "%~1"=="" pause
exit /b %RC%
