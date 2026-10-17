# Engines

NetBreak has three scan engines behind one interface. The Python front end
resolves targets, drives an engine, and turns the results into
`PortResult`/`HostResult` objects that every front end can display. Version
detection, UDP scanning and OS heuristics are always done in Python, so the
choice of engine changes how TCP port state and host discovery are produced, not
the shape of the final report.

| Engine | Binary | Role |
|--------|--------|------|
| Python | none | Default. asyncio TCP connect scan, UDP probe, banner grabbing, version detection, TTL-based OS hints. Always available. |
| Go | `netbreak-engine.exe` (`netbreak-engine` elsewhere) | TCP connect scan and TCP ping with a worker pool. Emits JSON lines on stdout. |
| C++ | `netbreak-native.exe` (`netbreak-native` elsewhere) | Windows helper. `IcmpSendEcho` for TTL and alive probing, plus a connect-scan fallback. |

## Discovery order

`netbreak/core/backends.py` looks for the two native executables in this order.
The first match for each name wins.

1. The directory named by the `NETBREAK_ENGINE_DIR` environment variable.
2. When frozen by PyInstaller: the bundle directory (`sys._MEIPASS`) and
   `<bundle>/engines`.
3. The directory that contains the `netbreak` package (`<package_parent>`) plus:
   - `engines/go/bin`
   - `engines/cpp/bin`
   - `engines/cpp/build`
   - `bin`
   - `dist`
4. Anywhere on `PATH`.

The Go engine is looked up as `netbreak-engine`, and the native engine as
`netbreak-native` (with a `.exe` suffix on Windows). If neither is found, the
Python engine is used.

`netbreak --list-engines` prints the discovery order and the resolved paths:

```
engine order: go, native, python
  go engine:     C:\...\engines\go\bin\netbreak-engine.exe
  native engine: C:\...\engines\cpp\bin\netbreak-native.exe
```

Missing engines show as `not found`, and the order line reads
`go(absent), native(absent), python`.

## Engine selection

`--engine` accepts `auto`, `go`, `cpp` or `python`.

- `auto` (default) prefers Go, then the native engine, then Python.
- `go` uses the Go engine if it was found; otherwise it falls back to Python.
- `cpp` (also `c++` or `native` internally) uses the native engine if found;
  otherwise it falls back to Python.
- `python` always uses the Python engine.

If a native engine is selected but produces no port results for a host, the
engine warns and falls back to the Python engine for that scan. This keeps a
misconfigured or incompatible binary from silently returning nothing.

For host discovery, the front end runs a TCP ping first and, if that fails, uses
the native engine's `icmp` subcommand when available, then the system `ping`
command. The Go engine's `ping` subcommand exists but the front end does not
call it; discovery goes through the native and system paths.

## JSONL protocol

The Python front end launches a native engine as a subprocess and reads one JSON
object per line from its stdout. Anything the engine prints on stderr is ignored.
The commands are:

```
netbreak-engine scan -host <ip> -p <spec> -timeout <seconds> -concurrency <n> -retries <n>
netbreak-native connect <ip> <spec> -timeout <seconds> -concurrency <n> -retries <n>
netbreak-native icmp <ip> <timeout_ms>
```

`<spec>` is a compact TCP port list with consecutive runs collapsed into ranges,
for example `22,80,1000-2000`. The front end builds it from the parsed port spec.

There are four event shapes.

### Port

```json
{"event":"port","port":80,"proto":"tcp","state":"open","reason":"syn-ack","rtt_ms":1.24}
```

- `port` is the port number.
- `proto` is `tcp`.
- `state` is `open`, `closed` or `filtered`.
- `reason` is the observation that produced the state, such as `syn-ack`,
  `conn-refused`, `conn-reset`, `no-response` or `net-unreachable`.
- `rtt_ms` is the round-trip time in milliseconds, measured only for open ports.

The Go engine uses `omitempty`, so `rtt_ms` is absent on non-open ports, and the
C++ engine emits it only for open ports. A typical closed-port line is therefore
`{"event":"port","port":81,"proto":"tcp","state":"closed","reason":"conn-refused"}`.

### Host

The native engine's ICMP probe emits:

