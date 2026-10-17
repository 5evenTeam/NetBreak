#include "icmp.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#ifdef _WIN32
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0600
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
using socket_type = SOCKET;
const socket_type bad_socket = INVALID_SOCKET;
using socklen_type = int;
#else
#include <arpa/inet.h>
#include <cerrno>
#include <fcntl.h>
#include <netinet/in.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <unistd.h>
using socket_type = int;
const socket_type bad_socket = -1;
using socklen_type = socklen_t;
#endif

namespace {

std::mutex g_output;

void emit(const std::string& line) {
    std::lock_guard<std::mutex> guard(g_output);
    std::cout << line << '\n' << std::flush;
}

std::string escape(const std::string& value) {
    std::string out;
    out.reserve(value.size());
    for (char character : value) {
        switch (character) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (static_cast<unsigned char>(character) < 0x20) {
                    out += ' ';
                } else {
                    out += character;
                }
        }
    }
    return out;
}

std::string fixed(double value) {
    std::ostringstream stream;
    stream << std::fixed << std::setprecision(2) << value;
    return stream.str();
}

bool init_networking() {
#ifdef _WIN32
    WSADATA data{};
    return WSAStartup(MAKEWORD(2, 2), &data) == 0;
#else
    return true;
#endif
}

void shutdown_networking() {
#ifdef _WIN32
    WSACleanup();
#endif
}

void close_socket(socket_type handle) {
#ifdef _WIN32
    closesocket(handle);
#else
    ::close(handle);
#endif
}

int socket_error() {
#ifdef _WIN32
    return WSAGetLastError();
#else
    return errno;
#endif
}

bool in_progress_error(int code) {
#ifdef _WIN32
    return code == WSAEWOULDBLOCK || code == WSAEINPROGRESS;
#else
    return code == EINPROGRESS || code == EWOULDBLOCK;
#endif
}

std::vector<int> parse_ports(const std::string& spec) {
    std::vector<int> ports;
    std::stringstream stream(spec);
    std::string token;
    while (std::getline(stream, token, ',')) {
        if (token.empty()) {
            continue;
        }
        auto dash = token.find('-');
        if (dash == std::string::npos) {
            int port = std::atoi(token.c_str());
            if (port >= 1 && port <= 65535) {
                ports.push_back(port);
            }
            continue;
        }
        std::string left = token.substr(0, dash);
        std::string right = token.substr(dash + 1);
        int start = left.empty() ? 1 : std::atoi(left.c_str());
        int end = right.empty() ? 65535 : std::atoi(right.c_str());
        if (start > end) {
            std::swap(start, end);
        }
        start = std::max(start, 1);
        end = std::min(end, 65535);
        for (int port = start; port <= end; ++port) {
            ports.push_back(port);
        }
    }
    std::sort(ports.begin(), ports.end());
    ports.erase(std::unique(ports.begin(), ports.end()), ports.end());
    return ports;
}

struct Outcome {
    const char* state;
    const char* reason;
    double rtt_ms;
};

Outcome classify(int code) {
#ifdef _WIN32
    switch (code) {
        case WSAECONNREFUSED: return {"closed", "conn-refused", 0.0};
        case WSAECONNRESET: return {"closed", "conn-reset", 0.0};
        case WSAEHOSTUNREACH:
        case WSAENETUNREACH: return {"filtered", "net-unreachable", 0.0};
        case WSAETIMEDOUT: return {"filtered", "no-response", 0.0};
        case WSAEACCES: return {"filtered", "admin-prohibited", 0.0};
        default: return {"filtered", "error", 0.0};
    }
#else
    switch (code) {
        case ECONNREFUSED: return {"closed", "conn-refused", 0.0};
        case ECONNRESET: return {"closed", "conn-reset", 0.0};
        case EHOSTUNREACH:
        case ENETUNREACH: return {"filtered", "net-unreachable", 0.0};
        case ETIMEDOUT: return {"filtered", "no-response", 0.0};
        case EACCES:
        case EPERM: return {"filtered", "admin-prohibited", 0.0};
        default: return {"filtered", "error", 0.0};
    }
#endif
}

void set_nonblocking(socket_type handle) {
#ifdef _WIN32
    u_long mode = 1;
    ioctlsocket(handle, FIONBIO, &mode);
#else
    int flags = fcntl(handle, F_GETFL, 0);
    fcntl(handle, F_SETFL, flags | O_NONBLOCK);
#endif
}

