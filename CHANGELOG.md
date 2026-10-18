# Changelog

All notable changes to NetBreak are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [3.0.0] - 2026-10-18

UDP port scanning is now a first-class scan type instead of a best-guess
placeholder that only ever reported `open|filtered` on Windows.

### Added

- UDP scanning in the Go engine (`netbreak-engine udpscan`) and the Python core,
  wired through `-sU` and `--udp-ports`.
- Protocol-aware UDP probes with response validation for DNS (53), DHCP
  (67/68), TFTP (69), NTP (123), NetBIOS-NS (137), SNMP (161), SSDP (1900),
  SIP (5060), mDNS (5353) and LLMNR (5355). A validated reply is reported as
  `open` with the `udp-response:<service>` reason.
- Raw ICMP capture in the Go engine so ICMP port-unreachable maps a port to
  `closed`, host/protocol unreachable maps it to `filtered`, and silent ports
  are retried before being reported as `open|filtered`.
- Engine warnings when raw ICMP capture is unavailable or when the host OS
  suppresses ICMP errors, so callers know how much to trust `open|filtered`.

### Fixed

- The Go UDP scanner no longer sends an empty datagram and treats a timeout as
  `open|filtered` for everything; it now sends real probes and classifies the
  result, so open UDP services are detected and closed ports are reported on
  platforms that deliver ICMP errors.

## [2.0.0] - 2026-10-17

Version 2.0 is a ground-up rewrite. The scanner was previously a single Textual
application; it is now a shared scan core with three front ends.

### Added

- A Go scan engine (`engines/go`) with a TCP connect scan and TCP ping, a worker
  pool, and JSON-lines output. Built with
  `go build -trimpath -ldflags "-s -w" -o bin/netbreak-engine.exe .`.
- A C++ native engine (`native/cpp`) for Windows, using `IcmpSendEcho` for TTL
  and alive probing with a connect-scan fallback. Built with CMake or directly
  with MinGW g++.
- A Tkinter desktop app as a second graphical front end, alongside the terminal
  UI and the command line.
- An Nmap-style command line with `-p/--ports`, `--udp-ports`,
  `--exclude-ports`, `--top-ports`, `-T0`..`-T5`, `-sT`, `-sU`, `-sn`, `-sV`,
  `-O`, `-Pn`, `-6`, `--engine`, `--open`, `-v`, `-q`, `--timeout`,
  `--concurrency`, `--retries`, `--delay`, `--no-resolve` and `--list-engines`.
- Four report formats: normal text, XML (`nmaprun`-shaped), JSON and grepable,
  with `-oN`, `-oX`, `-oJ`, `-oG` and `-oA` writers.
- Service and version detection for HTTP, TLS, SSH, FTP, SMTP, POP3, IMAP,
  Redis, memcached, MySQL, VNC and RDP, with banner grabbing.
- TTL and service heuristics for a coarse OS guess.
- A Windows installer (`installer/`) that builds the native engines, produces
  two PyInstaller bundles and compiles an Inno Setup package
  (`dist/NetBreak-Setup-2.0.0.exe`) that registers `NETBREAK_ENGINE_DIR` and
  creates shortcuts for both front ends.
- A 46-test pytest suite covering port specs, target expansion, timing
  templates, the four output formats, engine scans against a local listener with
  all three engines, version detection against a local HTTP stub, the CLI end to
  end, and the TUI and desktop app mounted headlessly.

### Changed

- The engine core was rewritten: `netbreak/core` now holds a shared `ScanEngine`
  that streams events to every front end.
- The terminal UI was rebuilt on the shared engine (`netbreak/tui`) instead of
  its own scanner.
- The version was bumped from 1.0.0 to 2.0.0.
- `-sU` now selects a UDP-only scan, the way Nmap does, instead of adding UDP
  ports on top of the default TCP set. Add `-sT` to scan both protocols.

### Removed

- The original single-file scanner module.
- The old Textual application, replaced by `netbreak/tui` and `netbreak/core`.

### Fixed

- Event payload field ordering is now consistent across the event types.
- Dash-range target parsing (`10.0.0.5-7` and `10.0.0.1-10.0.0.3`).
- Protocol-prefixed UDP port lists such as `U:53,161`.

## [1.0.0]

The original release: a single-file TCP connect scanner with a Textual terminal
UI, a hide-closed toggle, and a JSON export.

[2.0.0]: https://github.com/5evenTeam/NetBreak/compare/v1.0.0...v2.0.0
[1.0.0]: https://github.com/5evenTeam/NetBreak/releases/tag/v1.0.0
