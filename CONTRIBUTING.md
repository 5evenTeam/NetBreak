# Contributing to NetBreak

Thanks for taking the time to help. This document covers how to set up a
development environment, the conventions the project follows, and what a pull
request should look like.

## Development environment

NetBreak needs Python 3.10 or newer. The native engines and the Windows
installer need extra tools; you can work on the Python side without them,
because the Python engine is always available.

### Windows

Install Python 3.10+ (the `py` launcher is convenient) and create a virtual
environment:

```powershell
git clone https://github.com/5evenTeam/NetBreak.git
cd NetBreak
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

To build the native engines as well, install:

- Go (for `engines/go`).
- MinGW-w64 `g++` and `mingw32-make` (for `native/cpp`). With scoop, `g++` is at
  `%USERPROFILE%\scoop\apps\mingw\current\bin`.
- CMake, for the CMake build of the native engine.
- Inno Setup 6, only if you are building the installer.

### macOS and Linux

```bash
git clone https://github.com/5evenTeam/NetBreak.git
cd NetBreak
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

The C++ engine is a Windows-focused helper, but the source keeps POSIX
fallbacks and the CMake project builds on Unix if you want to work on it there.

## Source conventions

The project owner asks that the source code carry no comments. Keep Python, Go
and C++ sources comment-free: prefer clear names, small functions and explicit
types over explanatory comments. Docstrings are not used either; if something
needs explaining, that belongs in the docs under `docs/` or in this file.

Markdown documentation, by contrast, is plain prose. Write it the way a
maintainer would: first person plural or neutral, no emoji, no marketing
language, sensible headings, and honest about what the tool does and does not
do.

## Running the tests

```bash
python -m pytest
```

The suite runs against local listeners and stubs only, so it needs no network
access. The TUI tests mount the app headlessly through Textual's `run_test` and
skip if Textual is missing. The native-engine tests skip when the matching
binary has not been built.

Run a single file while iterating:

```bash
python -m pytest tests/test_engine.py
```

## Building the native engines

Go engine, from `engines/go`:

```bash
go build -trimpath -ldflags "-s -w" -o bin/netbreak-engine.exe .
```

C++ engine, from the repository root with MinGW:

```bash
g++ -std=c++17 -O3 -Wall -Wextra -static -static-libgcc -static-libstdc++ \
  -o engines/cpp/bin/netbreak-native.exe \
  native/cpp/src/main.cpp native/cpp/src/icmp.cpp -lws2_32 -liphlpapi
```

Or through CMake:

```bash
cmake -S native/cpp -B native/cpp/build -G "MinGW Makefiles"
cmake --build native/cpp/build --config Release
```

Build a development engine with the usual `go build -o bin/netbreak-engine.exe .`
and place it where `netbreak --list-engines` can see it.

On Windows, `installer/build.ps1` builds both engines, the PyInstaller bundles
and the Inno Setup installer in one pass. The flags `-SkipGo`, `-SkipCpp`,
`-SkipBundles` and `-SkipInstaller` let you run only the parts you need.
`installer/install.ps1 -WithEngines` builds the engines into a virtual
environment and is handy for testing an installed layout.

## Commit messages

Use an imperative subject line of at most 72 characters, for example:

```
Add top-ports flag to the CLI
Fix dash-range parsing for single-octet ends
```

Add a body when the change needs more context, separated from the subject by a
blank line. Keep unrelated changes in separate commits where you can.

## Pull request checklist

Before opening a pull request, make sure that:

- `python -m pytest` passes.
- New behaviour is covered by a test, or you explain why it cannot be.
- The sources you touched remain comment-free.
- Any user-facing change is reflected in `README.md`, `docs/`, or `CHANGELOG.md`.
- The pull request describes what changed, why, and how you verified it.

Keep pull requests focused. If a change grows into several unrelated pieces,
split it up.

## Reporting a bug

Open an issue at
[github.com/5evenTeam/NetBreak/issues](https://github.com/5evenTeam/NetBreak/issues)
and include:

- What you ran, and what you expected to happen.
- What actually happened, including the exact error text.
- Your operating system and Python version.
- The output of `netbreak --list-engines`, so we know which engines were
  available.
- If the problem is about a specific target, a short description of the target
  type (for example "a Linux host on the local network"). Do not paste sensitive
  addresses or scan results you are not allowed to share.

If you are reporting a security problem in NetBreak itself, do not open a public
issue; follow [SECURITY.md](SECURITY.md) instead.
