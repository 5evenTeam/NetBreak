from __future__ import annotations

import ipaddress
import re
import socket

MAX_ADDRESSES = 65536

_RE_RANGE = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){0,3})-(\d{1,3}(?:\.\d{1,3}){0,3})$")


def _octets(value: str) -> list[int]:
    parts = value.split(".")
    if len(parts) > 4:
        raise ValueError(f"bad address {value!r}")
    out = []
    for part in parts:
        if part == "":
            out.append(-1)
        else:
            number = int(part)
            if not 0 <= number <= 255:
                raise ValueError(f"bad octet {part!r} in {value!r}")
            out.append(number)
    return out


def _dash_range(token: str) -> list[str]:
    match = _RE_RANGE.match(token)
    if not match:
        raise ValueError(f"bad range {token!r}")
    start_raw, end_raw = match.groups()
    start = _octets(start_raw)
    end = _octets(end_raw)
    if len(start) != 4:
        raise ValueError(f"range {token!r} needs a full four octet start address")
    base = start[:3]
    first = start[3]
    if len(end) == 4:
        if end[:3] != base:
            raise ValueError(f"range {token!r} must stay inside one /24")
        last = end[3]
    elif len(end) == 1:
        last = end[0]
    else:
        raise ValueError(f"range {token!r} has an incomplete end address")
    if last < first:
        raise ValueError(f"range {token!r} ends before it starts")
    if last - first + 1 > MAX_ADDRESSES:
        raise ValueError(f"range {token!r} too large")
    prefix = ".".join(str(octet) for octet in base)
    return [f"{prefix}.{n}" for n in range(first, last + 1)]


def _expand_one(token: str, ipv6: bool) -> list[str]:
    token = token.strip()
    if not token:
        return []
    try:
        network = ipaddress.ip_network(token, strict=False)
    except ValueError:
        network = None
    if network is not None:
        if network.version == 6 and not ipv6:
            raise ValueError(f"{token} is IPv6, pass -6 to enable IPv6 targets")
        if network.version == 4 and network.prefixlen < 32:
            if network.num_addresses > MAX_ADDRESSES:
                raise ValueError(
                    f"{token} covers {network.num_addresses} addresses, limit is {MAX_ADDRESSES}"
                )
            hosts = list(network.hosts())
            if not hosts:
                hosts = [network.network_address]
            return [str(h) for h in hosts]
        return [str(network.network_address)]
    if _RE_RANGE.match(token):
        if ipv6:
            raise ValueError(f"IPv4 range {token!r} with -6 is not supported")
        return _dash_range(token)
    return [token]


def expand(specs: list[str], *, ipv6: bool = False, exclude: list[str] | None = None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for spec in specs:
        for token in spec.split(","):
            for target in _expand_one(token, ipv6):
                if target not in seen:
                    seen.add(target)
                    out.append(target)
    if exclude:
        drop: set[str] = set()
        for spec in exclude:
            drop.update(expand([spec], ipv6=ipv6))
        out = [t for t in out if t not in drop]
    if not out:
        raise ValueError("no targets left to scan")
    return out


def resolve(target: str, *, ipv6: bool = False, timeout: float = 4.0) -> str:
    try:
        ipaddress.ip_address(target)
        return target
    except ValueError:
        pass
    family = socket.AF_UNSPEC if ipv6 else socket.AF_INET
    infos = socket.getaddrinfo(target, None, family, socket.SOCK_STREAM)
    if not infos:
        raise OSError(f"cannot resolve {target!r}")
    if ipv6:
        for fam, _t, _p, _c, sockaddr in infos:
            if fam == socket.AF_INET6:
                return sockaddr[0]
    for fam, _t, _p, _c, sockaddr in infos:
        if fam == socket.AF_INET:
            return sockaddr[0]
    return infos[0][4][0]


def reverse_name(address: str, timeout: float = 2.0) -> str | None:
    socket.setdefaulttimeout(timeout)
    try:
        name, _aliases, _addrs = socket.gethostbyaddr(address)
        return name
    except OSError:
        return None
    finally:
        socket.setdefaulttimeout(None)
