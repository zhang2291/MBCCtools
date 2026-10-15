@echo off
setlocal EnableExtensions
chcp 65001 >nul

set "ROOT=%~dp0"
set "SRC=%ROOT%build-local-final\resource\base\pipeline"
set "DST=%ROOT%resource\base\pipeline"
set "PUBLISH=%ROOT%publish-resource.ps1"
set "MODE=%~1"

if not exist "%SRC%" (
  echo [ERROR] Local pipeline directory not found:
  echo %SRC%
  goto :fail
)
if not exist "%DST%" (
  echo [ERROR] Repository pipeline directory not found:
  echo %DST%
  goto :fail
)
if not exist "%PUBLISH%" (
  echo [ERROR] Publish script not found:
  echo %PUBLISH%
  goto :fail
)

echo.
echo === MBCCtools local pipeline sync ===
echo From: %SRC%
echo To:   %DST%
echo.

set "SYNC_MODE=normal"
if /I "%MODE%"=="force" set "SYNC_MODE=force"
if /I "%MODE%"=="dryrun" set "SYNC_MODE=dryrun"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$src=[IO.Path]::GetFullPath($env:SRC);" ^
  "$dst=[IO.Path]::GetFullPath($env:DST);" ^
  "$mode=$env:SYNC_MODE;" ^
  "$copy=@(); $older=@();" ^
  "Get-ChildItem -LiteralPath $src -Recurse -File -Filter '*.json' | ForEach-Object {" ^
  "  $rel=$_.FullName.Substring($src.Length).TrimStart('\');" ^
  "  $target=Join-Path $dst $rel;" ^
  "  if(-not (Test-Path -LiteralPath $target)) { $copy += [pscustomobject]@{S=$_;T=$target;R=$rel;Why='new'}; return }" ^
  "  $same=((Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash -eq (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash);" ^
  "  if($same){ return }" ^
  "  if($mode -eq 'force' -or $_.LastWriteTimeUtc -gt (Get-Item -LiteralPath $target).LastWriteTimeUtc.AddSeconds(1)) {" ^
  "    $copy += [pscustomobject]@{S=$_;T=$target;R=$rel;Why='changed'}" ^
  "  } else { $older += $rel }" ^
  "};" ^
  "if($older.Count -gt 0){ Write-Host '[SKIP] Different but local file is not newer:' -ForegroundColor Yellow; $older | ForEach-Object { Write-Host ('  ' + $_) } };" ^
  "if($copy.Count -eq 0){ Write-Host 'No newer/different pipeline files to sync.' -ForegroundColor Cyan; exit 10 };" ^
  "Write-Host 'Will sync:' -ForegroundColor Green; $copy | ForEach-Object { Write-Host ('  ['+$_.Why+'] '+$_.R) };" ^
  "if($mode -eq 'dryrun'){ Write-Host 'Dry run only. Nothing copied or published.' -ForegroundColor Cyan; exit 0 };" ^
  "foreach($x in $copy){ $parent=Split-Path -Parent $x.T; New-Item -ItemType Directory -Force -Path $parent | Out-Null; Copy-Item -LiteralPath $x.S.FullName -Destination $x.T -Force };" ^
  "Write-Host ('Synced ' + $copy.Count + ' pipeline file(s).') -ForegroundColor Green"

set "SYNC_EXIT=%ERRORLEVEL%"
if "%SYNC_EXIT%"=="10" goto :nochange
if not "%SYNC_EXIT%"=="0" goto :fail
if /I "%SYNC_MODE%"=="dryrun" goto :done

echo.
echo === Git changes that will be considered by publish-resource.ps1 ===
pushd "%ROOT%"
git status --short
if errorlevel 1 (
  popd
  goto :fail
)
echo.
choice /C YN /N /M "Publish resource update now? [Y/N]: "
if errorlevel 2 (
  popd
  echo Cancelled. Files were synced, but nothing was published.
  goto :done
)

echo.
echo === Publishing resource update ===
powershell -NoProfile -ExecutionPolicy Bypass -File "%PUBLISH%" -Message "resource: sync local pipeline changes"
set "PUB_EXIT=%ERRORLEVEL%"
popd
if not "%PUB_EXIT%"=="0" goto :fail

echo.
echo Publish completed.
goto :done

:nochange
echo.
echo Nothing to publish.
goto :done

:fail
echo.
echo [FAILED] Operation did not complete.
pause
exit /b 1

:done
echo.
echo Usage:
echo   publish-local-pipeline.bat          Sync newer changed JSON files, then ask to publish
echo   publish-local-pipeline.bat dryrun   Preview only
echo   publish-local-pipeline.bat force    Sync all different JSON files, ignoring timestamps
echo.
pause
exit /b 0
