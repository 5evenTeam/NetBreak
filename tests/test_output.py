from __future__ import annotations

import json
from xml.etree import ElementTree as ET

from netbreak import __version__, output
from netbreak.core.models import HostResult, PortResult, ScanOptions
from netbreak.ports import PortSpec


def _sample() -> tuple[list[HostResult], ScanOptions]:
    port = PortResult(
        80,
        "tcp",
        "open",
        "syn-ack",
        1.5,
        "http",
        "nginx",
        "1.25.3",
        "HTTP/1.1 200 OK",
        {"title": "hello"},
    )
    filtered = PortResult(81, "tcp", "filtered", "no-response")
    host = HostResult(
        "example",
        "10.0.0.1",
        "example.local",
        "up",
        "tcp-connect",
        64,
        "Linux/Unix (ttl=64)",
        [port, filtered],
        1.2,
        "python",
    )
    options = ScanOptions(
        targets=["10.0.0.1"],
        ports=PortSpec(tcp=[80, 81]),
        engine="python",
        timing="T4",
    )
    return [host], options


def test_normal_report_has_ports_and_versions():
    hosts, options = _sample()
    text = output.render("normal", hosts, options, 1.5)
    assert "80/tcp" in text
    assert "nginx 1.25.3" in text
    assert "1 open" in text
    assert __version__ in text
    assert "example.local" in text


def test_json_report_is_structured():
    hosts, options = _sample()
    payload = json.loads(output.render("json", hosts, options, 1.5))
    assert payload["scanner"] == "netbreak"
    assert payload["summary"]["open_ports"] == 1
    assert payload["summary"]["hosts_up"] == 1
    assert payload["hosts"][0]["ports"][0]["product"] == "nginx"
    assert payload["hosts"][0]["ports"][0]["info"]["title"] == "hello"


def test_xml_report_parses():
    hosts, options = _sample()
    body = output.render("xml", hosts, options, 1.5).split("\n", 1)[1]
    root = ET.fromstring(body)
    assert root.tag == "nmaprun"
    port = root.find(".//port")
    assert port is not None
    assert port.get("portid") == "80"
    assert root.find(".//service").get("name") == "http"


def test_grep_report_shape():
    hosts, options = _sample()
    text = output.render("grep", hosts, options, 1.0)
    assert "Ports: 80/open/tcp//http//nginx 1.25.3/" in text
    assert "Status: Up" in text


def test_write_all_creates_every_format(tmp_path):
    hosts, options = _sample()
    written = output.write_all(str(tmp_path / "report"), hosts, options, 1.0)
    assert len(written) == 4
    for path in written:
        assert path.exists()
        assert path.stat().st_size > 0
