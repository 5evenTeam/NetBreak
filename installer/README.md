# NetBreak installer and packaging

This directory holds the Windows packaging layer for NetBreak 2.0.0: a
maintainer build script, PyInstaller specs, an Inno Setup script, and an
end-user bootstrap installer.

| File | Purpose |
|------|---------|
| `build.ps1` | Maintainer build: native engines, PyInstaller bundles, Inno Setup installer. |
| `install.ps1` | End-user installer: creates a virtual environment, installs the package, makes shortcuts. |
| `netbreak.iss` | Inno Setup 6 script that packages the two PyInstaller executables. |
| `pyinstaller-tui.spec` | PyInstaller spec for the terminal UI (`netbreak.exe`, console). |
| `pyinstaller-gui.spec` | PyInstaller spec for the desktop UI (`netbreak-gui.exe`, windowed). |
| `uninstall.ps1` | Not stored here; `install.ps1` writes it into the install prefix at install time. |

## Toolchain

Everything here is validated against these tools (all on `PATH` unless noted):

- Python 3.14 (`python`, plus the `py` launcher).
- PyInstaller 6.22 (`python -m PyInstaller`).
- Go 1.27 (`go`).
- MinGW g++ 16.2 (`g++`) and `mingw32-make`. If the scoop MinGW install has no
  shims, the scripts fall back to
  `%USERPROFILE%\scoop\apps\mingw\current\bin`.
- CMake 4.4 (`cmake`).
- Inno Setup 6.7 (`iscc`).

`build.ps1` and `install.ps1 -WithEngines` skip a native engine with a warning
when its toolchain or source tree is missing; the pure-Python engine still
works. Real compile errors still fail the build.

## Maintainer build

From the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File installer\build.ps1
```

Switches:

- `-SkipGo` - do not build the Go engine.
- `-SkipCpp` - do not build the C++ engine.
- `-SkipBundles` - do not run PyInstaller.
- `-SkipInstaller` - do not run `iscc`.

Steps and outputs:

1. Go engine: `go build -trimpath -ldflags "-s -w" -o bin\netbreak-engine.exe .`
   run with `engines\go` as the working directory, producing
   `engines\go\bin\netbreak-engine.exe`.
2. C++ engine: `cmake -S native\cpp -B native\cpp\build -G "MinGW Makefiles"`
   then `cmake --build native\cpp\build --config Release`. The resulting
   `netbreak-native.exe` is copied to `engines\cpp\bin\netbreak-native.exe`.
3. PyInstaller bundles into `dist\`:
   - `dist\netbreak.exe` (from `pyinstaller-tui.spec`).
   - `dist\netbreak-gui.exe` (from `pyinstaller-gui.spec`).
4. Inno Setup: `iscc installer\netbreak.iss` produces
   `dist\NetBreak-Setup-2.0.0.exe`.

The script prints an artifact list with sizes and exits non-zero when a real
step fails.

## How the app finds the engines

`netbreak/core/backends.py` resolves `netbreak-engine.exe` (Go) and
`netbreak-native.exe` (C++) in this order:

1. The directory named by the `NETBREAK_ENGINE_DIR` environment variable. This
   directory is searched for the executable name directly, with no subfolders.
2. When frozen by PyInstaller: `sys._MEIPASS` and `sys._MEIPASS\engines`.
3. Relative to the directory that contains the `netbreak` package
   (`<package_parent>`): `engines\go\bin`, `engines\cpp\bin`,
   `engines\cpp\build`, `bin`, and `dist`.
4. Anywhere on `PATH`.

`<package_parent>` depends on how NetBreak is installed:

- Source checkout: the repository root, so `engines\go\bin` and
  `engines\cpp\bin` (this is why `build.ps1` writes there).
- Virtual environment: `<venv>\Lib\site-packages`, so `install.ps1 -WithEngines`
  copies the engines to
  `<venv>\Lib\site-packages\engines\go\bin` and
  `<venv>\Lib\site-packages\engines\cpp\bin`.
- Inno Setup one-file install: the exe extracts to a temp directory, so step 3
  does not point at the install directory. The installer therefore uses step 1:
  both engine executables are copied flat into `{app}\engines` and
  `NETBREAK_ENGINE_DIR` is set to `{app}\engines`.

## Inno Setup package

`netbreak.iss` packages the two **one-file** PyInstaller executables
(`dist\netbreak.exe`, `dist\netbreak-gui.exe`) into `{autopf}\NetBreak`
(`Program Files\NetBreak` for an administrative install).

- `AppId`, `AppName` (`NetBreak`), `AppVersion` (`2.0.0`), and `Publisher`
  (`5evenTeam`) are set at the top of the file.
- The `LICENSE` file from the repository root is shown as the license page and
  installed into the application directory.
- Shortcuts: `NetBreak (Terminal UI)` -> `netbreak.exe` and `NetBreak Desktop`
  -> `netbreak-gui.exe`, in the Start Menu group `NetBreak` and, when the
  `desktopicon` task is selected, on the desktop.
- The `engines` task (selected by default) copies
  `engines\go\bin\netbreak-engine.exe` and `engines\cpp\bin\netbreak-native.exe`
  into `{app}\engines` and writes the machine-wide `NETBREAK_ENGINE_DIR`
  environment variable. Both sources use `skipifsourcedoesntexist`, so the
  installer still compiles when the native engines were not built.
- Uninstall removes the shortcuts, the environment variable, and the
  application directory.

Because the environment variable is written at install time, already-running
shells will not see it; newly launched processes (including the shortcuts) will.

## End-user install (install.ps1)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File installer\install.ps1
```

