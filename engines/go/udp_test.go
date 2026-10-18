package main

import (
	"encoding/binary"
	"net"
	"testing"
	"time"
)

func TestUDPServiceForPayloads(t *testing.T) {
	for _, port := range []int{53, 67, 69, 123, 137, 161, 1900, 5060, 5353, 5355} {
		svc := udpServiceFor(port)
		if svc.name == "" || len(svc.payload) == 0 || svc.validate == nil {
			t.Fatalf("port %d missing probe definition: %+v", port, svc)
		}
	}
	unknown := udpServiceFor(54321)
	if unknown.name != "" || unknown.payload != nil || unknown.validate != nil {
		t.Fatalf("unknown port should have no probe: %+v", unknown)
	}
}

func TestUDPValidators(t *testing.T) {
	dns := udpServiceFor(53)
	if !dns.validate([]byte{0xab, 0xcd, 0x81, 0x80, 0, 0, 0, 0, 0, 0, 0, 0}) {
		t.Fatal("dns response with QR bit should validate")
	}
	if dns.validate([]byte{0xab, 0xcd, 0x01, 0x00, 0, 0, 0, 0, 0, 0, 0, 0}) {
		t.Fatal("dns query should not validate as response")
	}

	ntp := udpServiceFor(123)
	if !ntp.validate(append([]byte{0x1c}, make([]byte, 47)...)) {
		t.Fatal("ntp server mode response should validate")
	}
	if ntp.validate(make([]byte, 10)) {
		t.Fatal("short ntp packet should not validate")
	}

	ssdp := udpServiceFor(1900)
	if !ssdp.validate([]byte("HTTP/1.1 200 OK\r\n")) {
		t.Fatal("ssdp http response should validate")
	}

	tftp := udpServiceFor(69)
	if !tftp.validate([]byte{0x00, 0x05, 0x00, 0x04}) {
		t.Fatal("tftp error packet should validate")
	}
	if tftp.validate([]byte{0x00, 0x09}) {
		t.Fatal("tftp unknown opcode should not validate")
	}

	sip := udpServiceFor(5060)
	if !sip.validate([]byte("SIP/2.0 200 OK")) {
		t.Fatal("sip response should validate")
	}

	snmp := udpServiceFor(161)
	if !snmp.validate([]byte{0x30, 0x00}) {
		t.Fatal("snmp sequence should validate")
	}

	netbios := udpServiceFor(137)
	if !netbios.validate([]byte{0, 0, 0x84, 0, 0, 0, 0, 0, 0, 0, 0, 0}) {
		t.Fatal("netbios response should validate")
	}

	dhcp := udpServiceFor(67)
	cookie := make([]byte, 240)
	cookie[236], cookie[237], cookie[238], cookie[239] = 0x63, 0x82, 0x53, 0x63
	if !dhcp.validate(cookie) {
		t.Fatal("dhcp magic cookie should validate")
	}
}

func TestHandleICMPPortUnreachable(t *testing.T) {
	scanner := &udpScanner{pending: map[uint16]int{}, states: map[int]udpResult{}}
	scanner.register(40001, 53)

	packet := make([]byte, 8+20+8)
	packet[0] = 3
	packet[1] = 3
	ip := packet[8:]
	ip[0] = 0x45
	udp := ip[20:]
	binary.BigEndian.PutUint16(udp[0:], 40001)
	binary.BigEndian.PutUint16(udp[2:], 53)

	scanner.handleICMP(packet)

	res, ok := scanner.stateOf(53)
	if !ok {
		t.Fatal("expected a recorded state for port 53")
	}
	if res.state != "closed" || res.reason != "icmp-port-unreachable" {
		t.Fatalf("unexpected result: %+v", res)
	}
}

func TestHandleICMPAdminProhibited(t *testing.T) {
	scanner := &udpScanner{pending: map[uint16]int{}, states: map[int]udpResult{}}
	scanner.register(40002, 161)

	packet := make([]byte, 8+20+8)
	packet[0] = 3
	packet[1] = 13
	ip := packet[8:]
	ip[0] = 0x45
	udp := ip[20:]
	binary.BigEndian.PutUint16(udp[0:], 40002)
	binary.BigEndian.PutUint16(udp[2:], 161)

	scanner.handleICMP(packet)

	res, ok := scanner.stateOf(161)
	if !ok {
		t.Fatal("expected a recorded state for port 161")
	}
	if res.state != "filtered" || res.reason != "icmp-admin-prohibited" {
		t.Fatalf("unexpected result: %+v", res)
	}
}

func TestHandleICMPIgnoresUnrelated(t *testing.T) {
	scanner := &udpScanner{pending: map[uint16]int{}, states: map[int]udpResult{}}
	scanner.register(40003, 123)

	packet := make([]byte, 8+20+8)
	packet[0] = 0
	packet[1] = 0
	ip := packet[8:]
	ip[0] = 0x45
	udp := ip[20:]
	binary.BigEndian.PutUint16(udp[0:], 40003)
	binary.BigEndian.PutUint16(udp[2:], 123)

	scanner.handleICMP(packet)

	if _, ok := scanner.stateOf(123); ok {
		t.Fatal("echo reply should not be recorded")
	}
}

func TestProbeOpenUDP(t *testing.T) {
	server, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1)})
	if err != nil {
		t.Fatalf("cannot start udp server: %v", err)
	}
	defer server.Close()

	go func() {
		buf := make([]byte, 256)
		for {
			n, addr, err := server.ReadFromUDP(buf)
			if err != nil {
				return
			}
			_, _ = server.WriteToUDP(append([]byte("pong:"), buf[:n]...), addr)
		}
	}()

	port := server.LocalAddr().(*net.UDPAddr).Port
	scanner := newUDPScanner("127.0.0.1", 800*time.Millisecond, 1)
	defer scanner.close()

	res := scanner.probe(port)
	if res.state != "open" {
		t.Fatalf("expected open, got %+v", res)
	}
}

func TestProbeClosedUDPLinux(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping network probe in short mode")
	}
	scanner := newUDPScanner("127.0.0.1", 400*time.Millisecond, 1)
	defer scanner.close()
	res := scanner.probe(9)
	if res.state == "open" {
		t.Fatalf("port 9 should not be open: %+v", res)
	}
}
