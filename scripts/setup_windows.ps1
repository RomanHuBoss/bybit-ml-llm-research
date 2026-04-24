$ErrorActionPreference = "Stop"

if (!(Test-Path ".venv")) {
    py -3.11 -m venv .venv
    if ($LASTEXITCODE -ne 0) { py -3 -m venv .venv }
}

. .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

Write-Host "Setup complete. Next: copy .env.example .env and edit PostgreSQL credentials." -ForegroundColor Green
