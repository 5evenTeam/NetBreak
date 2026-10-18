from __future__ import annotations

import asyncio

from netbreak.core import udp

PROBED_PORTS = (53, 67, 68, 69, 123, 137, 161, 1900, 5060, 5353, 5355)


def test_services_have_payload_and_validator():
    for port in PROBED_PORTS:
        name, payload, validator = udp.SERVICES[port]
        assert name
        assert payload
        assert validator is not None


def test_dns_validator():
    assert udp._is_dns_response(b"\xab\xcd\x81\x80" + b"\x00" * 8)
    assert not udp._is_dns_response(b"\xab\xcd\x01\x00" + b"\x00" * 8)
    assert not udp._is_dns_response(b"\xab\xcd")


def test_ntp_validator():
    assert udp._is_ntp_response(b"\x1c" + b"\x00" * 47)
    assert not udp._is_ntp_response(b"\x00" * 10)


def test_netbios_validator():
    assert udp._is_netbios_response(b"\x00\x00\x84" + b"\x00" * 9)
    assert not udp._is_netbios_response(b"\x00\x00\x04" + b"\x00" * 9)


def test_ssdp_and_sip_validators():
    assert udp._is_ssdp_response(b"HTTP/1.1 200 OK\r\n")
    assert udp._is_sip_response(b"SIP/2.0 200 OK")
    assert not udp._is_sip_response(b"junk")
    assert not udp._is_ssdp_response(b"junk")


def test_tftp_validator():
    assert udp._is_tftp_response(b"\x00\x05\x00\x04")
    assert not udp._is_tftp_response(b"\x00\x09")


def test_dhcp_validator():
    packet = bytearray(240)
    packet[236:240] = b"\x63\x82\x53\x63"
    assert udp._is_dhcp_response(bytes(packet))
    assert not udp._is_dhcp_response(b"\x00" * 239)


def test_probe_detects_open_udp_service():
    async def run():
        class Echo(asyncio.DatagramProtocol):
            def connection_made(self, transport):
                self.transport = transport

            def datagram_received(self, data, addr):
                self.transport.sendto(b"pong", addr)

        loop = asyncio.get_running_loop()
        transport, _protocol = await loop.create_datagram_endpoint(Echo, local_addr=("127.0.0.1", 0))
        port = transport.get_extra_info("sockname")[1]
        try:
            return await udp.probe("127.0.0.1", port, timeout=0.5, retries=1)
        finally:
            transport.close()

    result = asyncio.run(run())
    assert result.state == "open"
    assert result.reason == "udp-response"
    assert result.protocol == "udp"


def test_probe_reports_open_filtered_when_silent():
    async def run():
        loop = asyncio.get_running_loop()
        transport, _protocol = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol, local_addr=("127.0.0.1", 0)
        )
        port = transport.get_extra_info("sockname")[1]
        try:
            return await udp.probe("127.0.0.1", port, timeout=0.3, retries=0)
        finally:
            transport.close()

    result = asyncio.run(run())
    assert result.state == "open|filtered"
    assert result.reason == "no-response"


def test_probe_validates_wrong_protocol_response():
    async def run():
        class Wrong(asyncio.DatagramProtocol):
            def connection_made(self, transport):
                self.transport = transport

            def datagram_received(self, data, addr):
                self.transport.sendto(b"not-a-dns-response", addr)

        loop = asyncio.get_running_loop()
        transport, _protocol = await loop.create_datagram_endpoint(Wrong, local_addr=("127.0.0.1", 0))
        port = transport.get_extra_info("sockname")[1]
        try:
            return await udp._attempt("127.0.0.1", port, 0.3, udp.SERVICES[53][1], udp.SERVICES[53][2])
        finally:
            transport.close()

    assert asyncio.run(run()) is None
