package main

import (
	"bufio"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"math"
	"net"
	"os"
	"sort"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

type payload struct {
	Event   string  `json:"event"`
	Port    int     `json:"port,omitempty"`
	Proto   string  `json:"proto,omitempty"`
	State   string  `json:"state,omitempty"`
	Reason  string  `json:"reason,omitempty"`
	RTT     float64 `json:"rtt_ms,omitempty"`
	Alive   bool    `json:"alive,omitempty"`
	Host    string  `json:"host,omitempty"`
	Message string  `json:"message,omitempty"`
}

type writer struct {
	mu    sync.Mutex
	out   *bufio.Writer
	emits int
}

func newWriter() *writer {
	return &writer{out: bufio.NewWriterSize(os.Stdout, 1<<16)}
}

func (w *writer) emit(p payload) {
	w.mu.Lock()
	defer w.mu.Unlock()
	if p.Event == "port" {
		w.emits++
	}
	encoded, err := json.Marshal(p)
	if err != nil {
		return
	}
	w.out.Write(encoded)
	w.out.WriteByte('\n')
	w.out.Flush()
}

func (w *writer) count() int {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.emits
}

func parsePorts(spec string) ([]int, error) {
	seen := make(map[int]bool)
	tokens := strings.Split(spec, ",")
	for _, token := range tokens {
		token = strings.TrimSpace(token)
		if token == "" {
			continue
		}
		if strings.Contains(token, "-") {
			parts := strings.SplitN(token, "-", 2)
			start, err := strconv.Atoi(strings.TrimSpace(parts[0]))
			if err != nil {
				return nil, fmt.Errorf("bad port range %q", token)
			}
			end := 65535
			if strings.TrimSpace(parts[1]) != "" {
				end, err = strconv.Atoi(strings.TrimSpace(parts[1]))
				if err != nil {
					return nil, fmt.Errorf("bad port range %q", token)
				}
			}
			if start > end {
				start, end = end, start
			}
			if start < 1 || end > 65535 {
				return nil, fmt.Errorf("port range %q outside 1-65535", token)
			}
			for port := start; port <= end; port++ {
				seen[port] = true
			}
			continue
		}
		port, err := strconv.Atoi(token)
		if err != nil {
			return nil, fmt.Errorf("bad port %q", token)
		}
		if port < 1 || port > 65535 {
			return nil, fmt.Errorf("port %q outside 1-65535", token)
		}
		seen[port] = true
	}
	ports := make([]int, 0, len(seen))
	for port := range seen {
		ports = append(ports, port)
	}
	if len(ports) == 0 {
		return nil, errors.New("no ports supplied")
	}
	sort.Ints(ports)
	return ports, nil
}

func classify(err error) (string, string) {
	if err == nil {
		return "open", "syn-ack"
	}
	var opErr *net.OpError
	if errors.As(err, &opErr) {
		if opErr.Timeout() {
			return "filtered", "no-response"
		}
		var errno syscall.Errno
		if errors.As(opErr.Err, &errno) {
			switch errno {
			case syscall.ECONNREFUSED:
				return "closed", "conn-refused"
			case syscall.ECONNRESET:
				return "closed", "conn-reset"
			case syscall.EHOSTUNREACH, syscall.ENETUNREACH:
				return "filtered", "net-unreachable"
			case syscall.EACCES, syscall.EPERM:
				return "filtered", "admin-prohibited"
			}
		}
		message := strings.ToLower(opErr.Err.Error())
		if strings.Contains(message, "refused") {
			return "closed", "conn-refused"
		}
		if strings.Contains(message, "reset") {
			return "closed", "conn-reset"
		}
	}
	return "filtered", "error"
}

func round(value float64) float64 {
	return math.Round(value*100) / 100
}

func probe(host string, port int, timeout time.Duration, retries int) payload {
	address := net.JoinHostPort(host, strconv.Itoa(port))
	attempt := 0
	for {
		start := time.Now()
		conn, err := net.DialTimeout("tcp", address, timeout)
		state, reason := classify(err)
		if err == nil {
			conn.Close()
			return payload{
				Event:  "port",
				Port:   port,
				Proto:  "tcp",
				State:  state,
				Reason: reason,
				RTT:    round(float64(time.Since(start).Microseconds()) / 1000.0),
			}
		}
		if state == "filtered" && attempt < retries {
			attempt++
			continue
		}
		if attempt > 0 {
			reason = fmt.Sprintf("%s (%d attempts)", reason, attempt+1)
		}
		return payload{Event: "port", Port: port, Proto: "tcp", State: state, Reason: reason}
	}
}

func runScan(args []string) int {
	flags := flag.NewFlagSet("scan", flag.ContinueOnError)
	host := flags.String("host", "", "target address")
	spec := flags.String("p", "", "tcp port specification")
	timeout := flags.Float64("timeout", 1.0, "per port timeout in seconds")
	concurrency := flags.Int("concurrency", 900, "simultaneous probes")
	retries := flags.Int("retries", 0, "extra attempts on filtered ports")
	if err := flags.Parse(args); err != nil {
		return 2
	}
	out := newWriter()
	if *host == "" || *spec == "" {
		out.emit(payload{Event: "error", Message: "scan requires -host and -p"})
		return 2
	}
	ports, err := parsePorts(*spec)
	if err != nil {
		out.emit(payload{Event: "error", Message: err.Error()})
		return 2
	}
	if *concurrency < 1 {
		*concurrency = 1
	}
	duration := time.Duration(*timeout * float64(time.Second))
	jobs := make(chan int)
	results := make(chan payload, *concurrency)
	done := make(chan struct{})

	var workers sync.WaitGroup
	for index := 0; index < *concurrency; index++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			for port := range jobs {
				results <- probe(*host, port, duration, *retries)
			}
		}()
	}
	go func() {
		for _, port := range ports {
			jobs <- port
		}
		close(jobs)
	}()
	go func() {
		workers.Wait()
		close(results)
	}()
	go func() {
		for result := range results {
			out.emit(result)
		}
		close(done)
	}()
	<-done
	out.emit(payload{Event: "done", Message: fmt.Sprintf("probed %d", out.count())})
	return 0
}

