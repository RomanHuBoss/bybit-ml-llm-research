$ErrorActionPreference = "Stop"
. .\.venv\Scripts\Activate.ps1
python -m app.init_db
