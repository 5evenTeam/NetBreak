from __future__ import annotations

from xml.etree import ElementTree as ET

from .. import __version__
from ..core.models import HostResult, PortResult, ScanOptions
from ..ports import service_for


def _address_type(address: str) -> str:
    return "ipv6" if ":" in address else "ipv4"


def _address(host: HostResult) -> ET.Element:
    element = ET.Element("address", {"addr": host.address, "addrtype": _address_type(host.address)})
    return element


def _host_element(host: HostResult) -> ET.Element:
    root = ET.Element("host")
    status = {"state": host.state, "reason": host.reason or "unknown"}
    if host.ttl:
        status["reason_ttl"] = str(host.ttl)
    ET.SubElement(root, "status", status)
    root.append(_address(host))
    if host.hostname:
        names = ET.SubElement(root, "hostnames")
        ET.SubElement(names, "hostname", {"name": host.hostname, "type": "PTR"})
    if host.ports:
        ports = ET.SubElement(root, "ports")
        for port in host.ports:
            ports.append(_port_element(port, host))
    if host.os_guess:
        os_element = ET.SubElement(root, "os")
        ET.SubElement(os_element, "osmatch", {"name": host.os_guess, "accuracy": "70"})
    ET.SubElement(root, "hostscript", {"engine": host.engine})
    return root


def _port_element(port: PortResult, host: HostResult) -> ET.Element:
    element = ET.Element("port", {"protocol": port.protocol, "portid": str(port.port)})
    state = {"state": port.state, "reason": port.reason or "unknown"}
    if host.ttl:
        state["reason_ttl"] = str(host.ttl)
    ET.SubElement(element, "state", state)
    service_attributes = {"name": port.service or service_for(port.port, port.protocol) or "unknown"}
    if port.product:
        service_attributes["product"] = port.product
    if port.version:
        service_attributes["version"] = port.version
    service_element = ET.SubElement(element, "service", service_attributes)
    if port.product and port.version:
        cpe_vendor = port.product.lower().replace(" ", "_")
        ET.SubElement(service_element, "cpe").text = f"cpe:/a:{cpe_vendor}:{cpe_vendor}:{port.version}"
    for key, value in port.info.items():
        ET.SubElement(element, "script", {"id": key, "output": str(value)})
    if port.banner:
        ET.SubElement(element, "banner").text = port.banner[:2000]
    return element


def render(hosts: list[HostResult], options: ScanOptions, elapsed: float) -> str:
    root = ET.Element(
        "nmaprun",
        {
            "scanner": "netbreak",
            "version": __version__,
            "args": " ".join(options.targets),
            "start": "0",
            "elapsed": f"{elapsed:.2f}",
        },
    )
    ET.SubElement(root, "scaninfo", {"type": "connect", "protocol": "tcp", "numservices": str(options.ports.total)})
    for host in hosts:
        root.append(_host_element(host))
    stats = ET.SubElement(root, "runstats")
    ET.SubElement(
        stats,
        "finished",
        {"elapsed": f"{elapsed:.2f}", "summary": "NetBreak done"},
    )
    ET.SubElement(
        stats,
        "hosts",
        {
            "up": str(sum(1 for host in hosts if host.state == "up")),
            "down": str(sum(1 for host in hosts if host.state != "up")),
            "total": str(len(hosts)),
        },
    )
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"