func runPing(args []string) int {
	flags := flag.NewFlagSet("ping", flag.ContinueOnError)
	host := flags.String("host", "", "target address")
	spec := flags.String("p", "80,443,22,445,3389", "candidate ports")
	timeout := flags.Float64("timeout", 1.0, "per port timeout in seconds")
	if err := flags.Parse(args); err != nil {
		return 2
	}
	out := newWriter()
	if *host == "" {
		out.emit(payload{Event: "error", Message: "ping requires -host"})
		return 2
	}
	ports, err := parsePorts(*spec)
	if err != nil {
		out.emit(payload{Event: "error", Message: err.Error()})
		return 2
	}
	duration := time.Duration(*timeout * float64(time.Second))
	for _, port := range ports {
		start := time.Now()
		conn, err := net.DialTimeout("tcp", net.JoinHostPort(*host, strconv.Itoa(port)), duration)
		if err == nil {
			conn.Close()
			out.emit(payload{
				Event:  "host",
				Host:   *host,
				Alive:  true,
				Reason: "tcp-connect",
				RTT:    round(float64(time.Since(start).Microseconds()) / 1000.0),
			})
			return 0
		}
	}
	out.emit(payload{Event: "host", Host: *host, Alive: false, Reason: "no-response"})
	return 0
}


var udpPayloads = map[int][]byte{
	53:  {0xab, 0xcd, 0x01, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x03, 0x77, 0x77, 0x77, 0x07, 0x65, 0x78, 0x61, 0x6d, 0x70, 0x6c, 0x65, 0x03, 0x63, 0x6f, 0x6d, 0x00, 0x00, 0x01, 0x00, 0x01},
	123: {0x1b},
	161: {0x30, 0x26, 0x02, 0x01, 0x01, 0x04, 0x06, 0x70, 0x75, 0x62, 0x6c, 0x69, 0x63},
}

