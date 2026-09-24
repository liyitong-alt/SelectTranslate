param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $venvPython)) {
    python -m venv (Join-Path $projectRoot ".venv")
}

& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $projectRoot "requirements-build.txt")
& $venvPython -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onedir `
    --noupx `
    --name "SelectTranslate" `
    --icon (Join-Path $projectRoot "assets\app-icon.ico") `
    --manifest (Join-Path $projectRoot "assets\app.manifest") `
    --add-data "$(Join-Path $projectRoot 'assets\app-icon.ico');." `
    --add-binary "$(Join-Path $projectRoot 'SelectionReader.exe');." `
    --collect-all "eng_to_ipa" `
    --distpath (Join-Path $projectRoot "dist") `
    --workpath (Join-Path $projectRoot "build") `
    --specpath (Join-Path $projectRoot "build") `
    (Join-Path $projectRoot "select_translate.py")

if ($SkipInstaller) {
    exit 0
}

$isccCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$iscc = $isccCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $iscc) {
    throw "Inno Setup 6 was not found. Install it and run scripts\build.ps1 again."
}

& $iscc (Join-Path $projectRoot "installer\SelectTranslate.iss")
