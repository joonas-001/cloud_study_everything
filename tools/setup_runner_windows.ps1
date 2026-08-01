[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$dataRoot = "D:\CloudStudy\DockerData"
$downloadRoot = "D:\CloudStudy\Downloads"
$logRoot = "D:\CloudStudy\Logs"
$installerPath = Join-Path $downloadRoot "DockerDesktopInstaller.exe"
$dockerInstallerUrl = "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe"

function Stop-WithMessage {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message,
        [int]$ExitCode = 1
    )
    Write-Error $Message
    exit $ExitCode
}

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [string[]]$Arguments = @()
    )
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $output = & $FilePath @Arguments 2>&1
        $exitCode = $LASTEXITCODE
        $output | ForEach-Object { Write-Host $_ }
        return $exitCode
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

$virtualization = Get-CimInstance Win32_Processor |
    Select-Object -First 1 -ExpandProperty VirtualizationFirmwareEnabled
$hypervisorPresent = Get-CimInstance Win32_ComputerSystem |
    Select-Object -ExpandProperty HypervisorPresent
if (-not $virtualization -and -not $hypervisorPresent) {
    Stop-WithMessage "Enable CPU virtualization in BIOS/UEFI and restart. No changes were made." 2
}

$dDrive = Get-Volume -DriveLetter D
if ($dDrive.FileSystem -ne "NTFS") {
    Stop-WithMessage "D: must use NTFS. Current filesystem: $($dDrive.FileSystem)." 3
}
if ($dDrive.SizeRemaining -lt 8GB) {
    Stop-WithMessage "D: must have at least 8 GB free." 4
}

$principal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
$isAdministrator = $principal.IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdministrator) {
    Stop-WithMessage "Run this script from an elevated PowerShell to enable WSL2." 5
}

New-Item -ItemType Directory -Path $dataRoot -Force | Out-Null
New-Item -ItemType Directory -Path $downloadRoot -Force | Out-Null
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
Start-Transcript -LiteralPath (Join-Path $logRoot "setup-runner-windows.log") -Append |
    Out-Null

$wslVersionExitCode = Invoke-NativeCommand -FilePath "wsl.exe" -Arguments @("--version")
if ($wslVersionExitCode -ne 0) {
    $wslInstallExitCode = Invoke-NativeCommand `
        -FilePath "wsl.exe" `
        -Arguments @("--install", "--no-distribution")
    if ($wslInstallExitCode -ne 0) {
        Stop-WithMessage "WSL installation failed. Check Windows optional features and logs." 6
    }
    Write-Host "WSL features are enabled. Restart Windows and run this script again."
    exit 3010
}

$wslUpdateExitCode = Invoke-NativeCommand -FilePath "wsl.exe" -Arguments @("--update")
if ($wslUpdateExitCode -ne 0) {
    Stop-WithMessage "WSL update failed. Docker Desktop was not installed." 7
}
$wslDefaultExitCode = Invoke-NativeCommand `
    -FilePath "wsl.exe" `
    -Arguments @("--set-default-version", "2")
if ($wslDefaultExitCode -ne 0) {
    Stop-WithMessage "Could not set the default WSL version to 2." 8
}

if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
    Invoke-WebRequest -Uri $dockerInstallerUrl -OutFile $installerPath
}
$signature = Get-AuthenticodeSignature -LiteralPath $installerPath
if ($signature.Status -ne "Valid" -or $signature.SignerCertificate.Subject -notmatch "Docker") {
    Stop-WithMessage "Docker Desktop installer signature validation failed." 9
}

$arguments = @(
    "install",
    "--user",
    "--quiet",
    "--accept-license",
    "--backend=wsl-2",
    "--no-windows-containers",
    "--wsl-default-data-root=$dataRoot"
)
$process = Start-Process -FilePath $installerPath -ArgumentList $arguments -Wait -PassThru
if ($process.ExitCode -ne 0) {
    Stop-WithMessage "Docker Desktop installer exit code: $($process.ExitCode)." 10
}

Write-Host "Docker Desktop per-user installation completed. Data root: $dataRoot"
Write-Host "Start Docker Desktop, wait until ready, then run tools\provision_runner_images.ps1."
Stop-Transcript | Out-Null
