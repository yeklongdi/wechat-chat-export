[CmdletBinding()]
param(
    [string]$Python = 'python',
    [string]$CacheDirectory = (Join-Path $env:LOCALAPPDATA 'wechat-chat-export'),
    [switch]$WithTests
)

$ErrorActionPreference = 'Stop'
$taskSkillRoot = Split-Path -Parent $PSScriptRoot
$taskEnvironment = Join-Path $CacheDirectory 'venv'
$taskEnvironmentPython = Join-Path $taskEnvironment 'Scripts\python.exe'
$taskRequirements = Join-Path $taskSkillRoot 'requirements.txt'
if ($WithTests) {
    $taskRequirements = Join-Path $taskSkillRoot 'requirements-dev.txt'
}

if (-not (Test-Path -LiteralPath $taskEnvironmentPython)) {
    New-Item -ItemType Directory -Path $CacheDirectory -Force | Out-Null
    & $Python -m venv $taskEnvironment
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create the Python environment.' }
}

& $taskEnvironmentPython -c "import sys,sqlite3; assert sys.version_info >= (3,11), 'Python 3.11+ required'; assert hasattr(sqlite3.Connection,'deserialize'), 'sqlite3.deserialize required'"
if ($LASTEXITCODE -ne 0) { throw 'The Python runtime is not compatible.' }

if (Get-Command uv -ErrorAction SilentlyContinue) {
    & uv pip install --python $taskEnvironmentPython --link-mode copy -r $taskRequirements
} else {
    & $taskEnvironmentPython -m pip install -r $taskRequirements
}
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }

if ($WithTests) {
    & $taskEnvironmentPython -B -m pytest -q (Join-Path $taskSkillRoot 'tests') -p no:cacheprovider
    if ($LASTEXITCODE -ne 0) { throw 'Synthetic tests failed.' }
}

Write-Output "Python: $taskEnvironmentPython"
Write-Output 'Setup complete. No WeChat data was accessed.'
