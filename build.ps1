$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$null = python -c "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('PyInstaller') else 1)"
if ($LASTEXITCODE -ne 0) {
    python -m pip install pyinstaller
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller installation failed."
    }
}

python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name "SideTranslate" `
    --collect-all tkinter `
    main.py

Write-Host "Build complete: $PSScriptRoot\dist\SideTranslate\SideTranslate.exe"
