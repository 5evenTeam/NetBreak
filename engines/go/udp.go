package main

import (
	"encoding/binary"
	"errors"
	"net"
	"strings"
	"sync"
	"time"
)

type udpService struct {
	name     string
	payload  []byte
	validate func([]byte) bool
}

type udpResult struct {
	state  string
	reason string
	rtt    float64
}

type udpScanner struct {
	host    string
	timeout time.Duration
	retries int
	icmp    *net.IPConn
	mu      sync.Mutex
	pending map[uint16]int
	states  map[int]udpResult
}

func dnsValidate(b []byte) bool {
	return len(b) >= 12 && b[2]&0x80 != 0
}

func dnsQuery(txid uint16, name []byte) []byte {
	out := make([]byte, 0, 12+len(name)+4)
	out = append(out, byte(txid>>8), byte(txid))
	out = append(out, 0x01, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00)
	out = append(out, name...)
	out = append(out, 0x00, 0x01, 0x00, 0x01)
	return out
}

var mdnsName = []byte{9, '_', 's', 'e', 'r', 'v', 'i', 'c', 'e', 's', 7, '_', 'd', 'n', 's', '-', 's', 'd', 4, '_', 'u', 'd', 'p', 5, 'l', 'o', 'c', 'a', 'l'}

var llmnrName = []byte{8, 'n', 'e', 't', 'b', 'r', 'e', 'a', 'k'}

var nbstatName = func() []byte {
	out := []byte{0x20, 0x43, 0x4b}
	for i := 0; i < 15; i++ {
		out = append(out, 0x43, 0x41)
	}
	return append(out, 0x00)
}()

var nbstatPayload = append([]byte{0x82, 0x28, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}, append(nbstatName, 0x00, 0x21, 0x00, 0x01)...)

var ntpPayload = func() []byte {
	out := make([]byte, 48)
	out[0] = 0x1b
	return out
}()

var snmpPayload = []byte{
	0x30, 0x27, 0x02, 0x01, 0x00, 0x04, 0x06, 'p', 'u', 'b', 'l', 'i', 'c',
	0xa0, 0x1a, 0x02, 0x04, 0x00, 0x00, 0x00, 0x01, 0x02, 0x01, 0x00, 0x02, 0x01, 0x00,
	0x30, 0x0c, 0x30, 0x0a, 0x06, 0x08, 0x2b, 0x06, 0x01, 0x02, 0x01, 0x01, 0x01, 0x00, 0x05, 0x00,
}

var tftpPayload = func() []byte {
	out := []byte{0x00, 0x01}
	out = append(out, []byte("netbreak-probe")...)
	out = append(out, 0x00)
	out = append(out, []byte("octet")...)
	return append(out, 0x00)
}()

var ssdpPayload = []byte("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 1\r\nST: ssdp:all\r\n\r\n")

var dhcpPayload = func() []byte {
	out := make([]byte, 240)
	out[0] = 1
	out[1] = 1
	out[2] = 6
	copy(out[4:8], []byte{0xab, 0xcd, 0x12, 0x34})
	out[236] = 0x63
	out[237] = 0x82
	out[238] = 0x53
	out[239] = 0x63
	return out
}()

var sipPayload = []byte("OPTIONS sip:netbreak@localhost SIP/2.0\r\nVia: SIP/2.0/UDP 127.0.0.1:5060\r\nMax-Forwards: 70\r\nTo: <sip:netbreak@localhost>\r\nFrom: <sip:probe@localhost>;tag=netbreak\r\nCall-ID: netbreak\r\nCSeq: 1 OPTIONS\r\nContent-Length: 0\r\n\r\n")

func udpServiceFor(port int) udpService {
	switch port {
	case 53:
		return udpService{name: "domain", payload: dnsQuery(0xabcd, []byte{3, 'w', 'w', 'w', 7, 'e', 'x', 'a', 'm', 'p', 'l', 'e', 3, 'c', 'o', 'm'}), validate: dnsValidate}
	case 67, 68:
		return udpService{name: "dhcp", payload: dhcpPayload, validate: func(b []byte) bool {
			return len(b) >= 240 && b[236] == 0x63 && b[237] == 0x82 && b[238] == 0x53 && b[239] == 0x63
		}}
	case 69:
		return udpService{name: "tftp", payload: tftpPayload, validate: func(b []byte) bool {
			return len(b) >= 2 && b[0] == 0x00 && b[1] >= 0x01 && b[1] <= 0x05
		}}
	case 123:
		return udpService{name: "ntp", payload: ntpPayload, validate: func(b []byte) bool {
			return len(b) >= 48 && b[0]&0x07 == 4
		}}
	case 137:
		return udpService{name: "netbios-ns", payload: nbstatPayload, validate: func(b []byte) bool {
			return len(b) >= 12 && b[2]&0x80 != 0
		}}
	case 161:
		return udpService{name: "snmp", payload: snmpPayload, validate: func(b []byte) bool {
			return len(b) >= 2 && b[0] == 0x30
		}}
	case 1900:
		return udpService{name: "ssdp", payload: ssdpPayload, validate: func(b []byte) bool {
			return len(b) >= 8 && strings.HasPrefix(string(b), "HTTP/1.")
		}}
	case 5060:
		return udpService{name: "sip", payload: sipPayload, validate: func(b []byte) bool {
			return len(b) >= 8 && strings.HasPrefix(string(b), "SIP/2.0")
		}}
	case 5353:
		return udpService{name: "mdns", payload: dnsQuery(0, mdnsName), validate: dnsValidate}
	case 5355:
		return udpService{name: "llmnr", payload: dnsQuery(0x1234, llmnrName), validate: dnsValidate}
	default:
		return udpService{}
	}
}

