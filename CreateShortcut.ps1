param([string]$PreviousInstallDir = '')
$ErrorActionPreference = 'Stop'
$shell = New-Object -ComObject WScript.Shell
$destinations = @($PSScriptRoot, [Environment]::GetFolderPath('Desktop'))
foreach ($folder in $destinations) {
    $path = Join-Path $folder 'MusicScore.lnk'
    $shortcut = $shell.CreateShortcut($path)
    $oldTarget = if ($PreviousInstallDir) { Join-Path $PreviousInstallDir '.venv/Scripts/pythonw.exe' } else { '' }
    $ourPreviousShortcut = $PreviousInstallDir -and $shortcut.WorkingDirectory -eq $PreviousInstallDir -and $shortcut.TargetPath -eq $oldTarget
    if ((Test-Path -LiteralPath $path) -and $shortcut.WorkingDirectory -ne $PSScriptRoot -and !$ourPreviousShortcut) {
        throw "An unrelated MusicScore shortcut already exists: $path"
    }
    $shortcut.TargetPath = Join-Path $PSScriptRoot '.venv/Scripts/pythonw.exe'
    $shortcut.Arguments = '"' + (Join-Path $PSScriptRoot 'desktop.py') + '"'
    $shortcut.WorkingDirectory = $PSScriptRoot
    $shortcut.Description = 'MusicScore - Personal music transcription and score library'
    $shortcut.IconLocation = (Join-Path $PSScriptRoot 'static/app-blue.ico') + ',0'
    $shortcut.Save()
}
Write-Output 'MusicScore shortcuts created.'
