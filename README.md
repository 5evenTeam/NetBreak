# NetBreak

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

**A fast, friendly terminal-UI port scanner for authorized network reconnaissance.**

NetBreak probes TCP ports with plain OS-level connect scans (no raw sockets, no
admin rights needed), streams results live into a Textual TUI, and can drop
everything to JSON when you're done.

```
 ▗ NetBreak v0.1.0 - TCP connect scanner
 ┌──────────────────────────────────────────────────────────────────────┐
 │ target host or IP - e.g. 192.168.1.10   ports - top100 | 1-1000 ...  │
 │ [ Scan ]  [ Stop ]  [ Export ]  [x] Hide closed                      │
 ├──────────────────────────────────────────────────────────────────────┤
 │ probed 100/100 - 6 open - 0 filtered - 412 ports/s - 0.2s            │
 │   Port  State   Service      Latency  Detail                         │
 │     22  open    ssh            1.2                                 │
 │     80  open    http           0.9                                 │
 │    443  open    ssl/http       1.4                                 │
 └──────────────────────────────────────────────────────────────────────┘
```

## Features

- **Live TUI** — results stream in as they're found, with progress, scan rate,
  and per-port latency.
- **Fast async engine** — hundreds of concurrent probes, bounded memory even on
  a full `1-65535` sweep.
- **Flexible port specs** — presets (`top100`, `full`), ranges (`1-1000`),
  lists (`22,80,443`), or any mix.
- **Hide-closed toggle** — keep the table focused on what's actually open.
- **JSON export** — one keystroke (`e`) writes a timestamped report.
- **CLI fallback** — `--cli` for scripting and CI, with `--json` output.

## Install

```bash
git clone https://github.com/5evenTeam/NetBreak.git
cd NetBreak
pip install -e .
```

## Usage

```bash
netbreak                          # open the TUI
netbreak 192.168.1.10             # TUI with the target prefilled
netbreak example.com -p full      # TUI, full 1-65535 sweep

netbreak --cli example.com -p 22,80,443          # one-shot terminal scan
netbreak --cli example.com -p top100 --json      # machine-readable output
netbreak --cli example.com -t 2.0 -c 800         # slower hosts, more parallelism
```

### TUI keys

| Key | Action                    |
|-----|---------------------------|
| `s` | Start scan                |
| `x` | Stop scan (graceful)      |
| `e` | Export results to JSON    |
| `c` | Toggle closed-port rows   |
| `q` | Quit                      |

### Port states

| State     | Meaning                                                        |
|-----------|----------------------------------------------------------------|
| `open`    | The TCP handshake completed - a service accepted the connection. |
| `closed`  | The host replied, refusing the connection - nothing listening.  |
| `filtered`| No reply before the timeout - likely dropped by a firewall.     |

## How it works

NetBreak performs a **TCP connect scan**: it asks the operating system to
complete a normal TCP handshake with each port, exactly like a web browser
connecting to a website. This means:

- No raw packets or privilege escalation required (works as a regular user).
- Reliable "open" detection - a completed handshake is definitive.
- "Filtered" ports depend on timeout behavior, so tune `-t` for slow or
  high-latency links.

## Development

```bash
pip install -e . pytest
pytest
```

Tests cover the port-spec parser, the async scanner against a real local
listener, and a headless TUI session that runs a full scan via Textual's
test pilot.

## Responsible use

NetBreak is provided for **education and authorized security testing only**.
Only scan hosts and networks you own or have **explicit written permission**
to test. Unauthorized scanning can be illegal in your jurisdiction. Use this
software at your own risk; the authors accept no liability for misuse.

## License

[MIT](LICENSE) - (c) 2026 5evenTeam
