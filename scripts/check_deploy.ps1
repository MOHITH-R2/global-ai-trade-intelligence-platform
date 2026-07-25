param(
    [string]$Python = "venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $Python)) {
    $Python = "python"
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$ArgumentList = @()
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code $LASTEXITCODE`: $FilePath $($ArgumentList -join ' ')"
    }
}

Write-Host "Using Python: $Python"

Invoke-Checked -FilePath $Python -ArgumentList @(
    "-B",
    "-m",
    "py_compile",
    "backend/main.py",
    "backend/aisstream_client.py",
    "database/connection.py",
    "database/init_db.py",
    "database/models.py",
    "frontend/app.py",
    "ml/risk_engine.py",
    "reports/generate_pdf.py"
)

Invoke-Checked -FilePath $Python -ArgumentList @(
    "-B",
    "-m",
    "pytest",
    "-p",
    "no:cacheprovider"
)

Write-Host "Deploy checks passed."
