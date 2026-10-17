#include "icmp.h"

#ifdef _WIN32

#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0600
#endif

#include <winsock2.h>
#include <ws2tcpip.h>
#include <iphlpapi.h>
#include <icmpapi.h>

#include <cstring>

IcmpResult icmp_probe(const std::string& address, int timeout_ms) {
    IcmpResult result{false, 0, 0.0};
    HANDLE handle = IcmpCreateFile();
    if (handle == INVALID_HANDLE_VALUE) {
        return result;
    }
    IN_ADDR target{};
    if (InetPtonA(AF_INET, address.c_str(), &target) != 1) {
        IcmpCloseHandle(handle);
        return result;
    }
    char payload[32] = "netbreak-icmp-probe";
    IP_OPTION_INFORMATION options{};
    options.Ttl = 128;
    unsigned char reply_buffer[sizeof(ICMP_ECHO_REPLY) + 64] = {};
    DWORD replies = IcmpSendEcho(
        handle,
        target.S_un.S_addr,
        payload,
        sizeof(payload),
        &options,
        reply_buffer,
        sizeof(reply_buffer),
        static_cast<DWORD>(timeout_ms > 0 ? timeout_ms : 2000));
    if (replies > 0) {
        auto* reply = reinterpret_cast<ICMP_ECHO_REPLY*>(reply_buffer);
        if (reply->Status == IP_SUCCESS) {
            result.alive = true;
            result.ttl = reply->Options.Ttl;
            result.rtt_ms = static_cast<double>(reply->RoundTripTime);
        }
    }
    IcmpCloseHandle(handle);
    return result;
}

#else

#include <array>
#include <cstdio>
#include <cstdlib>

IcmpResult icmp_probe(const std::string& address, int timeout_ms) {
    IcmpResult result{false, 0, 0.0};
    int seconds = timeout_ms > 0 ? (timeout_ms + 999) / 1000 : 2;
    std::string command = "ping -c 1 -W " + std::to_string(seconds) + " " + address + " 2>/dev/null";
    FILE* pipe = popen(command.c_str(), "r");
    if (pipe == nullptr) {
        return result;
    }
    std::array<char, 512> buffer{};
    std::string output;
    while (std::fgets(buffer.data(), static_cast<int>(buffer.size()), pipe) != nullptr) {
        output += buffer.data();
    }
    pclose(pipe);
    auto ttl_position = output.find("ttl=");
    if (ttl_position == std::string::npos) {
        ttl_position = output.find("TTL=");
    }
    if (ttl_position != std::string::npos) {
        result.alive = true;
        result.ttl = std::atoi(output.c_str() + static_cast<long>(ttl_position) + 4);
    }
    auto time_position = output.find("time=");
    if (time_position != std::string::npos) {
        result.rtt_ms = std::atof(output.c_str() + static_cast<long>(time_position) + 5);
    }
    return result;
}

#endif