Outcome probe_connect(const std::string& host, int port, int timeout_ms) {
    socket_type handle = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (handle == bad_socket) {
        return {"filtered", "socket-failed", 0.0};
    }
    ::sockaddr_in target{};
    target.sin_family = AF_INET;
    target.sin_port = htons(static_cast<unsigned short>(port));
#ifdef _WIN32
    InetPtonA(AF_INET, host.c_str(), &target.sin_addr);
#else
    inet_pton(AF_INET, host.c_str(), &target.sin_addr);
#endif
    set_nonblocking(handle);
    auto started = std::chrono::steady_clock::now();
    int code = ::connect(handle, reinterpret_cast<sockaddr*>(&target), sizeof(target));
    Outcome outcome{"filtered", "error", 0.0};
    bool finished = false;
    if (code == 0) {
        outcome = {"open", "syn-ack", 0.0};
        finished = true;
    } else if (!in_progress_error(socket_error())) {
        outcome = classify(socket_error());
        finished = true;
    }
    if (!finished) {
        fd_set writable;
        FD_ZERO(&writable);
        FD_SET(handle, &writable);
        timeval timeout{timeout_ms / 1000, (timeout_ms % 1000) * 1000};
        int ready = select(static_cast<int>(handle) + 1, nullptr, &writable, nullptr, &timeout);
        if (ready <= 0) {
            outcome = {"filtered", "no-response", 0.0};
        } else {
            int error = 0;
            socklen_type length = sizeof(error);
            getsockopt(handle, SOL_SOCKET, SO_ERROR, reinterpret_cast<char*>(&error), &length);
            if (error == 0) {
                outcome = {"open", "syn-ack", 0.0};
            } else {
                outcome = classify(error);
            }
        }
    }
    if (std::string(outcome.state) == "open") {
        auto finished_at = std::chrono::steady_clock::now();
        std::chrono::duration<double, std::milli> elapsed = finished_at - started;
        outcome.rtt_ms = elapsed.count();
    }
    close_socket(handle);
    return outcome;
}

int run_connect(const std::vector<std::string>& args) {
    if (args.size() < 3) {
        emit("{\"event\":\"error\",\"message\":\"connect requires <host> <ports>\"}");
        return 2;
    }
    std::string host = args[1];
    std::vector<int> ports = parse_ports(args[2]);
    if (ports.empty()) {
        emit("{\"event\":\"error\",\"message\":\"no ports supplied\"}");
        return 2;
    }
    int timeout_ms = 1000;
    int concurrency = 900;
    int retries = 0;
    for (std::size_t index = 3; index + 1 < args.size(); index += 2) {
        const std::string& key = args[index];
        const std::string& value = args[index + 1];
        if (key == "-timeout") {
            timeout_ms = static_cast<int>(std::atof(value.c_str()) * 1000.0);
        } else if (key == "-concurrency") {
            concurrency = std::atoi(value.c_str());
        } else if (key == "-retries") {
            retries = std::atoi(value.c_str());
        }
    }
    if (concurrency < 1) {
        concurrency = 1;
    }
    if (timeout_ms < 1) {
        timeout_ms = 1;
    }
    std::atomic<std::size_t> next{0};
    std::atomic<int> produced{0};
    std::size_t worker_count = std::min<std::size_t>(static_cast<std::size_t>(concurrency), ports.size());
    std::vector<std::thread> workers;
    workers.reserve(worker_count);
    for (std::size_t index = 0; index < worker_count; ++index) {
        workers.emplace_back([&]() {
            while (true) {
                std::size_t position = next.fetch_add(1);
                if (position >= ports.size()) {
                    return;
                }
                int port = ports[position];
                Outcome outcome = probe_connect(host, port, timeout_ms);
                std::string reason = outcome.reason;
                int attempt = 0;
                while (std::string(outcome.state) == "filtered" && attempt < retries) {
                    attempt++;
                    outcome = probe_connect(host, port, timeout_ms);
                }
                if (attempt > 0) {
                    reason = reason + " (" + std::to_string(attempt + 1) + " attempts)";
                }
                std::ostringstream line;
                line << "{\"event\":\"port\",\"port\":" << port
                     << ",\"proto\":\"tcp\",\"state\":\"" << outcome.state
                     << "\",\"reason\":\"" << escape(reason) << "\"";
                if (std::string(outcome.state) == "open") {
                    line << ",\"rtt_ms\":" << fixed(outcome.rtt_ms);
                }
                line << "}";
                produced.fetch_add(1);
                emit(line.str());
            }
        });
    }
    for (auto& worker : workers) {
        worker.join();
    }
    std::ostringstream summary;
    summary << "{\"event\":\"done\",\"message\":\"probed " << produced.load() << "\"}";
    emit(summary.str());
    return 0;
}

int run_icmp(const std::vector<std::string>& args) {
    if (args.size() < 2) {
        emit("{\"event\":\"error\",\"message\":\"icmp requires <host> [timeout_ms]\"}");
        return 2;
    }
    std::string host = args[1];
    int timeout_ms = args.size() > 2 ? std::atoi(args[2].c_str()) : 2000;
    IcmpResult result = icmp_probe(host, timeout_ms);
    std::ostringstream line;
    line << "{\"event\":\"host\",\"host\":\"" << escape(host) << "\",\"alive\":"
         << (result.alive ? "true" : "false")
         << ",\"ttl\":" << result.ttl
         << ",\"rtt_ms\":" << fixed(result.rtt_ms) << "}";
    emit(line.str());
    return 0;
}

}

int main(int argc, char** argv) {
    std::vector<std::string> args;
    for (int index = 1; index < argc; ++index) {
        args.emplace_back(argv[index]);
    }
    if (args.empty()) {
        std::cerr << "usage: netbreak-native <connect|icmp> [options]\n";
        return 2;
    }
    if (!init_networking()) {
        emit("{\"event\":\"error\",\"message\":\"network stack unavailable\"}");
        return 1;
    }
    int status = 2;
    if (args[0] == "connect") {
        status = run_connect(args);
    } else if (args[0] == "icmp") {
        status = run_icmp(args);
    } else if (args[0] == "version") {
        std::cout << "netbreak-native 2.0.0\n";
        status = 0;
    } else {
        std::cerr << "unknown command " << args[0] << '\n';
        status = 2;
    }
    shutdown_networking();
    return status;
}
