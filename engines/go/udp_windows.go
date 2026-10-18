//go:build windows

package main

import (
	"net"
	"syscall"
	"unsafe"
)

const sioUDPConnReset = 0x9800000C

func enableUDPConnReset(conn *net.UDPConn) {
	raw, err := conn.SyscallConn()
	if err != nil {
		return
	}
	_ = raw.Control(func(fd uintptr) {
		var in uint32 = 1
		var out uint32
		_ = syscall.WSAIoctl(syscall.Handle(fd), sioUDPConnReset, (*byte)(unsafe.Pointer(&in)), 4, nil, 0, &out, nil, 0)
	})
}
