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
$localJdks = if (Test-Path 'C:\jdk') {
    Get-ChildItem 'C:\jdk' -Directory -Filter 'jdk*17*' |
        Sort-Object LastWriteTime -Descending |
        Select-Object -ExpandProperty FullName
} else { @() }
$jdkCandidates = @(
    $env:JAVA_HOME
) + @($localJdks) + @($adoptiumJdks) + @(
    'C:\jdk\jdk17',
    'C:\Program Files\JetBrains\IntelliJ IDEA 2024.3.1.1\jbr',
    'C:\Program Files\JetBrains\PyCharm 2024.1\jbr'
) | Select-Object -Unique | Where-Object {
    $_ -and
    (Test-Path (Join-Path $_ 'bin\java.exe')) -and
    (Test-Path (Join-Path $_ 'bin\jlink.exe')) -and
    ((& (Join-Path $_ 'bin\java.exe') -version 2>&1 | Select-String 'version "17\.').Count -gt 0)
}
if (-not $jdkCandidates -and (Get-Command mise -ErrorAction SilentlyContinue)) {
    $miseJdk = & mise where java@17.0.12 2>$null
    if ($LASTEXITCODE -eq 0 -and (Test-Path (Join-Path $miseJdk 'bin/jlink.exe'))) {
        $jdkCandidates = @($miseJdk.Trim())
    }
}
if (-not $jdkCandidates) { throw 'Full JDK 17 with jlink not found.' }
$env:JAVA_HOME = @($jdkCandidates)[0]
$env:Path = "$($env:JAVA_HOME)\bin;$env:Path"
Write-Host "Using JDK 17: $($env:JAVA_HOME)"

if (-not $AndroidSdk) { $AndroidSdk = $env:ANDROID_HOME }
if (-not $AndroidSdk -and (Test-Path 'D:\Android\Sdk')) { $AndroidSdk = 'D:\Android\Sdk' }
if (-not $AndroidSdk -or -not (Test-Path $AndroidSdk)) {
    throw 'Android SDK not found. Pass -AndroidSdk <path> or set ANDROID_SDK_ROOT.'
}
$sdkNormalized = $AndroidSdk.Replace('\', '/')
$profileNormalized = $profile.Replace('\', '/')
$debugAbi = if ($Emulator) { 'arm64-v8a,x86_64' } else { 'arm64-v8a' }
$localPropsPath = Join-Path $MaaFwAppDir 'local.properties'
$desiredProps = @(
    "sdk.dir=$sdkNormalized",
    "pi.profile=$profileNormalized",
    "build.debugAbi=$debugAbi",
    "build.releaseAbi=arm64-v8a"
) -join "`r`n"
$currentProps = if (Test-Path $localPropsPath) { (Get-Content -Raw $localPropsPath).Trim() } else { '' }
if ($currentProps -ne $desiredProps) {
    Set-Content -Path $localPropsPath -Value $desiredProps -Encoding ASCII
}

$needFrameworkSetup = -not (Test-Path (Join-Path $MaaFwAppDir '.maafwversion')) -or
    ($Emulator -and -not (Test-Path (Join-Path $MaaFwAppDir 'app\src\main\jniLibs\x86_64')))
if ($needFrameworkSetup) {
    $setupAbi = if ($Emulator) { 'all' } else { 'arm64-v8a' }
    & python (Join-Path $MaaFwAppDir 'scripts\setup_maa_framework.py') --abi $setupAbi
    if ($LASTEXITCODE -ne 0) { throw 'MaaFramework setup failed.' }
}

# Agent binding must match the framework bundled into this APK.
$frameworkVersion = (Get-Content (Join-Path $MaaFwAppDir '.maafwversion') -Raw).Trim().TrimStart('v')
$agentDir = Join-Path $PSScriptRoot 'agent-runtime'
$agentManifest = Join-Path $agentDir 'arm64-v8a/bundle/agent-core.json'
$requirements = Join-Path $PSScriptRoot 'agent-requirements.txt'
$requirementsHash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash
$requirementsMarker = Join-Path $agentDir 'project-requirements.sha256'
$pillowDir = Join-Path $agentDir 'arm64-v8a/bundle/site-packages/PIL'
# A cached Python core alone is insufficient: inventory imports Pillow, including native codecs.
$hasPillow = (Test-Path -LiteralPath $pillowDir) -and
    @(Get-ChildItem -LiteralPath $pillowDir -Filter '_imaging*.so' -ErrorAction SilentlyContinue).Count -gt 0
$sameRequirements = (Test-Path -LiteralPath $requirementsMarker) -and
    (Get-Content -LiteralPath $requirementsMarker -Raw).Trim() -eq $requirementsHash
if (-not (Test-Path $agentManifest) -or -not $hasPillow -or -not $sameRequirements) {
    & python (Join-Path $MaaFwAppDir 'scripts/build_agent_bundle.py') --out $agentDir --core-tag "3.13.15-maafw$frameworkVersion" --requirements $requirements --extra-index-url 'https://chaquo.com/pypi-13.1/'
    if ($LASTEXITCODE -ne 0) { throw 'Android Agent runtime preparation failed.' }
    $requirementsHash | Set-Content -LiteralPath $requirementsMarker -Encoding ASCII
}
$manifest = Get-Content $agentManifest -Raw | ConvertFrom-Json
if ($manifest.provides.maafw -ne $frameworkVersion) {
    throw "Agent runtime/framework mismatch. Rebuild android/agent-runtime for MaaFw $frameworkVersion."
}
if ($Emulator) { throw 'The gacha agent profile currently targets arm64-v8a phones only.' }

$sw = [System.Diagnostics.Stopwatch]::StartNew()
Push-Location $MaaFwAppDir
try {
    $task = if ($Release) { ':app:assembleRelease' } else { ':app:assembleDebug' }
    & .\gradlew.bat $task
    if ($LASTEXITCODE -ne 0) { throw "Gradle task failed: $task" }
} finally {
    Pop-Location
}
$sw.Stop()

$kind = if ($Release) { 'release' } else { 'debug' }
$apk = Get-ChildItem (Join-Path $MaaFwAppDir "app\build\outputs\apk\$kind") -Filter '*.apk' -Recurse |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $apk) { throw 'APK output not found.' }
$outputDir = Join-Path $PSScriptRoot 'output'
New-Item -ItemType Directory -Force -Path $outputDir | Out-Null
$suffix = if ($Release) { 'release-arm64' } elseif ($Emulator) { 'debug-arm64-x86_64' } else { 'debug-arm64' }
$outputApk = Join-Path $outputDir "MBCCtools-$suffix.apk"
Copy-Item $apk.FullName $outputApk -Force
$item = Get-Item $outputApk
$sizeMb = [Math]::Round($item.Length / 1MB, 2)
Write-Host ("APK built in {0:N1}s: {1} ({2} MB)" -f $sw.Elapsed.TotalSeconds, $item.FullName, $sizeMb)
if ($sizeMb -gt 200) {
    Write-Warning "APK size ($sizeMb MB) exceeds 200 MB! Check pi-profile.yaml excludes (e.g. agent/python/**)."
}
$item | Select-Object FullName,Length,LastWriteTime



