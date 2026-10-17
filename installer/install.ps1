[CmdletBinding()]
param(
    [string]$Prefix = (Join-Path $env:LOCALAPPDATA 'NetBreak'),
    [switch]$WithEngines,
    [switch]$NoPath,
    [switch]$Uninstall,
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Prefix = [System.IO.Path]::GetFullPath($Prefix)
$VenvDir = Join-Path $Prefix 'venv'
$ScriptsDir = Join-Path $VenvDir 'Scripts'
$VenvPython = Join-Path $ScriptsDir 'python.exe'
$TuiExe = Join-Path $ScriptsDir 'netbreak.exe'
$GuiExe = Join-Path $ScriptsDir 'netbreak-gui.exe'

$GxxFallbacks = @(
    (Join-Path $env:USERPROFILE 'scoop\apps\mingw\current\bin\g++.exe'),
    'C:\msys64\mingw64\bin\g++.exe',
    'C:\mingw64\bin\g++.exe'
)

function Write-Info {
    param([string]$Message)
    if (-not $Quiet) {
        Write-Host $Message
    }
}

function Join-Parts {
    param([string[]]$Parts)
    $result = $Parts[0]
    for ($index = 1; $index -lt $Parts.Count; $index++) {
        $result = Join-Path $result $Parts[$index]
    }
    return $result
}

function Get-Python {
    $candidates = @()
    $py = Get-Command -Name 'py' -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($py) {
        $candidates += , @($py.Source, @('-3'))
    }
    $all = @(Get-Command -Name 'python' -All -ErrorAction SilentlyContinue)
    foreach ($entry in $all) {
        $candidates += , @($entry.Source, @())
    }
    foreach ($candidate in $candidates) {
        $exe = $candidate[0]
        $arguments = $candidate[1]
        $version = $null
        $previousPreference = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            $version = & $exe @arguments -c "import sys; sys.stdout.write('%d.%d' % (sys.version_info[0], sys.version_info[1]))" 2>$null
        }
        catch {
            $version = $null
        }
        finally {
            $ErrorActionPreference = $previousPreference
        }
        if (-not $version) {
            continue
        }
        $version = (@($version)[-1]).ToString().Trim()
        if ($version -notmatch '^(\d+)\.(\d+)$') {
            continue
        }
        $major = [int]$Matches[1]
        $minor = [int]$Matches[2]
        if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 10)) {
            return @{ Exe = $exe; Args = $arguments; Display = $version }
        }
    }
    return $null
}

function Find-Tool {
    param(
        [string]$Name,
        [string[]]$Fallbacks = @()
    )
    $command = Get-Command -Name $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) {
        return $command.Source
    }
    foreach ($candidate in $Fallbacks) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    return $null
}

function Invoke-Native {
    param(
        [string]$File,
        [string[]]$Arguments
    )
    if ($Quiet) {
        & $File @Arguments | Out-Null
    }
    else {
        & $File @Arguments
    }
    return $LASTEXITCODE
}

