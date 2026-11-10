param(
    [string]$ExecutablePath = '',
    [switch]$InspectOnly
)

# Dot-source this file to test the helpers in an isolated directory. Executing it
# always resolves the real current-user DesktopDirectory; it never uses Public.
$script:DesktopKillerShortcutName = '桌面叛乱'

function Get-ShortcutExecutablePath {
    param([Parameter(Mandatory=$true)][string]$ScriptDirectory)
    $portableTarget = Join-Path $ScriptDirectory 'DesktopKiller.exe'
    if (Test-Path -LiteralPath $portableTarget -PathType Leaf) { return $portableTarget }
    Join-Path (Split-Path -Parent $ScriptDirectory) 'dist\DesktopKiller\DesktopKiller.exe'
}

function Get-ShortcutFileHash {
    param([Parameter(Mandatory=$true)][string]$Path)
    $stream = [IO.File]::OpenRead($Path)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-', '') }
    finally { $hasher.Dispose(); $stream.Dispose() }
}

function Get-ShortcutDetails {
    param([Parameter(Mandatory=$true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw 'Shortcut does not exist.' }
    $shellObject = New-Object -ComObject WScript.Shell
    $linkObject = $null
    try {
        $linkObject = $shellObject.CreateShortcut($Path)
        $bytes = [System.IO.File]::ReadAllBytes($Path)
        if ($bytes.Length -lt 76 -or [BitConverter]::ToUInt32($bytes, 0) -ne 76) {
            throw 'Invalid Shell Link header.'
        }
        [pscustomobject]@{
            ShortcutPath = $Path
            TargetPath = $linkObject.TargetPath
            WorkingDirectory = $linkObject.WorkingDirectory
            IconLocation = $linkObject.IconLocation
            Arguments = $linkObject.Arguments
            RunAsUser = (([BitConverter]::ToUInt32($bytes, 20) -band 0x2000) -ne 0)
        }
    } finally {
        if ($null -ne $linkObject) { [Runtime.InteropServices.Marshal]::ReleaseComObject($linkObject) | Out-Null }
        [Runtime.InteropServices.Marshal]::ReleaseComObject($shellObject) | Out-Null
    }
}

function Get-ProjectShortcutPlan {
    param([Parameter(Mandatory=$true)][string]$DesktopDirectory,
          [Parameter(Mandatory=$true)][string]$TargetPath)
    $directory = (Resolve-Path -LiteralPath $DesktopDirectory -ErrorAction Stop).Path
    $target = (Resolve-Path -LiteralPath $TargetPath -ErrorAction Stop).Path
    if (-not (Test-Path -LiteralPath $target -PathType Leaf) -or [IO.Path]::GetExtension($target) -ine '.exe') {
        throw 'The built executable is missing.'
    }
    $firstUnused = $null
    for ($number = 1; $number -le 100; $number++) {
        $filename = if ($number -eq 1) { "$script:DesktopKillerShortcutName.lnk" } else { "$script:DesktopKillerShortcutName ($number).lnk" }
        $candidate = Join-Path $directory $filename
        if (-not (Test-Path -LiteralPath $candidate)) {
            if ($null -eq $firstUnused) { $firstUnused = $candidate }
            continue
        }
        try {
            $details = Get-ShortcutDetails -Path $candidate
            # A description or matching display name is not proof of ownership.
            if ([string]::Equals([IO.Path]::GetFullPath($details.TargetPath), $target,
                                [StringComparison]::OrdinalIgnoreCase)) {
                return [pscustomobject]@{ ShortcutPath=$candidate; TargetPath=$target; Action='update';
                    ExistingHash=(Get-ShortcutFileHash -Path $candidate) }
            }
        } catch {
            # Occupied/unreadable/foreign links are left untouched.
        }
    }
    if ($null -eq $firstUnused) { throw 'No unused shortcut name was found.' }
    [pscustomobject]@{ ShortcutPath=$firstUnused; TargetPath=$target; Action='create'; ExistingHash=$null }
}

function Write-ProjectShortcut {
    param([Parameter(Mandatory=$true)]$Plan)
    $workingDirectory = [IO.Path]::GetDirectoryName($Plan.TargetPath)
    $iconLocation = "$($Plan.TargetPath),0"
    # A fresh off-desktop link cannot inherit an old shortcut's RunAs setting.
    $temporaryLink = Join-Path ([IO.Path]::GetTempPath()) ("DesktopKiller-" + [guid]::NewGuid().ToString('N') + '.lnk')
    $shellObject = New-Object -ComObject WScript.Shell
    $linkObject = $null
    try {
        $linkObject = $shellObject.CreateShortcut($temporaryLink)
        $linkObject.TargetPath = $Plan.TargetPath
        $linkObject.WorkingDirectory = $workingDirectory
        $linkObject.IconLocation = $iconLocation
        $linkObject.Arguments = ''
        $linkObject.Description = 'Desktop Killer / 桌面叛乱'
        $linkObject.WindowStyle = 1
        $linkObject.Save()
        $created = Get-ShortcutDetails -Path $temporaryLink
        if ($created.RunAsUser) { throw 'Unexpected RunAs flag on the new shortcut.' }
        $bytes = [IO.File]::ReadAllBytes($temporaryLink)
        $fileMode = if ($Plan.Action -eq 'update') { [IO.FileMode]::Open } else { [IO.FileMode]::CreateNew }
        # Lock against writes/deletes while verifying an owned existing file.
        # CreateNew also refuses a name claimed since the read-only planning step.
        $stream = [IO.File]::Open($Plan.ShortcutPath, $fileMode, [IO.FileAccess]::ReadWrite, [IO.FileShare]::Read)
        try {
            if ($Plan.Action -eq 'update') {
                $hasher = [Security.Cryptography.SHA256]::Create()
                try { $currentHash = [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-', '') }
                finally { $hasher.Dispose() }
                if ($currentHash -ne $Plan.ExistingHash) { throw 'Shortcut changed after inspection; refusing to overwrite it.' }
            }
            $stream.Position = 0
            $stream.SetLength(0)
            $stream.Write($bytes, 0, $bytes.Length)
            $stream.Flush($true)
        } finally { $stream.Dispose() }
    } finally {
        if ($null -ne $linkObject) { [Runtime.InteropServices.Marshal]::ReleaseComObject($linkObject) | Out-Null }
        [Runtime.InteropServices.Marshal]::ReleaseComObject($shellObject) | Out-Null
        if ([IO.File]::Exists($temporaryLink)) { [IO.File]::Delete($temporaryLink) }
    }
    $verified = Get-ShortcutDetails -Path $Plan.ShortcutPath
    if ($verified.TargetPath -ine $Plan.TargetPath -or $verified.WorkingDirectory -ine $workingDirectory -or
        $verified.IconLocation -ine $iconLocation -or $verified.Arguments -ne '' -or $verified.RunAsUser) {
        throw 'Shortcut read-back verification failed.'
    }
    $verified | Add-Member -NotePropertyName Action -NotePropertyValue $Plan.Action -PassThru
}

if ($MyInvocation.InvocationName -ne '.') {
    $ErrorActionPreference = 'Stop'
    if ([string]::IsNullOrWhiteSpace($ExecutablePath)) {
        $ExecutablePath = Get-ShortcutExecutablePath -ScriptDirectory $PSScriptRoot
    }
    $desktop = [Environment]::GetFolderPath([Environment+SpecialFolder]::DesktopDirectory)
    if ([string]::IsNullOrWhiteSpace($desktop)) { throw 'Current user DesktopDirectory is unavailable.' }
    $plan = Get-ProjectShortcutPlan -DesktopDirectory $desktop -TargetPath $ExecutablePath
    if ($InspectOnly) { $plan | ConvertTo-Json }
    else { Write-ProjectShortcut -Plan $plan | ConvertTo-Json }
}
