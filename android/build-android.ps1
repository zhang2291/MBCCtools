param(
    [string]$MaaFwAppDir = 'D:\a-maa-dev\MaaFwApp',
    [string]$AndroidSdk = $env:ANDROID_SDK_ROOT,
    [switch]$Release,
    [switch]$Emulator
)

$ErrorActionPreference = 'Stop'
$profile = Join-Path $PSScriptRoot 'pi-profile.yaml'
if (-not (Test-Path $profile)) { throw "Missing profile: $profile" }
if (-not (Test-Path (Join-Path $MaaFwAppDir 'gradlew.bat'))) { throw "Invalid MaaFwApp dir: $MaaFwAppDir" }

$adoptiumJdks = if (Test-Path 'C:\Program Files\Eclipse Adoptium') {
    Get-ChildItem 'C:\Program Files\Eclipse Adoptium' -Directory -Filter 'jdk-17*' |
        Sort-Object LastWriteTime -Descending |
        Select-Object -ExpandProperty FullName
} else { @() }
$jdkCandidates = @(
    $env:JAVA_HOME
) + @($adoptiumJdks) + @(
    'C:\Program Files\JetBrains\IntelliJ IDEA 2024.3.1.1\jbr',
    'C:\Program Files\JetBrains\PyCharm 2024.1\jbr'
) | Where-Object {
    $_ -and
    (Test-Path (Join-Path $_ 'bin\java.exe')) -and
    (Test-Path (Join-Path $_ 'bin\jlink.exe'))
}
if (-not $jdkCandidates) { throw 'Full JDK 17+ with jlink not found.' }
$env:JAVA_HOME = @($jdkCandidates)[0]
$env:Path = "$($env:JAVA_HOME)\bin;$env:Path"

if (-not $AndroidSdk) { $AndroidSdk = $env:ANDROID_HOME }
if (-not $AndroidSdk -or -not (Test-Path $AndroidSdk)) {
    throw 'Android SDK not found. Pass -AndroidSdk <path> or set ANDROID_SDK_ROOT.'
}
$sdkNormalized = $AndroidSdk.Replace('\', '/')
$profileNormalized = $profile.Replace('\', '/')
$debugAbi = if ($Emulator) { 'arm64-v8a,x86_64' } else { 'arm64-v8a' }
@(
    "sdk.dir=$sdkNormalized",
    "pi.profile=$profileNormalized",
    "build.debugAbi=$debugAbi",
    "build.releaseAbi=arm64-v8a"
) | Set-Content -Path (Join-Path $MaaFwAppDir 'local.properties') -Encoding ASCII

$needFrameworkSetup = -not (Test-Path (Join-Path $MaaFwAppDir '.maafwversion')) -or
    ($Emulator -and -not (Test-Path (Join-Path $MaaFwAppDir 'app\src\main\jniLibs\x86_64')))
if ($needFrameworkSetup) {
    $setupAbi = if ($Emulator) { 'all' } else { 'arm64-v8a' }
    & python (Join-Path $MaaFwAppDir 'scripts\setup_maa_framework.py') --abi $setupAbi
    if ($LASTEXITCODE -ne 0) { throw 'MaaFramework setup failed.' }
}

Push-Location $MaaFwAppDir
try {
    $task = if ($Release) { ':app:assembleRelease' } else { ':app:assembleDebug' }
    & .\gradlew.bat $task
    if ($LASTEXITCODE -ne 0) { throw "Gradle task failed: $task" }
} finally {
    Pop-Location
}

$kind = if ($Release) { 'release' } else { 'debug' }
$apk = Get-ChildItem (Join-Path $MaaFwAppDir "app\build\outputs\apk\$kind") -Filter '*.apk' -Recurse |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $apk) { throw 'APK output not found.' }
$outputDir = Join-Path $PSScriptRoot 'output'
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
$suffix = if ($Release) { 'release-arm64' } elseif ($Emulator) { 'debug-arm64-x86_64' } else { 'debug-arm64' }
$outputApk = Join-Path $outputDir "MBCCtools-$suffix.apk"
Copy-Item $apk.FullName $outputApk -Force
Get-Item $outputApk | Select-Object FullName,Length,LastWriteTime



