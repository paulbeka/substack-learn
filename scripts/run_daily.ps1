$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectDir
& "$projectDir\.venv\Scripts\python.exe" -m french_bot.cli run-daily
exit $LASTEXITCODE