```json
{"event":"host","host":"127.0.0.1","alive":true,"ttl":128,"rtt_ms":0.0}
```

The Go engine's ping emits the same shape but without `ttl`, and adds a `reason`:

```json
{"event":"host","host":"127.0.0.1","alive":true,"reason":"tcp-connect","rtt_ms":0.9}
{"event":"host","host":"127.0.0.1","alive":false,"reason":"no-response"}
```

`ttl` is present only when a real ICMP reply supplied it.

### Done

```json
{"event":"done","message":"probed 100"}
```

The engine emits this once at the end of a scan.

### Error

```json
{"event":"error","message":"scan requires -host and -p"}
```

Errors become warnings in the front end. A malformed line that does not parse as
JSON is ignored. The front end also recognises an `event` of `progress` and
skips it; the two shipped engines do not emit progress events today.

## Per-engine requirements and builds

### Python

No build step and no dependencies beyond Python 3.10. This is the fallback when
no native engine is present, and the only engine that performs UDP scans,
version detection and OS heuristics.

### Go

Requires Go 1.21 or newer (`engines/go/go.mod`). It is cross-platform and uses
`net.DialTimeout`, so it needs no special privileges. Build it from `engines/go`:

```bash
go build -trimpath -ldflags "-s -w" -o bin/netbreak-engine.exe .
```

The binary lands in `engines/go/bin`, which is on the discovery path for a source
checkout.

Run it directly to see its interface:

```
netbreak-engine scan -host 192.168.1.10 -p 22,80,443 -timeout 1 -concurrency 900 -retries 2
netbreak-engine ping -host 192.168.1.10
netbreak-engine version
```

### C++

Requires a C++17 compiler. On Windows, MinGW g++ works; the CMake project links
`ws2_32` and `iphlpapi`. Build with CMake:

```bash
cmake -S native/cpp -B native/cpp/build -G "MinGW Makefiles"
cmake --build native/cpp/build --config Release
```

or compile directly:

```bash
g++ -std=c++17 -O3 -Wall -Wextra -static -static-libgcc -static-libstdc++ \
  -o engines/cpp/bin/netbreak-native.exe \
  native/cpp/src/main.cpp native/cpp/src/icmp.cpp -lws2_32 -liphlpapi
```

The static flags matter on MinGW: without them the executable depends on the
MinGW runtime DLLs and will not start on a machine that lacks them. The source
keeps POSIX fallbacks (it shells out to `ping` for ICMP off Windows), but the
engine is packaged and shipped as a Windows helper.

Run it directly:

```
netbreak-native connect 192.168.1.10 22,80,443 -timeout 1 -concurrency 900 -retries 2
netbreak-native icmp 192.168.1.10 2000
netbreak-native version
```

## Comparison

| | Python | Go | C++ |
|--|--------|----|-----|
| Speed | Moderate | Fast | Fast |
| Platform support | Windows, macOS, Linux | Windows, macOS, Linux | Windows-focused |
| TCP connect scan | Yes | Yes | Yes |
| TCP ping | Yes (via connect) | Yes | No |
| ICMP TTL / alive probe | No (system ping only) | No | Yes (`IcmpSendEcho`) |
| UDP | Yes | No | No |
| Version detection | Yes | No | No |
| OS heuristics | Yes | No | No |
| Build step | None | Go 1.21+ | C++17 compiler |

Only the TCP port state and host discovery are produced by the native engines.
After a native scan, the Python front end still enriches open ports with service
and version data when `-sV` is given, and still performs UDP scanning when `-sU`
is given.

## Windows loopback behaviour

On some Windows machines, loopback ports behave differently depending on which
engine probes them. The Go engine uses the newer `ConnectEx` path, which can
return an immediate RST for a closed loopback port, while the Python and C++
engines see the same connection attempt dropped and time out. The practical
result is that the same closed port can be reported as `closed` by one engine and
`filtered` by another.

This is an environment quirk, not a difference in the scan logic. The `reason`
column records what was actually observed for each port: `conn-refused` or
`conn-reset` means a reply came back, while `no-response` means the probe timed
out. If you are comparing engines on loopback and the results disagree, read the
reason rather than the state alone, and prefer a real remote target for
engine-to-engine comparisons.
