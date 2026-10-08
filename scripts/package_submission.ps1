<#
.SYNOPSIS
    Builds the Team Project Part 1 submission zip: [LabGroup_TeamNumber_ProjectPart1Final].zip

.DESCRIPTION
    Creates dist/<name>/ with the five required folders, then zips it:
      Engineering Report      - docs/Engineering_Report.pdf
      Project Code            - every tracked file at HEAD (git archive, so .env and caches are never included)
      Test Script             - tests/ plus run instructions
      Git Repository History  - full git bundle (clonable) + readable log and branch graph
      Docker image            - docker save tarball of the image built from HEAD's Dockerfile + load instructions

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/package_submission.ps1 -LabGroup P1 -TeamNumber 07
#>
param(
    [Parameter(Mandatory = $true)][string]$LabGroup,
    [Parameter(Mandatory = $true)][string]$TeamNumber,
    [switch]$SkipDockerImage
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function Invoke-Native([string]$Description, [scriptblock]$Command) {
    Write-Host "-> $Description"
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Description failed (exit code $LASTEXITCODE)" }
}

$name = "${LabGroup}_${TeamNumber}_ProjectPart1Final"
$distDir = Join-Path $repoRoot 'dist'
$outDir = Join-Path $distDir $name
$zipPath = Join-Path $distDir "$name.zip"

if (git status --porcelain) {
    Write-Warning 'You have uncommitted changes. The zip packages the last commit (HEAD), not your working tree.'
}
if (-not (Test-Path 'docs/Engineering_Report.pdf')) { throw 'docs/Engineering_Report.pdf not found.' }

if (Test-Path $outDir) { Remove-Item -Recurse -Force $outDir }
if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
$folders = 'Engineering Report', 'Project Code', 'Test Script', 'Git Repository History', 'Docker image'
foreach ($f in $folders) { New-Item -ItemType Directory -Force -Path (Join-Path $outDir $f) | Out-Null }

# 1. Engineering Report
Copy-Item 'docs/Engineering_Report.pdf' (Join-Path $outDir 'Engineering Report/Engineering_Report.pdf')

# 2. Project Code (tracked files only)
$codeZip = Join-Path $distDir 'code.zip'
Invoke-Native 'Exporting tracked source files (git archive HEAD)' { git archive --format=zip -o $codeZip HEAD }
Expand-Archive -Path $codeZip -DestinationPath (Join-Path $outDir 'Project Code') -Force
Remove-Item $codeZip
if (Test-Path (Join-Path $outDir 'Project Code/.env')) { throw 'Refusing to package: .env found in Project Code.' }

# 3. Test Script
Copy-Item 'tests/test_pipeline.py', 'tests/sample_ai_responses.py' (Join-Path $outDir 'Test Script')
@"
Automated test suite - runs fully offline (no GEMINI_API_KEY or network needed)

Files
  test_pipeline.py        12 procedural tests + runner (exit code 0 = all passed)
  sample_ai_responses.py  hardcoded sample Gemini API responses used by the tests

Run from the project root (the 'Project Code' folder):
  python tests/test_pipeline.py

Run inside Docker:
  docker compose run --rm test
  # or, with the image from the 'Docker image' folder loaded:
  docker run --rm projectkitchen:latest python tests/test_pipeline.py
"@ | Out-File -Encoding utf8 (Join-Path $outDir 'Test Script/HOW_TO_RUN.txt')

# 4. Git Repository History
$histDir = Join-Path $outDir 'Git Repository History'
Invoke-Native 'Creating git bundle of all branches' { git bundle create (Join-Path $histDir 'PROJECTKITCHEN.bundle') --all }
git log --all --date=iso --stat | Out-File -Encoding utf8 (Join-Path $histDir 'git_log_detailed.txt')
git log --all --graph --date=short --pretty=format:'%h %ad %an  %s%d' | Out-File -Encoding utf8 (Join-Path $histDir 'git_log_graph.txt')
@"
PROJECTKITCHEN.bundle is the complete repository history (all branches and commits).
Restore it with:
  git clone PROJECTKITCHEN.bundle PROJECTKITCHEN
  cd PROJECTKITCHEN && git log --oneline --graph --all

git_log_graph.txt     one line per commit with the branch/merge graph
git_log_detailed.txt  every commit with the files it changed
"@ | Out-File -Encoding utf8 (Join-Path $histDir 'README.txt')

# 5. Docker image
$dockerDir = Join-Path $outDir 'Docker image'
Copy-Item 'Dockerfile', 'docker-compose.yml' $dockerDir
if ($SkipDockerImage) {
    Write-Warning 'Skipping docker save (-SkipDockerImage). Only the Dockerfile is included.'
} else {
    Invoke-Native 'Building Docker image projectkitchen:latest' { docker build -t projectkitchen:latest . }
    Invoke-Native 'Verifying tests pass inside the image' { docker run --rm projectkitchen:latest python tests/test_pipeline.py }
    Invoke-Native 'Saving Docker image tarball' { docker save projectkitchen:latest -o (Join-Path $dockerDir 'projectkitchen_image.tar') }
}
@"
Load and run the pre-built image:
  docker load -i projectkitchen_image.tar
  docker run --rm -it -e GEMINI_API_KEY=your_key_here projectkitchen:latest
  docker run --rm projectkitchen:latest python tests/test_pipeline.py   # offline test suite

Or rebuild from source in the 'Project Code' folder:
  docker build -t projectkitchen:latest .
"@ | Out-File -Encoding utf8 (Join-Path $dockerDir 'HOW_TO_RUN.txt')

Write-Host '-> Compressing submission zip'
Compress-Archive -Path $outDir -DestinationPath $zipPath -CompressionLevel Optimal
$sizeMb = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
Write-Host "Done: $zipPath ($sizeMb MB)"
