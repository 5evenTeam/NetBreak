#pragma once

#include <string>

struct IcmpResult {
    bool alive;
    int ttl;
    double rtt_ms;
};

IcmpResult icmp_probe(const std::string& address, int timeout_ms);