func newUDPScanner(host string, timeout time.Duration, retries int) *udpScanner {
	if timeout <= 0 {
		timeout = time.Second
	}
	if retries < 0 {
		retries = 0
	}
	s := &udpScanner{
		host:    host,
		timeout: timeout,
		retries: retries,
		pending: map[uint16]int{},
		states:  map[int]udpResult{},
	}
	if conn, err := net.ListenIP("ip4:icmp", &net.IPAddr{IP: net.IPv4zero}); err == nil {
		s.icmp = conn
		go s.readICMP()
	}
	return s
}

func (s *udpScanner) close() {
	if s.icmp != nil {
		_ = s.icmp.Close()
	}
}

func (s *udpScanner) readICMP() {
	buf := make([]byte, 4096)
	for {
		n, _, err := s.icmp.ReadFrom(buf)
		if err != nil {
			return
		}
		s.handleICMP(buf[:n])
	}
}

func (s *udpScanner) handleICMP(pkt []byte) {
	if len(pkt) < 8 || pkt[0] != 3 {
		return
	}
	code := pkt[1]
	off := 8
	if len(pkt) < off+20 {
		return
	}
	ihl := int(pkt[off]&0x0f) * 4
	if ihl < 20 || len(pkt) < off+ihl+8 {
		return
	}
	udpOff := off + ihl
	srcPort := binary.BigEndian.Uint16(pkt[udpOff : udpOff+2])

	s.mu.Lock()
	defer s.mu.Unlock()
	port, ok := s.pending[srcPort]
	if !ok {
		return
	}
	state, reason := "filtered", "icmp-unreachable"
	switch code {
	case 3:
		state, reason = "closed", "icmp-port-unreachable"
	case 1:
		state, reason = "filtered", "icmp-host-unreachable"
	case 2:
		state, reason = "filtered", "icmp-protocol-unreachable"
	case 9, 10, 13:
		state, reason = "filtered", "icmp-admin-prohibited"
	}
	if _, exists := s.states[port]; !exists {
		s.states[port] = udpResult{state: state, reason: reason}
	}
}

func (s *udpScanner) stateOf(port int) (udpResult, bool) {
	s.mu.Lock()
	defer s.mu.Unlock()
	res, ok := s.states[port]
	return res, ok
}

func (s *udpScanner) register(local, port int) {
	s.mu.Lock()
	s.pending[uint16(local)] = port
	s.mu.Unlock()
}

func (s *udpScanner) unregister(local int) {
	s.mu.Lock()
	delete(s.pending, uint16(local))
	s.mu.Unlock()
}

func (s *udpScanner) probe(port int) udpResult {
	ip := net.ParseIP(s.host)
	if ip == nil {
		return udpResult{state: "filtered", reason: "bad-target"}
	}
	svc := udpServiceFor(port)
	payload := svc.payload
	if len(payload) == 0 {
		payload = []byte{0x00}
	}
	target := &net.UDPAddr{IP: ip, Port: port}

	for attempt := 0; attempt <= s.retries; attempt++ {
		conn, err := net.DialUDP("udp4", nil, target)
		if err != nil {
			return udpResult{state: "filtered", reason: "socket-error"}
		}
		enableUDPConnReset(conn)
		local := conn.LocalAddr().(*net.UDPAddr).Port
		s.register(local, port)
		start := time.Now()
		_, werr := conn.Write(payload)
		if werr != nil {
			s.unregister(local)
			_ = conn.Close()
			return udpResult{state: "filtered", reason: "write-error"}
		}
		result, done := s.wait(conn, port, time.Now().Add(s.timeout), svc, start)
		_ = conn.Close()
		if done {
			s.unregister(local)
			return result
		}
		time.Sleep(80 * time.Millisecond)
		if res, ok := s.stateOf(port); ok {
			s.unregister(local)
			return res
		}
		s.unregister(local)
	}
	if res, ok := s.stateOf(port); ok {
		return res
	}
	return udpResult{state: "open|filtered", reason: "no-response"}
}

func (s *udpScanner) wait(conn *net.UDPConn, port int, deadline time.Time, svc udpService, start time.Time) (udpResult, bool) {
	buf := make([]byte, 65535)
	for time.Now().Before(deadline) {
		slice := time.Now().Add(120 * time.Millisecond)
		if slice.After(deadline) {
			slice = deadline
		}
		_ = conn.SetReadDeadline(slice)
		n, err := conn.Read(buf)
		if err == nil {
			if svc.validate == nil || svc.validate(buf[:n]) {
				return udpResult{state: "open", reason: serviceReason(svc), rtt: round(float64(time.Since(start).Microseconds()) / 1000.0)}, true
			}
			continue
		}
		if res, ok := s.stateOf(port); ok {
			return res, true
		}
		var netErr net.Error
		if errors.As(err, &netErr) && netErr.Timeout() {
			continue
		}
		lower := strings.ToLower(err.Error())
		if strings.Contains(lower, "refused") || strings.Contains(lower, "reset") || strings.Contains(lower, "forcibly closed") {
			return udpResult{state: "closed", reason: "icmp-port-unreachable"}, true
		}
	}
	if res, ok := s.stateOf(port); ok {
		return res, true
	}
	return udpResult{}, false
}

func serviceReason(svc udpService) string {
	if svc.name != "" {
		return "udp-response:" + svc.name
	}
	return "udp-response"
}
