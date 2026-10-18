from __future__ import annotations

import asyncio
import socket
import struct
import time
from typing import AsyncIterator

from .models import PortResult, PortState


def _dns_query(txid: int, name: bytes) -> bytes:
    header = struct.pack(">HHHHHH", txid, 0x0100, 1, 0, 0, 0)
    return header + name + b"\x00" + struct.pack(">HH", 1, 1)


def _is_dns_response(data: bytes) -> bool:
    return len(data) >= 12 and bool(data[2] & 0x80)


def _is_ntp_response(data: bytes) -> bool:
    return len(data) >= 48 and (data[0] & 0x07) == 4


def _is_netbios_response(data: bytes) -> bool:
    return len(data) >= 12 and bool(data[2] & 0x80)


def _is_snmp_response(data: bytes) -> bool:
    return len(data) >= 2 and data[0] == 0x30


def _is_ssdp_response(data: bytes) -> bool:
    return data.startswith(b"HTTP/1.")


def _is_sip_response(data: bytes) -> bool:
    return data.startswith(b"SIP/2.0")


def _is_tftp_response(data: bytes) -> bool:
    return len(data) >= 2 and data[0] == 0x00 and 0x01 <= data[1] <= 0x05


def _is_dhcp_response(data: bytes) -> bool:
    return len(data) >= 240 and data[236:240] == b"\x63\x82\x53\x63"


def _dhcp_payload() -> bytes:
    packet = bytearray(240)
    packet[0] = 1
    packet[1] = 1
    packet[2] = 6
    packet[4:8] = bytes.fromhex("abcd1234")
    packet[236:240] = b"\x63\x82\x53\x63"
    return bytes(packet)


def _nbstat_payload() -> bytes:
    return bytes.fromhex("822800000001000000000000") + b"\x20CK" + b"\x43\x41" * 15 + b"\x00\x00\x21\x00\x01"


SERVICES: dict[int, tuple[str, bytes, object]] = {
    53: ("domain", _dns_query(0xABCD, b"\x03www\x07example\x03com"), _is_dns_response),
    67: ("dhcp", _dhcp_payload(), _is_dhcp_response),
    68: ("dhcp", _dhcp_payload(), _is_dhcp_response),
    69: ("tftp", b"\x00\x01netbreak-probe\x00octet\x00", _is_tftp_response),
    123: ("ntp", b"\x1b" + b"\x00" * 47, _is_ntp_response),
    137: ("netbios-ns", _nbstat_payload(), _is_netbios_response),
    161: (
        "snmp",
        bytes.fromhex(
            "302702010004067075626c6963a01a020400000001020100020100300c300a06082b060102010101000500"
        ),
        _is_snmp_response,
    ),
    1900: (
        "ssdp",
        b"M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
        b'MAN: "ssdp:discover"\r\nMX: 1\r\nST: ssdp:all\r\n\r\n',
        _is_ssdp_response,
    ),
    5060: (
        "sip",
        b"OPTIONS sip:netbreak@localhost SIP/2.0\r\n"
        b"Via: SIP/2.0/UDP 127.0.0.1:5060\r\nMax-Forwards: 70\r\n"
        b"To: <sip:netbreak@localhost>\r\nFrom: <sip:probe@localhost>;tag=netbreak\r\n"
        b"Call-ID: netbreak\r\nCSeq: 1 OPTIONS\r\nContent-Length: 0\r\n\r\n",
        _is_sip_response,
    ),
    5353: ("mdns", _dns_query(0, b"\x09_services\x07_dns-sd\x04_udp\x05local"), _is_dns_response),
    5355: ("llmnr", _dns_query(0x1234, b"\x08netbreak"), _is_dns_response),
}

PAYLOADS: dict[int, bytes] = {port: entry[1] for port, entry in SERVICES.items()}


def _payload(port: int) -> bytes:
    return PAYLOADS.get(port, b"")


def service_name(port: int) -> str:
    entry = SERVICES.get(port)
    return entry[0] if entry else ""


async def _attempt(
    ip: str,
    port: int,
    timeout: float,
    payload: bytes,
    validator,
) -> PortResult | None:
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setblocking(False)
    start = time.perf_counter()
    try:
        await loop.sock_connect(sock, (ip, port))
        await loop.sock_sendall(sock, payload or b"\x00")
        deadline = time.perf_counter() + timeout
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return None
            try:
                data = await asyncio.wait_for(loop.sock_recv(sock, 65535), remaining)
            except asyncio.TimeoutError:
                return None
            except ConnectionResetError:
                return PortResult(port, "udp", PortState.CLOSED.value, "icmp-port-unreachable")
            except OSError as exc:
                name = (getattr(exc, "strerror", None) or str(exc)).lower()
                if "refused" in name or "reset" in name or "forcibly closed" in name:
                    return PortResult(port, "udp", PortState.CLOSED.value, "icmp-port-unreachable")
                if "unreachable" in name:
                    return PortResult(port, "udp", PortState.FILTERED.value, name)
                return None
            if validator is None or validator(data):
                rtt = round((time.perf_counter() - start) * 1000.0, 2)
                result = PortResult(port, "udp", PortState.OPEN.value, "udp-response", rtt)
                result.info["bytes"] = str(len(data))
                result.banner = data[:64].hex()
                return result
    except ConnectionResetError:
        return PortResult(port, "udp", PortState.CLOSED.value, "icmp-port-unreachable")
    except OSError:
        return None
    finally:
        sock.close()


async def probe(ip: str, port: int, timeout: float, retries: int = 2) -> PortResult:
    entry = SERVICES.get(port)
    payload = entry[1] if entry else b""
    validator = entry[2] if entry else None
    for attempt in range(retries + 1):
        result = await _attempt(ip, port, timeout, payload, validator)
        if result is not None:
            return result
        if attempt < retries:
            await asyncio.sleep(0.05)
    return PortResult(port, "udp", PortState.OPEN_FILTERED.value, "no-response")


async def scan(
    ip: str,
    ports: list[int],
    timeout: float,
    cancel: asyncio.Event | None = None,
    concurrency: int = 128,
    retries: int = 2,
) -> AsyncIterator[PortResult]:
    sem = asyncio.Semaphore(concurrency)

    async def worker(port: int) -> PortResult:
        async with sem:
            return await probe(ip, port, timeout, retries)

    tasks = [asyncio.create_task(worker(port)) for port in ports]
    try:
        for task in asyncio.as_completed(tasks):
            if cancel is not None and cancel.is_set():
                break
            yield await task
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
