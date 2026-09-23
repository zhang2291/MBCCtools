param(
    [string]$Message = "",
    [switch]$UseCurrentCommit
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

function Assert-GitSuccess([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed (git exit code $LASTEXITCODE)"
    }
}

$branch = (git branch --show-current).Trim()
Assert-GitSuccess 'Read current branch'
if ($branch -ne 'main') {
    throw "Resource release must be published from main. Current branch: $branch"
}

$staged = @(git diff --cached --name-only)
Assert-GitSuccess 'Check staged files'
if ($staged.Count -gt 0) {
    throw "There are already staged files. Commit or unstage them before publishing resources."
}
$jsonFiles = @((Get-Item '.\interface.json')) + @(Get-ChildItem '.\resource' -Recurse -Filter '*.json' -File | Where-Object { $_.Name -ne 'default_pipeline.json' })
foreach ($file in $jsonFiles) {
    try {
        Get-Content $file.FullName -Raw -Encoding UTF8 | ConvertFrom-Json | Out-Null
    } catch {
        throw "Invalid JSON: $($file.FullName)`n$($_.Exception.Message)"
    }
}
Write-Host "Validated $($jsonFiles.Count) JSON files."

$tag = 'resource-v' + (Get-Date -Format 'yyyyMMdd-HHmmss')
if (-not $UseCurrentCommit) {
    git add -- interface.json resource .github/workflows/publish-resource.yml publish-resource.ps1
    Assert-GitSuccess 'Stage resources'

    git diff --cached --quiet -- interface.json resource
    if ($LASTEXITCODE -eq 0) {
        throw 'No interface.json/resource changes to publish. Use -UseCurrentCommit to release the current commit.'
    }

    $commitMessage = if ($Message) { $Message } else { "resource: publish $tag" }
    git commit -m $commitMessage
    Assert-GitSuccess 'Commit resources'
}
git push origin main
Assert-GitSuccess 'Push main'

git tag -a $tag -m "MBCCtools resource release $tag"
Assert-GitSuccess 'Create resource tag'

git push origin $tag
Assert-GitSuccess 'Push resource tag'

$remote = (git remote get-url origin).Trim()
$repo = $remote -replace '^https://github.com/', '' -replace '\.git$', ''
Write-Host ''
Write-Host "Resource release triggered: $tag"
Write-Host "GitHub Actions will package interface.json + resource/** and publish a prerelease."
if ($repo -match '^[^/]+/[^/]+$') {
    Write-Host "Actions: https://github.com/$repo/actions/workflows/publish-resource.yml"
}
Write-Host 'After the workflow succeeds, open MBCCtools on the phone and tap Check resource update.'
