from __future__ import annotations

import pytest

from netbreak import ports, targets, timing


def test_parse_explicit_ports():
    spec = ports.parse("22,80,1000-1002")
    assert spec.tcp == [22, 80, 1000, 1001, 1002]
    assert spec.total == 5
    assert spec.udp == []


def test_parse_reversed_range_is_tolerated():
    spec = ports.parse("100-98")
    assert spec.tcp == [98, 99, 100]


def test_parse_all_ports():
    spec = ports.parse("-")
    assert len(spec.tcp) == 65535


def test_parse_top_ports():
    spec = ports.parse("top10")
    assert spec.tcp == sorted(ports.TOP_PORTS[:10])


def test_parse_protocol_prefixes():
    spec = ports.parse("T:22,80", udp="U:53,161")
    assert spec.tcp == [22, 80]
    assert spec.udp == [53, 161]


def test_parse_exclusions():
    spec = ports.parse("1-10", exclude="3,5-6")
    assert spec.tcp == [1, 2, 4, 7, 8, 9, 10]
    assert spec.excluded == [3, 5, 6]


def test_parse_rejects_bad_specs():
    with pytest.raises(ValueError):
        ports.parse("70000")
    with pytest.raises(ValueError):
        ports.parse("not-a-port")
    with pytest.raises(ValueError):
        ports.parse("80", exclude="80")
    with pytest.raises(ValueError):
        ports.parse("top999999")


def test_service_lookup():
    assert ports.service_for(22) == "ssh"
    assert ports.service_for(445) == "microsoft-ds"
    assert ports.service_for(80) == "http"


def test_cidr_expansion():
    assert targets.expand(["192.168.1.0/30"]) == ["192.168.1.1", "192.168.1.2"]


def test_dash_range_expansion():
    assert targets.expand(["10.0.0.5-7"]) == ["10.0.0.5", "10.0.0.6", "10.0.0.7"]
    assert targets.expand(["10.0.0.1-10.0.0.3"]) == ["10.0.0.1", "10.0.0.2", "10.0.0.3"]


def test_hostname_targets_pass_through():
    assert targets.expand(["example.com,host.local"]) == ["example.com", "host.local"]


def test_expand_deduplicates_and_excludes():
    result = targets.expand(["10.0.0.1,10.0.0.1", "10.0.0.2"], exclude=["10.0.0.2"])
    assert result == ["10.0.0.1"]


def test_expand_rejects_huge_networks():
    with pytest.raises(ValueError):
        targets.expand(["10.0.0.0/8"])


def test_expand_requires_ipv6_flag():
    with pytest.raises(ValueError):
        targets.expand(["::1/128"])


def test_expand_allows_ipv6_when_requested():
    assert targets.expand(["::1/128"], ipv6=True) == ["::1"]


def test_timing_templates():
    assert timing.get("4").template == "T4"
    assert timing.get("T0").name == "paranoid"
    assert timing.get("T5").concurrency >= timing.get("T1").concurrency
    with pytest.raises(ValueError):
        timing.get("T9")
