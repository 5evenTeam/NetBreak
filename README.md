# NetBreak

[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![Release 2.0.0](https://img.shields.io/badge/release-2.0.0-blue)

NetBreak is a TCP/UDP port scanner for Windows, macOS and Linux, built for
authorized network reconnaissance. It ships three front ends over one shared
scan core: a Textual terminal UI, a Tkinter desktop app, and an Nmap-style
command line. Scans use ordinary TCP connect probes, so the tool runs as a
regular user without raw sockets or administrator privileges.

The project started as a small Textual TUI scanner. Version 2.0 is a rewrite:
the scan core is shared by all front ends, the command line gained Nmap-style
flags and report formats, and two native engines (Go and C++) were added to
speed up large scans.

## Features

- Three front ends: Textual TUI, Tkinter desktop app, and an Nmap-style CLI.
- Three scan engines behind one interface: Python (always available), Go, and a
  Windows C++ helper. See [docs/engines.md](docs/engines.md).
- TCP connect scanning plus a best-effort UDP scan.
- Service and version detection: HTTP, TLS, SSH, FTP, SMTP, POP3, IMAP, Redis,
  memcached, MySQL, VNC and RDP, with banner grabbing.
- TTL and service heuristics for a coarse OS guess.
- Target syntax for single hosts, CIDR blocks, dash ranges and comma lists.
- Flexible port specs: `top100`, `1-1000`, `22,80,443`, `-` for all 65535, and
  `T:`/`U:` protocol prefixes.
- Nmap-style timing templates `-T0` through `-T5`.
- Four report formats: normal text, XML (`nmaprun`-shaped), JSON, and grepable
  output, plus a combined `-oA` writer.
- A Windows installer that bundles the Python runtime and native engines, so end
  users need nothing installed.

New to the tool? [docs/usage.md](docs/usage.md) is a practical cookbook, and
[docs/engines.md](docs/engines.md) explains the engine layer.

## Install

### Windows installer

The prebuilt `NetBreak-Setup-2.0.0.exe` installs per machine (administrator
required), registers the native engines, and adds Start Menu shortcuts (with
optional desktop shortcuts) for the terminal UI and the desktop app. The bundles
include the Python runtime and the native engines, so no separate toolchain is
needed. Uninstall from the usual Windows "Apps & features" list.

### pipx or pip, from a checkout

```bash
git clone https://github.com/5evenTeam/NetBreak.git
cd NetBreak
pipx install .
```

`pip install .` works the same way if you would rather use it inside a virtual
environment. This installs the `netbreak` console script (TUI and CLI) and
`netbreak-gui` (desktop app). It does not install the native engines; the Python
engine is used until you build them (see below).

### From source, for development

```bash
git clone https://github.com/5evenTeam/NetBreak.git
cd NetBreak
pip install -e ".[dev]"
```

## Quick start

### Terminal UI

```bash
netbreak            # no targets launches the TUI
netbreak tui        # launch the TUI explicitly
```

The TUI starts on `127.0.0.1` and `top100`. Press `s` to scan, `x` to stop, `c`
to clear, `e` to export JSON, `v`/`o`/`u` to toggle version detection, OS
detection and UDP, and `q` to quit.

### Desktop app

```bash
netbreak gui
```

The desktop app has the same options with an `Export` button for each report
format.

### Command line

```bash
netbreak 192.168.1.0/24
netbreak host.example.com -p 22,80,443 -sV
netbreak 10.0.0.1-20 -p- -T4 --open
netbreak 10.0.0.5 -sU --udp-ports 53,161
netbreak 10.0.0.7 -p top100 -sV -O -Pn -oA report
```

The last command writes `report.txt`, `report.xml`, `report.json` and
`report.gnmap`.

## Engines

NetBreak picks an engine at runtime. When present, the native engines are used
for TCP scanning; otherwise the Python engine runs.

- **Python** (`netbreak/core/connect.py`): asyncio TCP connect scan, UDP probe,
  banner grabbing, version detection and TTL-based OS hints. No build step, and
  always available.
- **Go** (`engines/go/bin/netbreak-engine.exe`): fast TCP connect scan and TCP
  ping with a worker pool. Emits JSON lines on stdout. Build from `engines/go`:

  ```bash
  go build -trimpath -ldflags "-s -w" -o bin/netbreak-engine.exe .
  ```

- **C++** (`engines/cpp/bin/netbreak-native.exe`): Windows helper that uses
  `IcmpSendEcho` for TTL and alive probing, with a connect-scan fallback. Build
  with CMake from `native/cpp/CMakeLists.txt`, or directly with MinGW:

  ```bash
  g++ -std=c++17 -O3 -Wall -Wextra -static -static-libgcc -static-libstdc++ \
    -o engines/cpp/bin/netbreak-native.exe \
    native/cpp/src/main.cpp native/cpp/src/icmp.cpp -lws2_32 -liphlpapi
  ```

  With MinGW installed through scoop, `g++` lives in
  `%USERPROFILE%\scoop\apps\mingw\current\bin`. The static flags matter: without
  them the executable needs MinGW runtime DLLs at runtime.

The front end looks for the engines in this order: the `NETBREAK_ENGINE_DIR`
environment variable, the PyInstaller bundle directory, `engines/go/bin`,
`engines/cpp/bin`, `engines/cpp/build`, `bin/`, `dist/`, then `PATH`. Force an
engine with `--engine auto|go|cpp|python`, and see what was found with:

```bash
netbreak --list-engines
```

Full details, including the JSONL protocol between the front end and the native
engines, are in [docs/engines.md](docs/engines.md).

## CLI reference

```
netbreak [targets ...] [options]
```

`-p/--ports` accepts `topN`, `N`, ranges such as `1000-2000`, lists, `-` for all
65535, and `T:`/`U:` protocol prefixes. If no targets are given, the TUI starts
instead.

| Flag | Meaning |
|------|---------|
| `-p`, `--ports SPEC` | TCP ports (default `top100`). `-p-` scans all 65535. |
| `--udp-ports SPEC` | UDP ports to scan. |
| `--exclude-ports SPEC` | Ports or ranges to remove from the scan. |
| `--top-ports N` | Scan the `N` most common TCP ports. |
| `-T0`..`-T5`, `--timing Tn` | Timing template (see below). |
| `-sT` | TCP connect scan (default). |
| `-sU` | Scan UDP ports. Alone it uses a default UDP port set; with `-sT` both protocols are scanned. |
| `-sn` | Host discovery only, no port scan. |
| `-sV` | Service and version detection. |
| `-O` | Operating system guess. |
| `-Pn` | Skip host discovery and treat targets as up. |
| `-6` | Enable IPv6 targets. |
| `--engine auto\|go\|cpp\|python` | Choose a scan engine. |
| `--open` | Only report open ports. |
| `-oN FILE` | Write a normal text report. |
| `-oX FILE` | Write an XML report. |
| `-oJ FILE` | Write a JSON report. |
| `-oG FILE` | Write a grepable report. |
| `-oA BASE` | Write all four formats as `BASE.txt/.xml/.json/.gnmap`. |
| `-v` | Verbose output, repeatable. |
| `-q`, `--quiet` | Suppress live progress. |
| `--timeout SECONDS` | Per-probe timeout. |
| `--concurrency N` | Simultaneous probes. |
| `--retries N` | Extra attempts on filtered ports. |
| `--delay MS` | Delay in milliseconds between probes. |
| `--no-resolve` | Skip reverse DNS lookups. |
| `--list-engines` | Show the detected native engines. |
| `--version` | Print the version. |

Exit codes are `0` on success and `2` for usage errors or a missing target.

`netbreak tui` and `netbreak gui` launch the two graphical front ends.

## Output formats

| Format | Flag | Shape |
|--------|------|-------|
| Normal | `-oN` | A readable report with a header, per-host sections and a port table. |
| XML | `-oX` | An `nmaprun` element with `host`, `ports`, `service` and `runstats` elements. |
| JSON | `-oJ` | Scan options, a host list and a summary of open ports and probed ports. |
| Grepable | `-oG` | One `Host:` line per record with `Status:`, `Ports:` and `OS:` fields, e.g. `Ports: 80/open/tcp//http//nginx 1.25.3/`. |

Each host record carries its state, latency, TTL and OS guess; each port carries
state, protocol, service, product, version, banner, reason and RTT.

## Timing templates

| Template | Name | Concurrency | Timeout | Retries | Delay |
|----------|------|-------------|---------|---------|-------|
| `T0` | paranoid | 4 | 10.0s | 1 | 1000ms |
| `T1` | sneaky | 16 | 8.0s | 1 | 400ms |
| `T2` | polite | 64 | 5.0s | 1 | 100ms |
| `T3` | normal | 300 | 2.0s | 1 | 0ms |
| `T4` | aggressive (default) | 900 | 1.0s | 2 | 0ms |
| `T5` | insane | 2000 | 0.5s | 2 | 0ms |

Individual values can be overridden with `--timeout`, `--concurrency`,
`--retries` and `--delay`.

## Architecture

```
NetBreak/
├─ netbreak/
│  ├─ cli.py            command line entry point
│  ├─ ports.py          port spec parsing and service names
│  ├─ targets.py        target expansion and DNS resolution
│  ├─ timing.py         timing templates
│  ├─ core/
│  │  ├─ engine.py      ScanEngine: ties resolution, scanning and detection together
│  │  ├─ backends.py    native engine discovery
│  │  ├─ connect.py     asyncio TCP connect scan
│  │  ├─ discovery.py   host discovery (TCP ping, ICMP, system ping)
│  │  ├─ udp.py         UDP probe
│  │  ├─ versions.py    service and version detection
│  │  ├─ osdetect.py    TTL and service OS heuristics
│  │  ├─ events.py      streaming event types
│  │  └─ models.py      HostResult, PortResult, ScanOptions
│  ├─ output/           normal, XML, JSON and grepable renderers
│  ├─ tui/app.py        Textual terminal UI
│  └─ desktop/app.py    Tkinter desktop app
├─ engines/go/          Go engine (main.go, go.mod, bin/)
├─ native/cpp/          C++ engine sources and CMake project
├─ installer/           PowerShell build scripts, PyInstaller specs, Inno Setup script
├─ tests/               pytest suite
└─ docs/                engines.md, usage.md
```

The Python front end streams `Event` objects from `ScanEngine.run()`. All three
front ends consume the same events, so the TUI, the desktop app and the CLI show
the same results from the same code.

## Development

```bash
pip install -e ".[dev]"
python -m pytest
```

The suite covers port spec parsing, target expansion, timing templates, all four
output formats, engine scans against a local listener with all three engines,
version detection against a local HTTP stub, the CLI end to end, and the TUI
mounted headlessly through Textual's `run_test`. Native-engine tests skip when
the corresponding binary is not built.

Conventions and the pull request process are in
[CONTRIBUTING.md](CONTRIBUTING.md). Changes between releases are listed in
[CHANGELOG.md](CHANGELOG.md).

## Known limitations

- `-sS` (raw SYN scan) is not implemented. NetBreak is a connect scanner, not a
  stealth scanner, so it needs no privileges but is more visible to the target.
- UDP scanning is best-effort: there is no raw ICMP error capture, so UDP
  results are approximate.
- OS detection is a TTL and service heuristic, not a fingerprint database. It
  guesses broad families such as "Windows" or "Linux/Unix".
- Targets are IPv4 by default. IPv6 requires `-6`.

## Legal notice

NetBreak is for authorized security testing and education only. Scanning systems
you do not own or lack written permission to test is illegal in most
jurisdictions. You are responsible for how you use this tool; the authors accept
no liability for misuse. See [SECURITY.md](SECURITY.md) for how to report a
vulnerability.

## License

[MIT](LICENSE) - (c) 2026 5evenTeam

## Credits

NetBreak is maintained by [5evenTeam](https://github.com/5evenTeam). The TUI is
built on [Textual](https://textual.textualize.io/) and
[Rich](https://github.com/Textualize/rich); the command line uses `argparse`
from the standard library, and the desktop app uses Tkinter.