function Add-UserPath {
    param([string]$Directory)
    $current = [Environment]::GetEnvironmentVariable('Path', 'User')
    if (-not $current) {
        $current = ''
    }
    $target = $Directory.TrimEnd('\')
    $present = $false
    foreach ($entry in $current.Split(';')) {
        if ($entry -and $entry.TrimEnd('\') -ieq $target) {
            $present = $true
        }
    }
    if (-not $present) {
        $updated = $current.TrimEnd(';')
        if ($updated -ne '') {
            $updated = $updated + ';'
        }
        $updated = $updated + $Directory
        [Environment]::SetEnvironmentVariable('Path', $updated, 'User')
        Write-Info "Added $Directory to the user PATH."
    }
    else {
        Write-Info "User PATH already contains $Directory."
    }
    $inSession = $false
    foreach ($entry in $env:PATH.Split(';')) {
        if ($entry -and $entry.TrimEnd('\') -ieq $target) {
            $inSession = $true
        }
    }
    if (-not $inSession) {
        $env:PATH = $env:PATH + ';' + $Directory
    }
}

function New-Shortcut {
    param(
        [string]$Path,
        [string]$Target,
        [string]$WorkingDirectory,
        [string]$Description
    )
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($Path)
    $shortcut.TargetPath = $Target
    $shortcut.WorkingDirectory = $WorkingDirectory
    $shortcut.Description = $Description
    $shortcut.Save()
}

function Build-GoEngine {
    param([string]$Destination)
    $go = Find-Tool -Name 'go'
    if (-not $go) {
        return @{ Ok = $false; Reason = 'go executable not found' }
    }
    $source = Join-Path $RepoRoot 'engines\go'
    if (-not (Test-Path -LiteralPath $source)) {
        return @{ Ok = $false; Reason = "source directory not found: $source" }
    }
    $sources = @(Get-ChildItem -Path $source -Filter '*.go' -File -ErrorAction SilentlyContinue)
    if ($sources.Count -eq 0) {
        return @{ Ok = $false; Reason = "no Go source files found in $source" }
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $source 'bin') | Out-Null
    Push-Location -Path $source
    try {
        $code = Invoke-Native -File $go -Arguments @('build', '-trimpath', '-ldflags', '-s -w', '-o', 'bin\netbreak-engine.exe', '.')
    }
    finally {
        Pop-Location
    }
    if ($code -ne 0) {
        throw "go build failed with exit code $code"
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $target = Join-Path $Destination 'netbreak-engine.exe'
    Copy-Item -LiteralPath (Join-Path $source 'bin\netbreak-engine.exe') -Destination $target -Force
    return @{ Ok = $true; Path = $target }
}

function Build-CppEngine {
    param([string]$Destination)
    $cmake = Find-Tool -Name 'cmake'
    if (-not $cmake) {
        return @{ Ok = $false; Reason = 'cmake executable not found' }
    }
    $gxx = Find-Tool -Name 'g++' -Fallbacks $GxxFallbacks
    if (-not $gxx) {
        return @{ Ok = $false; Reason = 'g++ (MinGW) executable not found' }
    }
    $source = Join-Path $RepoRoot 'native\cpp'
    if (-not (Test-Path -LiteralPath (Join-Path $source 'CMakeLists.txt'))) {
        return @{ Ok = $false; Reason = "CMakeLists.txt not found in $source" }
    }
    $gxxDir = Split-Path -Parent $gxx
    if ($env:PATH -notlike "*$gxxDir*") {
        $env:PATH = $env:PATH + ';' + $gxxDir
    }
    $buildDir = Join-Path $source 'build'
    $configureCode = Invoke-Native -File $cmake -Arguments @('-S', $source, '-B', $buildDir, '-G', 'MinGW Makefiles')
    if ($configureCode -ne 0) {
        throw "cmake configure failed with exit code $configureCode"
    }
    $buildCode = Invoke-Native -File $cmake -Arguments @('--build', $buildDir, '--config', 'Release')
    if ($buildCode -ne 0) {
        throw "cmake build failed with exit code $buildCode"
    }
    $produced = Get-ChildItem -Path $buildDir -Recurse -Filter 'netbreak-native.exe' -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $produced) {
        throw 'netbreak-native.exe was not produced by the build'
    }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    $target = Join-Path $Destination 'netbreak-native.exe'
    Copy-Item -LiteralPath $produced.FullName -Destination $target -Force
    return @{ Ok = $true; Path = $target }
}

$UninstallContent = @'
param()

$ErrorActionPreference = 'Continue'

$prefix = $PSScriptRoot
$venvScripts = Join-Path (Join-Path $prefix 'venv') 'Scripts'

$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'NetBreak'
if (Test-Path -LiteralPath $startMenu) {
    Remove-Item -LiteralPath $startMenu -Recurse -Force -ErrorAction SilentlyContinue
}

$desktop = [Environment]::GetFolderPath('Desktop')
$shortcuts = @(
    (Join-Path $desktop 'NetBreak (Terminal UI).lnk'),
    (Join-Path $desktop 'NetBreak Desktop.lnk')
)
foreach ($shortcut in $shortcuts) {
    if (Test-Path -LiteralPath $shortcut) {
        Remove-Item -LiteralPath $shortcut -Force -ErrorAction SilentlyContinue
    }
}

$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($userPath) {
    $target = $venvScripts.TrimEnd('\')
    $kept = @()
    foreach ($entry in $userPath.Split(';')) {
        if ($entry -eq '') {
            continue
        }
        if ($entry.TrimEnd('\') -ieq $target) {
            continue
        }
        $kept += $entry
    }
    $updated = [string]::Join(';', $kept)
    if ($updated -ne $userPath) {
        [Environment]::SetEnvironmentVariable('Path', $updated, 'User')
        Write-Host 'Removed the NetBreak virtual environment from PATH.'
    }
}

Set-Location -Path $env:TEMP
Remove-Item -LiteralPath $prefix -Recurse -Force -ErrorAction SilentlyContinue
Write-Host 'NetBreak has been removed.'
'@

if ($Uninstall) {
    $uninstaller = Join-Path $Prefix 'uninstall.ps1'
    if (Test-Path -LiteralPath $uninstaller) {
        Write-Info "Uninstalling NetBreak from $Prefix"
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $uninstaller
        if ($LASTEXITCODE -ne 0) {
            throw "the uninstaller reported exit code $LASTEXITCODE"
        }
    }
    else {
        Write-Warning "No uninstaller found at $uninstaller"
    }
    exit 0
}

$python = Get-Python
if (-not $python) {
    Write-Host ''
    Write-Host 'ERROR: Python 3.10 or newer was not found.' -ForegroundColor Red
    Write-Host 'Download it from: https://www.python.org/downloads/windows/'
    Write-Host 'Enable "Add python.exe to PATH" during setup, or install the py launcher.'
    exit 2
}
Write-Info ("Using Python {0} ({1})" -f $python.Display, $python.Exe)

if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Info "Creating virtual environment at $VenvDir"
    New-Item -ItemType Directory -Force -Path $Prefix | Out-Null
    $venvCode = Invoke-Native -File $python.Exe -Arguments (@($python.Args) + @('-m', 'venv', $VenvDir))
    if ($venvCode -ne 0) {
        throw "failed to create the virtual environment (exit code $venvCode)"
    }
}
else {
    Write-Info "Reusing the existing virtual environment at $VenvDir"
}

Write-Info 'Installing NetBreak into the virtual environment'
Push-Location -Path $RepoRoot
try {
    $pipCode = Invoke-Native -File $VenvPython -Arguments @('-m', 'pip', 'install', '--upgrade', '--disable-pip-version-check', '.')
}
finally {
    Pop-Location
}
if ($pipCode -ne 0) {
    throw "pip install failed with exit code $pipCode"
}

$engineSummary = 'not requested'
if ($WithEngines) {
    $engineRoot = Join-Path $VenvDir 'Lib\site-packages'
    try {
        $probe = & $VenvPython -c "import netbreak, pathlib; print(pathlib.Path(netbreak.__file__).resolve().parent.parent)"
        if ($LASTEXITCODE -eq 0 -and $probe) {
            $engineRoot = $probe.Trim()
        }
    }
    catch {
        $engineRoot = Join-Path $VenvDir 'Lib\site-packages'
    }
    $goDestination = Join-Parts @($engineRoot, 'engines', 'go', 'bin')
    $cppDestination = Join-Parts @($engineRoot, 'engines', 'cpp', 'bin')
    $engineNotes = @()

    Write-Info 'Building native engines'
    $goResult = Build-GoEngine -Destination $goDestination
    if ($goResult.Ok) {
        $engineNotes += 'go: built'
        Write-Info ("  go engine -> {0}" -f $goResult.Path)
    }
    else {
        $engineNotes += ('go: skipped (' + $goResult.Reason + ')')
        Write-Warning ("go engine skipped: {0}" -f $goResult.Reason)
    }

    $cppResult = Build-CppEngine -Destination $cppDestination
    if ($cppResult.Ok) {
        $engineNotes += 'native: built'
        Write-Info ("  native engine -> {0}" -f $cppResult.Path)
    }
    else {
        $engineNotes += ('native: skipped (' + $cppResult.Reason + ')')
        Write-Warning ("native engine skipped: {0}" -f $cppResult.Reason)
    }

    $engineSummary = [string]::Join('; ', $engineNotes)
}

$startMenu = Join-Path ([Environment]::GetFolderPath('Programs')) 'NetBreak'
New-Item -ItemType Directory -Force -Path $startMenu | Out-Null
$desktop = [Environment]::GetFolderPath('Desktop')

if (Test-Path -LiteralPath $TuiExe) {
    New-Shortcut -Path (Join-Path $startMenu 'NetBreak (Terminal UI).lnk') -Target $TuiExe -WorkingDirectory $env:USERPROFILE -Description 'NetBreak terminal user interface'
    New-Shortcut -Path (Join-Path $desktop 'NetBreak (Terminal UI).lnk') -Target $TuiExe -WorkingDirectory $env:USERPROFILE -Description 'NetBreak terminal user interface'
    Write-Info 'Created shortcuts for the terminal UI.'
}
else {
    Write-Warning "netbreak.exe was not found at $TuiExe; skipping its shortcuts."
}

if (Test-Path -LiteralPath $GuiExe) {
    New-Shortcut -Path (Join-Path $startMenu 'NetBreak Desktop.lnk') -Target $GuiExe -WorkingDirectory $env:USERPROFILE -Description 'NetBreak desktop interface'
    New-Shortcut -Path (Join-Path $desktop 'NetBreak Desktop.lnk') -Target $GuiExe -WorkingDirectory $env:USERPROFILE -Description 'NetBreak desktop interface'
    Write-Info 'Created shortcuts for the desktop interface.'
}
else {
    Write-Warning "netbreak-gui.exe was not found at $GuiExe; skipping its shortcuts."
}

if (-not $NoPath) {
    Add-UserPath -Directory $ScriptsDir
}
else {
    Write-Info 'Leaving PATH unchanged (NoPath).'
}

Set-Content -LiteralPath (Join-Path $Prefix 'uninstall.ps1') -Value $UninstallContent -Encoding UTF8
Write-Info "Wrote uninstaller to $(Join-Path $Prefix 'uninstall.ps1')"

Write-Host ''
Write-Host 'NetBreak installation complete.'
Write-Host ("  Location:  {0}" -f $Prefix)
Write-Host ("  Virtualenv: {0}" -f $VenvDir)
if (Test-Path -LiteralPath $TuiExe) {
    Write-Host ("  Terminal UI: {0}" -f $TuiExe)
}
else {
    Write-Host '  Terminal UI: not installed'
}
if (Test-Path -LiteralPath $GuiExe) {
    Write-Host ("  Desktop:    {0}" -f $GuiExe)
}
else {
    Write-Host '  Desktop:    not installed'
}
Write-Host ("  Engines:   {0}" -f $engineSummary)
if ($NoPath) {
    Write-Host '  PATH:      not modified (NoPath)'
}
else {
    Write-Host ("  PATH:      {0} added to the user PATH" -f $ScriptsDir)
}
Write-Host '  Launch:    Start Menu -> NetBreak (Terminal UI) / NetBreak Desktop'
Write-Host ("  Uninstall: powershell -NoProfile -ExecutionPolicy Bypass -File `"{0}`"" -f (Join-Path $Prefix 'uninstall.ps1'))
Write-Host ''
