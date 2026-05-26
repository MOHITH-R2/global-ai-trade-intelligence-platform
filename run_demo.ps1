param(
    [int]$BackendPort = 8001,
    [int]$FrontendPort = 8502,
    [switch]$Restart,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root "venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    throw "Virtual environment not found. Run: python -m venv venv; venv\Scripts\pip install -r requirements.txt"
}

function Get-PortOwner {
    param([int]$Port)
    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($connection) {
        return $connection.OwningProcess
    }
    return $null
}

function Start-ServiceIfNeeded {
    param(
        [string]$Name,
        [int]$Port,
        [string]$Arguments,
        [string]$Url
    )

    if (-not $Restart -and (Test-UrlReady -Url $Url -TimeoutSec 2)) {
        Write-Host "$Name already running: $Url"
        return
    }

    $existingPid = Get-PortOwner -Port $Port
    if ($existingPid -and $Restart) {
        Write-Host "Stopping existing $Name on port $Port (PID $existingPid)..."
        Stop-Process -Id $existingPid -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
        $existingPid = Get-PortOwner -Port $Port
    }

    if ($existingPid) {
        Write-Host "$Name already running on port $Port (PID $existingPid). Use .\run_demo.ps1 -Restart to restart it."
        return
    }

    $process = Start-Process -FilePath $python `
        -ArgumentList $Arguments `
        -WorkingDirectory $root `
        -WindowStyle Hidden `
        -PassThru
    Write-Host "Started $Name on port $Port (PID $($process.Id))."
}

function Test-UrlReady {
    param(
        [string]$Url,
        [int]$TimeoutSec = 2
    )
    try {
        $response = Invoke-WebRequest -UseBasicParsing $Url -TimeoutSec $TimeoutSec
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500)
    } catch {
        return $false
    }
}

function Wait-ForUrl {
    param(
        [string]$Name,
        [string]$Url,
        [int]$Seconds = 35
    )

    Write-Host "Waiting for $Name..."
    for ($i = 0; $i -lt $Seconds; $i++) {
        if (Test-UrlReady -Url $Url -TimeoutSec 2) {
            Write-Host "$Name is ready: $Url"
            return $true
        }
        Start-Sleep -Seconds 1
    }
    Write-Warning "$Name did not respond at $Url within $Seconds seconds."
    return $false
}

$env:API_BASE = "http://127.0.0.1:$BackendPort"
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = "false"
$backendUrl = "http://127.0.0.1:$BackendPort/health"
$frontendUrl = "http://127.0.0.1:$FrontendPort"

Start-ServiceIfNeeded `
    -Name "Backend API" `
    -Port $BackendPort `
    -Arguments "-m uvicorn backend.main:app --host 127.0.0.1 --port $BackendPort --log-level warning" `
    -Url $backendUrl

Start-ServiceIfNeeded `
    -Name "Streamlit app" `
    -Port $FrontendPort `
    -Arguments "-m streamlit run frontend/app.py --server.port $FrontendPort --server.address 127.0.0.1 --server.headless true --browser.gatherUsageStats false" `
    -Url $frontendUrl

$backendReady = Wait-ForUrl -Name "Backend API" -Url $backendUrl
$frontendReady = Wait-ForUrl -Name "Streamlit app" -Url $frontendUrl

Write-Host ""
Write-Host "Backend API: http://127.0.0.1:$BackendPort"
Write-Host "Streamlit app: http://127.0.0.1:$FrontendPort"
Write-Host "Demo path: log in, open Dashboard, then Command Center > AI Captain."

if ($frontendReady -and -not $NoBrowser) {
    Write-Host "Opening browser..."
    Start-Process $frontendUrl
}

if (-not $backendReady -or -not $frontendReady) {
    Write-Host ""
    Write-Host "If it still does not open, check:"
    Write-Host "  1. venv exists and dependencies are installed"
    Write-Host "  2. ports $BackendPort and $FrontendPort are not blocked"
    Write-Host "  3. try: .\run_demo.ps1 -Restart"
}
