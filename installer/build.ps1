[CmdletBinding()]
param(
    [switch]$SkipGo,
    [switch]$SkipCpp,
    [switch]$SkipBundles,
    [switch]$SkipInstaller
)

$ErrorActionPreference = 'Stop'

$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -Path $RepoRoot

$GxxFallbacks = @(
    (Join-Path $env:USERPROFILE 'scoop\apps\mingw\current\bin\g++.exe'),
    'C:\msys64\mingw64\bin\g++.exe',
    'C:\mingw64\bin\g++.exe'
)

$IsccFallbacks = @()
if (${env:ProgramFiles(x86)}) {
    $IsccFallbacks += (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe')
}
if ($env:ProgramFiles) {
    $IsccFallbacks += (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
}
$IsccFallbacks += (Join-Path $env:USERPROFILE 'scoop\apps\inno-setup\current\ISCC.exe')

function Write-Step {
    param([string]$Message)
    Write-Host ''
    Write-Host "==> $Message"
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

function Build-GoEngine {
    $go = Find-Tool -Name 'go'
    if (-not $go) {
        return @{ Ok = $false; Reason = 'go executable not found on PATH' }
    }
    $source = Join-Path $RepoRoot 'engines\go'
    if (-not (Test-Path -LiteralPath $source)) {
        return @{ Ok = $false; Reason = "source directory not found: $source" }
    }
    $sources = @(Get-ChildItem -Path $source -Filter '*.go' -File -ErrorAction SilentlyContinue)
    if ($sources.Count -eq 0) {
        return @{ Ok = $false; Reason = "no Go source files found in $source" }
    }
    $output = Join-Path $source 'bin'
    New-Item -ItemType Directory -Force -Path $output | Out-Null
    Push-Location -Path $source
    try {
        & $go build -trimpath -ldflags '-s -w' -o 'bin\netbreak-engine.exe' .
        $code = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    if ($code -ne 0) {
        throw "go build failed with exit code $code"
    }
    $target = Join-Path $output 'netbreak-engine.exe'
    if (-not (Test-Path -LiteralPath $target)) {
        throw "go build reported success but $target is missing"
    }
    return @{ Ok = $true; Path = $target }
}

function Build-CppEngine {
    $cmake = Find-Tool -Name 'cmake'
    $gxx = Find-Tool -Name 'g++' -Fallbacks $GxxFallbacks
    if (-not $cmake) {
        return @{ Ok = $false; Reason = 'cmake executable not found on PATH' }
    }
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
    & $cmake -S $source -B $buildDir -G 'MinGW Makefiles'
    $configureCode = $LASTEXITCODE
    if ($configureCode -ne 0) {
        throw "cmake configure failed with exit code $configureCode"
    }
    & $cmake --build $buildDir --config Release
    $buildCode = $LASTEXITCODE
    if ($buildCode -ne 0) {
        throw "cmake build failed with exit code $buildCode"
    }
    $produced = Get-ChildItem -Path $buildDir -Recurse -Filter 'netbreak-native.exe' -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $produced) {
        throw 'netbreak-native.exe was not produced by the build'
    }
    $output = Join-Path $RepoRoot 'engines\cpp\bin'
    New-Item -ItemType Directory -Force -Path $output | Out-Null
    $target = Join-Path $output 'netbreak-native.exe'
    Copy-Item -LiteralPath $produced.FullName -Destination $target -Force
    return @{ Ok = $true; Path = $target }
}

function Build-Bundles {
    $python = Find-Tool -Name 'python'
    if (-not $python) {
        return @{ Ok = $false; Reason = 'python executable not found on PATH' }
    }
    $distDir = Join-Path $RepoRoot 'dist'
    $workDir = Join-Path $RepoRoot 'build'
    New-Item -ItemType Directory -Force -Path $distDir | Out-Null
    $specs = @(
        (Join-Path $RepoRoot 'installer\pyinstaller-tui.spec'),
        (Join-Path $RepoRoot 'installer\pyinstaller-gui.spec')
    )
    foreach ($spec in $specs) {
        if (-not (Test-Path -LiteralPath $spec)) {
            throw "spec file not found: $spec"
        }
        & $python -m PyInstaller --noconfirm --distpath $distDir --workpath $workDir $spec
        $code = $LASTEXITCODE
        if ($code -ne 0) {
            throw "PyInstaller failed for $spec with exit code $code"
        }
    }
    return @{ Ok = $true }
}

function Build-Installer {
    $iscc = Find-Tool -Name 'iscc' -Fallbacks $IsccFallbacks
    if (-not $iscc) {
        return @{ Ok = $false; Reason = 'iscc (Inno Setup compiler) not found' }
    }
    $script = Join-Path $RepoRoot 'installer\netbreak.iss'
    if (-not (Test-Path -LiteralPath $script)) {
        throw "installer script not found: $script"
    }
    $payloads = @(
        (Join-Path $RepoRoot 'dist\netbreak.exe'),
        (Join-Path $RepoRoot 'dist\netbreak-gui.exe')
    )
    foreach ($payload in $payloads) {
        if (-not (Test-Path -LiteralPath $payload)) {
            throw "missing installer payload: $payload"
        }
    }
    & $iscc $script
    $code = $LASTEXITCODE
    if ($code -ne 0) {
        throw "iscc failed with exit code $code"
    }
    return @{ Ok = $true; Path = (Join-Path $RepoRoot 'dist\NetBreak-Setup-2.0.0.exe') }
}

$exitCode = 0

try {
    if ($SkipGo) {
        Write-Host 'Skipping Go engine (SkipGo)'
    }
    else {
        Write-Step 'Building Go engine'
        $goResult = Build-GoEngine
        if ($goResult.Ok) {
            Write-Host ("Built {0}" -f $goResult.Path)
        }
        else {
            Write-Warning ("Go engine skipped: {0}" -f $goResult.Reason)
        }
    }

    if ($SkipCpp) {
        Write-Host 'Skipping C++ engine (SkipCpp)'
    }
    else {
        Write-Step 'Building C++ engine'
        $cppResult = Build-CppEngine
        if ($cppResult.Ok) {
            Write-Host ("Built {0}" -f $cppResult.Path)
        }
        else {
            Write-Warning ("C++ engine skipped: {0}" -f $cppResult.Reason)
        }
    }

    if ($SkipBundles) {
        Write-Host 'Skipping PyInstaller bundles (SkipBundles)'
    }
    else {
        Write-Step 'Building PyInstaller bundles'
        $bundleResult = Build-Bundles
        if ($bundleResult.Ok) {
            Write-Host 'Built dist\netbreak.exe and dist\netbreak-gui.exe'
        }
        else {
            Write-Warning ("Bundles skipped: {0}" -f $bundleResult.Reason)
        }
    }

    if ($SkipInstaller) {
        Write-Host 'Skipping Inno Setup installer (SkipInstaller)'
    }
    else {
        Write-Step 'Compiling Inno Setup installer'
        $installerResult = Build-Installer
        if ($installerResult.Ok) {
            Write-Host ("Built {0}" -f $installerResult.Path)
        }
        else {
            Write-Warning ("Installer skipped: {0}" -f $installerResult.Reason)
        }
    }
}
catch {
    Write-Host ''
    Write-Host ("BUILD FAILED: {0}" -f $_.Exception.Message) -ForegroundColor Red
    $exitCode = 1
}

Write-Step 'Artifacts'
$artifacts = @(
    'engines\go\bin\netbreak-engine.exe',
    'engines\cpp\bin\netbreak-native.exe',
    'dist\netbreak.exe',
    'dist\netbreak-gui.exe',
    'dist\NetBreak-Setup-2.0.0.exe'
)
foreach ($relative in $artifacts) {
    $full = Join-Path $RepoRoot $relative
    if (Test-Path -LiteralPath $full) {
        $size = (Get-Item -LiteralPath $full).Length
        Write-Host ("  {0,-42} {1,14:N0} bytes" -f $relative, $size)
    }
    else {
        Write-Host ("  {0,-42} {1}" -f $relative, '(not built)')
    }
}

Write-Host ''
if ($exitCode -eq 0) {
    Write-Host 'Build complete.'
}
else {
    Write-Host 'Build finished with errors.' -ForegroundColor Red
}

exit $exitCode
