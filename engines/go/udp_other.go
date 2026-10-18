//go:build !windows

package main

import "net"

func enableUDPConnReset(conn *net.UDPConn) {}
