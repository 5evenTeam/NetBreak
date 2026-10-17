# Usage cookbook

This is a practical guide to common NetBreak tasks. For the full flag list see
the CLI reference in [README.md](../README.md); for the engine layer see
[engines.md](engines.md).

Everything here assumes you have permission to scan the targets. See the
reminder at the end.

## Scan a single host

```bash
netbreak 192.168.1.10
```

With no `-p`, NetBreak scans the `top100` TCP ports. Add `-sV` to look at what is
running on any open ports:

```bash
netbreak 192.168.1.10 -p 22,80,443 -sV
```

Hostnames work in place of addresses:

```bash
netbreak host.example.com -p 22,80,443 -sV
```

## Scan a subnet

CIDR blocks are expanded to their usable host addresses:

```bash
netbreak 192.168.1.0/24
```

Dash ranges cover a run of addresses inside one `/24`:

```bash
netbreak 10.0.0.1-20
netbreak 10.0.0.1-10.0.0.3
```

You can mix forms with commas, and IPv6 is available behind `-6`:

```bash
netbreak 10.0.0.1,10.0.0.5-9,host.local
netbreak -6 2001:db8::1
```

Large blocks are expanded up to a limit of 65536 addresses; anything bigger is
rejected rather than silently truncated. Discovery-only sweeps keep the scan
light:

```bash
netbreak 192.168.1.0/24 -sn
```

## Top ports versus all ports

`-p topN` scans the `N` most common TCP ports, using the built-in list. The
default is `top100`.

```bash
netbreak 192.168.1.10 -p top20
```

`-p-` scans all 65535 ports, which takes much longer and is noisier on the
target:

```bash
netbreak 192.168.1.10 -p-
```

Ranges and lists are supported, and you can leave ports out:

```bash
netbreak 192.168.1.10 -p 1-1024
netbreak 192.168.1.10 -p 22,80,443,8000-8100
netbreak 192.168.1.10 -p- --exclude-ports 1-1023
```

## Service detection

`-sV` connects to each open port and tries to identify the service, product and
version. It understands HTTP, TLS, SSH, FTP, SMTP, POP3, IMAP, Redis, memcached,
MySQL, VNC and RDP, and grabs banners for the rest.

```bash
netbreak 192.168.1.10 -p 22,80,443 -sV
```

Detection is a best-effort match against banners and headers, not a full
fingerprint database. Treat the product and version as a strong hint, and
confirm anything that matters by hand. HTTPS and other TLS ports are probed with
certificate verification disabled so the scan does not fail on self-signed
certificates.

## OS hints

`-O` adds a coarse operating system guess, built from the observed TTL and the
services that were found:

```bash
netbreak 192.168.1.10 -p 22,80,443 -sV -O
```

A TTL near 64 suggests a Linux or Unix host, near 128 suggests Windows, near 32
suggests an embedded device, and near 255 suggests a network device. Service
names sharpen the guess. This is a heuristic, not Nmap's fingerprint database, so
use it as a starting point.

## UDP

UDP scanning is best-effort, because there is no raw ICMP error capture. NetBreak
sends a protocol-appropriate payload to well-known ports (DNS, NTP, SNMP) and
otherwise sends an empty datagram, then waits for a reply.

With `-sU` and no port selection, NetBreak scans UDP only, using a default set of
common UDP service ports (53, 67, 68, 69, 111, 123, 137, 161, 1900, 3389, 5353 and
others; the full list is `DEFAULT_UDP_PORTS` in `netbreak/cli.py`):

```bash
netbreak 10.0.0.5 -sU
```

Give it a port list and the list is treated as UDP, because only UDP is selected:

```bash
netbreak 10.0.0.5 -sU -p 53,161
netbreak 10.0.0.5 -sU --udp-ports 53,161
```

Add `-sT` to scan both protocols. Without an explicit `--udp-ports`, the same port
list covers both protocols, which matches Nmap's `-sS -sU` behaviour:

```bash
netbreak 10.0.0.5 -sT -sU -p 22,80,443
```

The port states for UDP follow the usual convention: `open` when a response
arrives, `closed` when an ICMP port-unreachable is seen, and `open|filtered` when
nothing comes back. Because a missing reply can mean either an open port that
stayed quiet or a filtered one, do not read too much into a silent result.

## Timing templates

The `-T` templates trade speed for stealth and for tolerance of slow links. The
default is `T4`.

