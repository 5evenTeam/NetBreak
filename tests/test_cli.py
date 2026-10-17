from __future__ import annotations

import json

from netbreak.cli import _build_options, build_parser, main
from netbreak.ports import TOP_PORTS


def _options_for(argv: list[str]):
    return _build_options(build_parser().parse_args(argv))


def test_cli_parses_ports_and_flags():
    options = _options_for(["10.0.0.1", "-p", "22,80", "-sV", "-T5", "--open", "-Pn"])
    assert options.targets == ["10.0.0.1"]
    assert options.ports.tcp == [22, 80]
    assert options.version_detect is True
    assert options.timing == "T5"
    assert options.timeout == 0.5
    assert options.ping is False


def test_cli_udp_only_scans_udp_by_default():
    from netbreak.cli import DEFAULT_UDP_PORTS

    options = _options_for(["10.0.0.9", "-sU"])
    assert options.udp is True
    assert options.tcp is False
    assert options.ports.tcp == []
    assert options.ports.udp == sorted(DEFAULT_UDP_PORTS)


def test_cli_udp_only_uses_the_port_spec_for_udp():
    options = _options_for(["10.0.0.9", "-sU", "-p", "53,161"])
    assert options.tcp is False
    assert options.ports.udp == [53, 161]


def test_cli_udp_only_uses_udp_ports_when_given():
    options = _options_for(["10.0.0.9", "-sU", "--udp-ports", "53,123"])
    assert options.tcp is False
    assert options.ports.udp == [53, 123]


def test_cli_tcp_and_udp_scan_the_same_ports_on_both_protocols():
    options = _options_for(["10.0.0.9", "-sT", "-sU", "-p", "22,80"])
    assert options.ports.tcp == [22, 80]
    assert options.ports.udp == [22, 80]


def test_cli_default_is_tcp_top_ports():
    options = _options_for(["10.0.0.9"])
    assert options.tcp is True
    assert options.udp is False
    assert options.ports.tcp == sorted(TOP_PORTS[:100])


def test_cli_ping_only_has_no_ports():
    options = _options_for(["10.0.0.9", "-sn"])
    assert options.ports.total == 0
    assert options.tcp is False
    assert options.udp is False


def test_cli_overrides_timing_values():
    options = _options_for(["10.0.0.9", "-T1", "--timeout", "3.5", "--concurrency", "7", "--retries", "4"])
    assert options.timeout == 3.5
    assert options.concurrency == 7
    assert options.retries == 4


def test_cli_list_engines(capsys):
    code = main(["--list-engines"])
    output = capsys.readouterr().out
    assert code == 0
    assert "engine order" in output
    assert "python" in output


def test_cli_scan_writes_reports(tcp_listener, quiet_stdout, tmp_path):
    _server, port = tcp_listener
    json_path = tmp_path / "report.json"
    xml_path = tmp_path / "report.xml"
    code = main(
        [
            "127.0.0.1",
            "-p",
            str(port),
            "-Pn",
            "-q",
            "-oJ",
            str(json_path),
            "-oX",
            str(xml_path),
        ]
    )
    assert code == 0
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["summary"]["open_ports"] == 1
    assert xml_path.exists()


def test_cli_scan_with_open_filter(tcp_listener, quiet_stdout):
    _server, port = tcp_listener
    code = main(["127.0.0.1", "-p", str(port), "-Pn", "-q", "--open"])
    assert code == 0


def test_cli_requires_targets(capsys):
    code = main(["cli"])
    assert code == 2
