@echo off
setlocal EnableExtensions
chcp 65001 >nul

set "ROOT=%~dp0"
set "PUBLISH=%ROOT%publish-resource.ps1"

if not exist "%PUBLISH%" (
  echo [ERROR] 发布脚本未找到: %PUBLISH%
  pause
  exit /b 1
)

echo.
echo === MBCCtools 资源发布（直接校验并发布当前源码仓库资源） ===
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%PUBLISH%" %*
pause