| Template | When to use it |
|----------|----------------|
| `-T0` paranoid | Very slow, single-ish probes. Use when you must avoid tripping rate limits. |
| `-T1` sneaky | Still slow, for cautious scans of a sensitive target. |
| `-T2` polite | Slower than default, reduces load on the target. |
| `-T3` normal | A middle ground when the default feels too aggressive. |
| `-T4` aggressive | Default. Good for LANs and responsive hosts. |
| `-T5` insane | Maximum parallelism. Fast on a LAN, likely to miss ports on a lossy or rate-limited link. |

Individual values can be overridden:

```bash
netbreak 10.0.0.1-20 -p top100 -T4 --concurrency 400 --timeout 2.0
```

`--retries` retries ports that came back filtered, and `--delay` inserts a
millisecond pause between probes. On a high-latency link, raise `--timeout`
rather than `--concurrency`, or a slow host will be reported as filtered.

## Writing reports

Each format has its own flag, and `-oA` writes all four at once:

```bash
netbreak 10.0.0.7 -p top100 -sV -O -Pn -oA report
```

That produces `report.txt`, `report.xml`, `report.json` and `report.gnmap`. The
XML is shaped like Nmap's `nmaprun` output for tools that expect it, and the
grepable file uses `Ports: 80/open/tcp//http//nginx 1.25.3/` style records. The
JSON report holds the scan options, the host list, and a summary of open and
probed ports.

## Piping JSON into other tools

`-oJ -` is not special-cased, so write to a file and read it, or capture stdout.
The quickest route to a machine-readable result is a JSON report file:

```bash
netbreak 10.0.0.7 -p top100 -q -oJ result.json
jq '.hosts[] | {address, open: [.ports[] | select(.state=="open") | .port]}' result.json
```

The same payload is easy to consume from Python:

```python
import json

data = json.load(open("result.json"))
for host in data["hosts"]:
    for port in host["ports"]:
        if port["state"] == "open":
            print(host["address"], port["port"], port.get("service") or "")
```

## Terminal UI and desktop app

With no targets, `netbreak` opens the terminal UI. `netbreak tui` opens it
explicitly, and `netbreak gui` opens the desktop app.

In the TUI, `s` starts a scan, `x` stops it, `c` clears the table, `e` exports
JSON, `v`, `o` and `u` toggle version detection, OS detection and UDP, and `q`
quits. The desktop app exposes the same options as checkboxes, a timing dropdown,
and one `Export` button per report format. Both front ends use whichever engine
`auto` selects.

## Choosing an engine

Leave `--engine` at its default (`auto`) unless you have a reason not to. On a
source checkout with the native engines built, `auto` prefers Go, then the C++
helper, then Python. To find out what is available:

```bash
netbreak --list-engines
```

To force one:

```bash
netbreak 10.0.0.1-20 -p- --engine go
netbreak 10.0.0.1-20 -p- --engine python
```

The Python engine is the only one that performs UDP scans, version detection and
OS heuristics, and those still run in Python even when a native engine handles
the TCP scan.

## Troubleshooting

**No open ports found.** Confirm the target is up, then check the port spec. A
default scan only covers the `top100` list, so a service on an unusual port will
be missed. Try `-p-`, or pass the exact ports. Also check `-Pn`: without it,
NetBreak does host discovery first, and a host that does not answer the TCP ping
or ICMP may be marked down before any port is probed.

**Everything is filtered.** A wall of `filtered` results usually means a firewall
is dropping the probes, or the timeout is too short for the path. Raise
`--timeout` first (for example `--timeout 3`), and try a lower template such as
`-T3` so probes are less bunched. If the target is remote and lossy, `--retries 2`
helps distinguish a genuinely filtered port from a dropped packet.

**The engines are not detected.** Run `netbreak --list-engines`. If a native
engine shows as `not found` on a source checkout, build it and make sure the
binary is in `engines/go/bin` or `engines/cpp/bin`. If you have moved the
binaries elsewhere, point `NETBREAK_ENGINE_DIR` at the folder that holds them.
The Python engine always works, so a missing native engine is not fatal.

**A firewall or VPN changes the results.** A host firewall can make a remote
scanner see `filtered` where a local scan sees `closed`. A VPN can route traffic
through a different path, add latency, or block ICMP, which affects both host
discovery and the OS guess. If results look wrong, scan from the same network
segment as the target and compare.

**High latency.** Slow links cause ports to time out and show as `filtered`, and
they make host discovery unreliable. Prefer a higher `--timeout` and a lower
`--concurrency`, or a lower timing template. On loopback you may also see the
engine-dependent difference between `closed` and `filtered` described in
[engines.md](engines.md).

## A note on permission

NetBreak is for authorized testing only. Only scan hosts and networks you own or
have explicit written permission to test. Unauthorized port scanning is illegal
in most jurisdictions. The authors accept no liability for misuse.