func udpPayload(port int) []byte {
	if p, ok := udpPayloads[port]; ok {
		return p
	}
	return nil
}

func probeUDP(host string, port int, timeout time.Duration) payload {
	address := net.JoinHostPort(host, strconv.Itoa(port))
	start := time.Now()
	conn, err := net.Dial("udp", address)
	if err != nil {
		return payload{Event: "port", Port: port, Proto: "udp", State: "filtered", Reason: "dial-error"}
	}
	defer conn.Close()
	_ = conn.SetDeadline(time.Now().Add(timeout))
	if p := udpPayload(port); len(p) > 0 {
		if _, err := conn.Write(p); err != nil {
			return payload{Event: "port", Port: port, Proto: "udp", State: "filtered", Reason: "write-error"}
		}
	}
	buf := make([]byte, 65535)
	n, err := conn.Read(buf)
	rtt := round(float64(time.Since(start).Microseconds()) / 1000.0)
	if err == nil && n > 0 {
		return payload{Event: "port", Port: port, Proto: "udp", State: "open", Reason: "udp-response", RTT: rtt}
	}
	var opErr *net.OpError
	if errors.As(err, &opErr) && opErr.Timeout() {
		return payload{Event: "port", Port: port, Proto: "udp", State: "open|filtered", Reason: "no-response", RTT: rtt}
	}
	if err != nil {
		message := strings.ToLower(err.Error())
		if strings.Contains(message, "refused") || strings.Contains(message, "reset") {
			return payload{Event: "port", Port: port, Proto: "udp", State: "closed", Reason: "icmp-port-unreachable", RTT: rtt}
		}
		if strings.Contains(message, "unreachable") {
			return payload{Event: "port", Port: port, Proto: "udp", State: "filtered", Reason: "net-unreachable", RTT: rtt}
		}
	}
	return payload{Event: "port", Port: port, Proto: "udp", State: "open|filtered", Reason: "no-response", RTT: rtt}
}

func runUDPScan(args []string) int {
	flags := flag.NewFlagSet("udpscan", flag.ContinueOnError)
	host := flags.String("host", "", "target address")
	spec := flags.String("p", "", "udp port specification")
	timeout := flags.Float64("timeout", 2.0, "per port timeout in seconds")
	concurrency := flags.Int("concurrency", 150, "simultaneous probes")
	if err := flags.Parse(args); err != nil {
		return 2
	}
	out := newWriter()
	if *host == "" || *spec == "" {
		out.emit(payload{Event: "error", Message: "udpscan requires -host and -p"})
		return 2
	}
	ports, err := parsePorts(*spec)
	if err != nil {
		out.emit(payload{Event: "error", Message: err.Error()})
		return 2
	}
	if *concurrency < 1 {
		*concurrency = 1
	}
	duration := time.Duration(*timeout * float64(time.Second))
	jobs := make(chan int)
	results := make(chan payload, *concurrency)
	done := make(chan struct{})

	var workers sync.WaitGroup
	for index := 0; index < *concurrency; index++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			for port := range jobs {
				results <- probeUDP(*host, port, duration)
			}
		}()
	}
	go func() {
		for _, port := range ports {
			jobs <- port
		}
		close(jobs)
	}()
	go func() {
		workers.Wait()
		close(results)
	}()
	go func() {
		for result := range results {
			out.emit(result)
		}
		close(done)
	}()
	<-done
	out.emit(payload{Event: "done", Message: fmt.Sprintf("probed %d", out.emits)})
	return 0
}


func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: netbreak-engine <scan|ping|udpscan> [options]")
		os.Exit(2)
	}
	switch os.Args[1] {
	case "scan":
		os.Exit(runScan(os.Args[2:]))
	case "ping":
		os.Exit(runPing(os.Args[2:]))
	case "udpscan":
		os.Exit(runUDPScan(os.Args[2:]))
	case "version":
		fmt.Println("netbreak-engine 2.0.0")
	default:
		fmt.Fprintf(os.Stderr, "unknown command %q\n", os.Args[1])
		os.Exit(2)
	}
}
