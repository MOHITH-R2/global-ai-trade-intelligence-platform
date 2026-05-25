$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root "venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "Virtual environment not found. Run: python -m venv venv; venv\Scripts\pip install -r requirements.txt"
}

$backendPort = 8001
$frontendPort = 8502
$env:API_BASE = "http://127.0.0.1:$backendPort"

Start-Process -FilePath $python `
    -ArgumentList "-m uvicorn backend.main:app --host 127.0.0.1 --port $backendPort" `
    -WorkingDirectory $root `
    -WindowStyle Hidden

Start-Process -FilePath $python `
    -ArgumentList "-m streamlit run frontend/app.py --server.port $frontendPort --server.address 127.0.0.1" `
    -WorkingDirectory $root `
    -WindowStyle Hidden

Write-Host "Backend API: http://127.0.0.1:$backendPort"
Write-Host "Streamlit app: http://127.0.0.1:$frontendPort"
Write-Host "Open the Streamlit URL, log in, then use Executive Command or Dashboard."