Parameters:

- `-Prefix <dir>` - install location. Default:
  `%LOCALAPPDATA%\NetBreak`.
- `-WithEngines` - build the Go and C++ engines into the virtual environment.
- `-NoPath` - do not add the virtual environment's `Scripts` directory to the
  user `PATH`.
- `-Uninstall` - remove the installation at `-Prefix`.
- `-Quiet` - reduce NetBreak's own status output.

What it does:

1. Finds Python 3.10+ through the `py -3` launcher or `python`. If neither
   provides a suitable version it prints a download link
   (`https://www.python.org/downloads/windows/`) and exits.
2. Creates (or reuses) a virtual environment at `<Prefix>\venv`.
3. Runs `pip install --upgrade .` from the repository root, installing the
   `netbreak` and `netbreak-gui` console scripts into the virtual environment.
4. With `-WithEngines`, builds the native engines and copies them next to the
   installed package (see the engine search order above).
5. Creates Start Menu shortcuts (in a `NetBreak` folder) and desktop shortcuts
   for the terminal UI and the desktop UI.
6. Adds `<Prefix>\venv\Scripts` to the user `PATH` unless `-NoPath`.
7. Writes `<Prefix>\uninstall.ps1`.

Re-running the script upgrades in place: the existing virtual environment is
reused and the shortcuts, `PATH` entry, and uninstaller are rewritten.

Uninstall:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File installer\install.ps1 -Uninstall -Prefix "$env:LOCALAPPDATA\NetBreak"
```

Pass the same `-Prefix` that was used at install time. `install.ps1 -Uninstall`
runs the generated `<Prefix>\uninstall.ps1`, which removes the shortcuts, the
`PATH` entry, and the install directory.

## Assumptions

- The package declares two entry points: `netbreak = netbreak.cli:main` (the
  TUI/CLI) and `netbreak-gui = netbreak.desktop.app:main` (the Tkinter
  desktop app). `netbreak.desktop.app` must exist for the GUI bundle and the
  `netbreak-gui` script to be produced.
- For the desktop shortcut to open with no console, `netbreak-gui` should be
  declared under `[project.gui-scripts]` (a windowed launcher). The GUI
  PyInstaller spec already sets `console=False`.
- Native engine argument formats match `netbreak/core/engine.py`:
  `netbreak-engine.exe scan -host <ip> -p <spec> -timeout <s> -concurrency <n> -retries <n>`
  and
  `netbreak-native.exe connect <ip> <spec> -timeout <s> -concurrency <n> -retries <n>`.
  Both print one JSON object per line
  (`{"event":"port","port":80,"proto":"tcp","state":"open","reason":"syn-ack","rtt_ms":1.2}`);
  the native binary additionally supports `icmp <ip> <timeout_ms>`.
- The PyInstaller specs generate their entry scripts at build time into
  `build\entry\` and set `distpath` to the repository `dist\` directory. This
  keeps the entry points as top-level scripts (relative imports inside the
  `netbreak` package are resolved as package modules) and keeps the specs
  self-contained when run without `build.ps1`.
- `engines\go` is a Go module (`main` package); `native\cpp` contains a
  `CMakeLists.txt` whose target is `netbreak-native`.

## Validation

PowerShell syntax check (no execution):

```powershell
powershell -NoProfile -Command "$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('installer\install.ps1',[ref]$null,[ref]$e); if($e){$e; exit 1} else {'OK'}"
powershell -NoProfile -Command "$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('installer\build.ps1',[ref]$null,[ref]$e); if($e){$e; exit 1} else {'OK'}"
```

Spec syntax check:

```powershell
python -c "import ast; ast.parse(open(r'installer\pyinstaller-tui.spec', encoding='utf-8').read())"
python -c "import ast; ast.parse(open(r'installer\pyinstaller-gui.spec', encoding='utf-8').read())"
```

Confirm the Inno Setup compiler is available (do not compile until `dist\`
contains both executables):

```powershell
iscc /?
```
