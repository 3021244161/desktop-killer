param(
    [string]$Python = 'python',
    [string]$OutputDirectory = ''
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $projectRoot 'dist'
}
$manualPath = Join-Path $projectRoot 'output\pdf\玩法指南.pdf'
$licensePath = Join-Path $projectRoot 'packaging\licenses'
if (-not (Test-Path -LiteralPath $manualPath -PathType Leaf)) {
    throw 'Build and visually verify output/pdf/玩法指南.pdf before packaging.'
}
if (-not (Test-Path -LiteralPath (Join-Path $licensePath 'NOTICE.txt') -PathType Leaf)) {
    throw 'Collect the original dependency licenses before packaging.'
}
& $Python -c 'import struct, PyInstaller; assert struct.calcsize("P") == 8, "Use a 64-bit Python interpreter"; print("PyInstaller", PyInstaller.__version__)'
if ($LASTEXITCODE -ne 0) { throw 'A 64-bit Python with PyInstaller is required. No dependencies were downloaded.' }
& $Python (Join-Path $PSScriptRoot 'write_version_info.py')
if ($LASTEXITCODE -ne 0) { throw 'Could not generate the executable version resource.' }
& $Python -m PyInstaller --noconfirm --distpath $OutputDirectory --workpath (Join-Path $projectRoot 'build') (Join-Path $projectRoot 'DesktopKiller.spec')
if ($LASTEXITCODE -ne 0) { throw 'Packaging failed; inspect the PyInstaller output.' }
$packageRoot = Join-Path $OutputDirectory 'DesktopKiller'
$docsPath = Join-Path $packageRoot 'docs'
New-Item -ItemType Directory -Path $docsPath -Force | Out-Null
Copy-Item -LiteralPath $manualPath -Destination (Join-Path $docsPath '玩法指南.pdf') -Force
Copy-Item -LiteralPath $licensePath -Destination $packageRoot -Recurse -Force
Copy-Item -LiteralPath (Join-Path $licensePath 'NOTICE.txt') -Destination (Join-Path $packageRoot 'NOTICE.txt') -Force
foreach ($documentName in @('README.md', 'compatibility.md', 'VALIDATION.md', 'RELEASE_NOTES.md')) {
    $documentPath = Join-Path $projectRoot $documentName
    if (Test-Path -LiteralPath $documentPath -PathType Leaf) {
        Copy-Item -LiteralPath $documentPath -Destination (Join-Path $packageRoot $documentName) -Force
    }
}
Write-Output (Join-Path $OutputDirectory 'DesktopKiller\DesktopKiller.exe')
Write-Output 'Copy the whole DesktopKiller directory, including _internal. Do not copy only the .exe.'
