param(
    [string]$Version = '',
    [string]$PackageDirectory = '',
    [string]$OutputDirectory = ''
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if ([string]::IsNullOrWhiteSpace($PackageDirectory)) { $PackageDirectory = Join-Path $projectRoot 'dist\DesktopKiller' }
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) { $OutputDirectory = Join-Path $projectRoot 'dist' }
if ([string]::IsNullOrWhiteSpace($Version)) {
    $versionText = Get-Content -LiteralPath (Join-Path $projectRoot 'desktop_world\__init__.py') -Raw
    if ($versionText -match '__version__\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"') { $Version = $Matches[1] }
}
if ($Version -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$') { throw 'Version must be numeric major.minor.patch.' }
$packageRoot = (Resolve-Path -LiteralPath $PackageDirectory).Path
foreach ($required in @('DesktopKiller.exe', '_internal\python310.dll', 'docs\玩法指南.pdf', 'licenses\NOTICE.txt')) {
    if (-not (Test-Path -LiteralPath (Join-Path $packageRoot $required) -PathType Leaf)) {
        throw "Incomplete portable package: missing $required"
    }
}
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$outputRoot = (Resolve-Path -LiteralPath $OutputDirectory).Path
$archivePath = Join-Path $outputRoot "DesktopKiller-v$Version-win-x64.zip"
Compress-Archive -LiteralPath $packageRoot -DestinationPath $archivePath -CompressionLevel Optimal -Force
$digest = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
$checksumPath = "$archivePath.sha256"
[System.IO.File]::WriteAllText($checksumPath, "$digest  $([System.IO.Path]::GetFileName($archivePath))`n", [System.Text.Encoding]::ASCII)
Write-Output $archivePath
Write-Output $checksumPath
Write-Output "SHA256 $digest"
