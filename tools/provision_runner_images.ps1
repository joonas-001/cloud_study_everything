[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$dockerCommand = Get-Command docker.exe -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty Source
if (-not $dockerCommand) {
    $dockerCandidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin\docker.exe"),
        (Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe")
    )
    $dockerCommand = $dockerCandidates |
        Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
        Select-Object -First 1
}
if (-not $dockerCommand) {
    Write-Error "Docker CLI is not installed."
    exit 1
}
$dockerBin = Split-Path -Parent $dockerCommand
if (($env:Path -split ";") -notcontains $dockerBin) {
    $env:Path = "$dockerBin;$env:Path"
}
$profiles = @(
    @{
        Name = "GCC"
        Image = "gcc@sha256:c101370f78e4a30be178c11dd18aeee64c65d617908a98157db2392ca73ab04f"
        Command = @("g++", "-dumpfullversion")
        Expected = "15.2.0"
    },
    @{
        Name = "Python"
        Image = "python@sha256:843ef86c4efef6d065c1767855730cc974e4998e66d65d6739449f0bc0ae4d93"
        Command = @("python", "--version")
        Expected = "Python 3.14.3"
    }
)

function Test-PinnedImagePresent {
    param([Parameter(Mandatory = $true)][string]$Image)

    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $dockerCommand image inspect $Image --format "{{.Id}}" 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Invoke-BoundedImagePull {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Image
    )

    $timeoutMinutes = 30
    Write-Host "$Name pinned image is absent. Starting the first pull (hard timeout: $timeoutMinutes minutes)."

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $dockerCommand
    $startInfo.Arguments = "pull --platform linux/amd64 $Image"
    $startInfo.UseShellExecute = $false

    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $startInfo
    if (-not $process.Start()) {
        Write-Error "$Name pinned image download could not be started."
        exit 2
    }

    if (-not $process.WaitForExit($timeoutMinutes * 60 * 1000)) {
        $process.Kill()
        $process.WaitForExit()
        Write-Error "$Name pinned image download exceeded the $timeoutMinutes-minute hard timeout."
        exit 2
    }
    if ($process.ExitCode -ne 0) {
        Write-Error "$Name pinned image download failed with exit code $($process.ExitCode)."
        exit 2
    }
}

& $dockerCommand version --format "{{.Server.Version}}" | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker Desktop is not ready."
    exit 1
}

foreach ($profile in $profiles) {
    if (Test-PinnedImagePresent -Image $profile.Image) {
        Write-Host "$($profile.Name) pinned image is already present; skipping download."
    }
    else {
        Invoke-BoundedImagePull -Name $profile.Name -Image $profile.Image
    }
    $observed = & $dockerCommand run --rm `
        --network none `
        --read-only `
        --user 65534:65534 `
        --cap-drop ALL `
        --security-opt no-new-privileges=true `
        --pull never `
        --platform linux/amd64 `
        $profile.Image `
        @($profile.Command)
    if ($LASTEXITCODE -ne 0 -or ($observed -join "`n").Trim() -ne $profile.Expected) {
        Write-Error "$($profile.Name) version mismatch. Expected $($profile.Expected)."
        exit 3
    }
    Write-Host "$($profile.Name) $($profile.Expected) is pinned by digest."
}

$dataRoot = "D:\CloudStudy\DockerData"
$usedBytes = (
    Get-ChildItem -LiteralPath $dataRoot -Recurse -File -ErrorAction Stop |
        Measure-Object -Property Length -Sum
).Sum
if ($null -eq $usedBytes) {
    $usedBytes = 0
}
$usedGigabytes = [Math]::Round($usedBytes / 1GB, 3)
Write-Host "Runner data root currently uses $usedGigabytes GB of the 6 GB hard budget."
if ($usedBytes -gt 6GB) {
    Write-Error "Runner data root exceeds the 6 GB hard budget."
    exit 4
}

Write-Host "Runner images are ready. Run the project Runner security and live-container tests."
