<#
.SYNOPSIS
    Builds the Team Project Part 2 submission zip: [LabGroup_TeamNumber_ProjectPart2Final].zip

.DESCRIPTION
    Creates dist/<name>/ with the required folders, then zips it:
      Engineering Report                                   - the Part 2 report PDF (-ReportPath)
      Project Code                                         - every tracked file at HEAD (git archive: .env is never included)
      Test Script                                          - tests/ plus run instructions
      Git Repository History and TeamAId Task Management   - git bundle + readable logs + TeamAId export (-TeamAIdFile)
      Dockerfile                                           - Dockerfile, docker-compose.yml and run instructions
    Unless -SkipDockerCheck is given, the image is built and the test suite run inside it first.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/package_submission.ps1 -LabGroup P1 -TeamNumber 07 -TeamAIdFile C:\Downloads\teamaid.csv
#>
param(
    [Parameter(Mandatory = $true)][string]$LabGroup,
    [Parameter(Mandatory = $true)][string]$TeamNumber,
    [string]$ReportPath = 'docs/Engineering_Report_Part2.pdf',
    [string]$TeamAIdFile = '',
    [switch]$SkipDockerCheck
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

function Invoke-Native([string]$Description, [scriptblock]$Command) {
    Write-Host "-> $Description"
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Description failed (exit code $LASTEXITCODE)" }
}

$name = "${LabGroup}_${TeamNumber}_ProjectPart2Final"
$distDir = Join-Path $repoRoot 'dist'
$outDir = Join-Path $distDir $name
$zipPath = Join-Path $distDir "$name.zip"
$testCommand = 'python -m unittest discover -s tests -t .'

if (git status --porcelain --untracked-files=no) {
    Write-Warning 'You have uncommitted changes. The zip packages the last commit (HEAD), not your working tree.'
}
if (-not (Test-Path $ReportPath)) { throw "Engineering report not found at '$ReportPath'. Pass -ReportPath." }
if ($TeamAIdFile -and -not (Test-Path $TeamAIdFile)) { throw "TeamAId file not found at '$TeamAIdFile'." }
if (-not $TeamAIdFile) { Write-Warning 'No -TeamAIdFile given: remember to add the TeamAId task export before submitting.' }

if (Test-Path $outDir) { Remove-Item -Recurse -Force $outDir }
if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
$historyFolder = 'Git Repository History and TeamAId Task Management'
foreach ($f in 'Engineering Report', 'Project Code', 'Test Script', $historyFolder, 'Dockerfile') {
    New-Item -ItemType Directory -Force -Path (Join-Path $outDir $f) | Out-Null
}

# 1. Engineering Report
Copy-Item $ReportPath (Join-Path $outDir 'Engineering Report')

# 2. Project Code (tracked files only)
$codeZip = Join-Path $distDir 'code.zip'
Invoke-Native 'Exporting tracked source files (git archive HEAD)' { git archive --format=zip -o $codeZip HEAD }
Expand-Archive -Path $codeZip -DestinationPath (Join-Path $outDir 'Project Code') -Force
Remove-Item $codeZip
if (Test-Path (Join-Path $outDir 'Project Code/.env')) { throw 'Refusing to package: .env found in Project Code.' }

# 3. Test Script
Copy-Item 'tests/*.py' (Join-Path $outDir 'Test Script')
@"
Automated test suite (Python unittest) - runs fully offline: no GEMINI_API_KEY or network needed.

  test_models.py          domain classes: validation, encapsulation, serialisation
  test_ai_manager.py      AI layer: prompt, schema validation, retry policy, Gemini client errors
  test_logic_manager.py   business rules on hardcoded sample AI responses, rule order, OCP/LSP checks
  test_data_manager.py    JSON persistence, corrupt/missing files, history filters
  test_io_manager.py      form validation and display helpers
  test_kitchen_service.py the pipeline and the recipe re-check (new feature)
  test_web_app.py         every web page end to end, including the recipe detail page
  sample_ai_responses.py  hardcoded sample AI replies and a scripted AI client

Run from the project root (the 'Project Code' folder), after: pip install -r requirements.txt
  $testCommand -v

Run inside Docker:
  docker compose run --rm test
"@ | Out-File -Encoding utf8 (Join-Path $outDir 'Test Script/HOW_TO_RUN.txt')

# 4. Git Repository History and TeamAId Task Management
$histDir = Join-Path $outDir $historyFolder
Invoke-Native 'Creating git bundle of all branches' { git bundle create (Join-Path $histDir 'PROJECTKITCHEN.bundle') --all }
git log --all --date=iso --stat | Out-File -Encoding utf8 (Join-Path $histDir 'git_log_detailed.txt')
git log --all --graph --date=short --pretty=format:'%h %ad %an  %s%d' | Out-File -Encoding utf8 (Join-Path $histDir 'git_log_graph.txt')
if ($TeamAIdFile) { Copy-Item $TeamAIdFile $histDir }
@"
PROJECTKITCHEN.bundle is the complete repository history (all branches and commits).
Restore it with:
  git clone PROJECTKITCHEN.bundle PROJECTKITCHEN
  cd PROJECTKITCHEN && git log --oneline --graph --all

git_log_graph.txt     one line per commit with the branch/merge graph
git_log_detailed.txt  every commit with the files it changed
"@ | Out-File -Encoding utf8 (Join-Path $histDir 'README.txt')

# 5. Dockerfile
$dockerDir = Join-Path $outDir 'Dockerfile'
Copy-Item 'Dockerfile', 'docker-compose.yml', '.env.example' $dockerDir
if (-not $SkipDockerCheck) {
    Invoke-Native 'Building Docker image projectkitchen:latest' { docker build -t projectkitchen:latest . }
    Invoke-Native 'Verifying tests pass inside the image' { docker run --rm projectkitchen:latest python -m unittest discover -s tests -t . }
}
@"
From the 'Project Code' folder:

  Build and start the website (http://localhost:5000):
    copy .env.example to .env and set GEMINI_API_KEY, then
    docker compose up --build app

  Run the automated tests in the container (no API key needed):
    docker compose run --rm test

Without compose:
  docker build -t projectkitchen .
  docker run --rm -p 5000:5000 -e GEMINI_API_KEY=your_key_here -v "%cd%\data:/app/data" projectkitchen
  docker run --rm projectkitchen $testCommand
"@ | Out-File -Encoding utf8 (Join-Path $dockerDir 'HOW_TO_RUN.txt')

Write-Host '-> Compressing submission zip'
Compress-Archive -Path $outDir -DestinationPath $zipPath -CompressionLevel Optimal
$sizeMb = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
Write-Host "Done: $zipPath ($sizeMb MB)"
