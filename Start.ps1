$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$scorePython = Join-Path $PSScriptRoot '.venv/Scripts/pythonw.exe'
if (!(Test-Path -LiteralPath $scorePython)) { throw 'MusicScore Python environment is missing.' }
Start-Process -FilePath $scorePython -ArgumentList ('"' + (Join-Path $PSScriptRoot 'desktop.py') + '"') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden
