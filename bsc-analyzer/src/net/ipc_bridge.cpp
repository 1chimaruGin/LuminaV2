// ============================================================
// Lumina BSC Tier 1 — IPC Bridge Implementation
// ============================================================
#include "lumina/net/ipc_bridge.h"
#include "lumina/tracking/logger.h"
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <cstring>
#include <poll.h>

namespace lumina {

IPCBridge::IPCBridge(const std::string& socket_path)
    : socket_path_(socket_path) {}

IPCBridge::~IPCBridge() { stop(); }

void IPCBridge::on_message(OnIpcMessage callback) {
    std::lock_guard<std::mutex> g(mu_);
    on_message_ = std::move(callback);
}

void IPCBridge::start_server() {
    if (running_.load()) return;

    server_fd_ = socket(AF_UNIX, SOCK_STREAM, 0);
    if (server_fd_ < 0) {
        LOG_ERR("IPC: socket() failed: %s", strerror(errno));
        return;
    }

    unlink(socket_path_.c_str());

    struct sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    std::strncpy(addr.sun_path, socket_path_.c_str(), sizeof(addr.sun_path) - 1);

    if (bind(server_fd_, reinterpret_cast<struct sockaddr*>(&addr), sizeof(addr)) < 0) {
        LOG_ERR("IPC: bind(%s) failed: %s", socket_path_.c_str(), strerror(errno));
        close(server_fd_);
        server_fd_ = -1;
        return;
    }
    listen(server_fd_, 4);
    running_.store(true);
    server_thread_ = std::thread(&IPCBridge::server_loop, this);
    LOG_INF("IPC bridge listening on %s", socket_path_.c_str());
}

void IPCBridge::stop() {
    if (!running_.exchange(false)) return;
    if (server_fd_ >= 0) {
        shutdown(server_fd_, SHUT_RDWR);
        close(server_fd_);
        server_fd_ = -1;
    }
    if (server_thread_.joinable()) server_thread_.join();
    unlink(socket_path_.c_str());
    LOG_INF("IPC bridge stopped");
}

void IPCBridge::server_loop() {
    while (running_.load()) {
        struct pollfd pfd{};
        pfd.fd = server_fd_;
        pfd.events = POLLIN;
        int ret = poll(&pfd, 1, 1000);
        if (ret <= 0) continue;

        int client = accept(server_fd_, nullptr, nullptr);
        if (client >= 0) {
            // Handle client in a detached thread so we can accept more
            std::thread([this, client]() {
                handle_client(client);
                close(client);
            }).detach();
        }
    }
}

void IPCBridge::handle_client(int client_fd) {
    // Read newline-delimited JSON lines from the client
    std::string buf;
    char chunk[4096];
    while (running_.load()) {
        struct pollfd pfd{};
        pfd.fd = client_fd;
        pfd.events = POLLIN;
        int ret = poll(&pfd, 1, 2000);
        if (ret < 0) break;
        if (ret == 0) continue;
        if (pfd.revents & (POLLERR | POLLHUP)) break;

        ssize_t n = read(client_fd, chunk, sizeof(chunk));
        if (n <= 0) break;
        buf.append(chunk, static_cast<size_t>(n));

        size_t pos;
        while ((pos = buf.find('\n')) != std::string::npos) {
            std::string line = buf.substr(0, pos);
            buf.erase(0, pos + 1);
            if (!line.empty()) {
                std::lock_guard<std::mutex> g(mu_);
                if (on_message_) on_message_(line);
            }
        }
    }
}

bool IPCBridge::send_line(const std::string& socket_path, const std::string& json_line) {
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return false;

    struct sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    std::strncpy(addr.sun_path, socket_path.c_str(), sizeof(addr.sun_path) - 1);

    if (connect(fd, reinterpret_cast<struct sockaddr*>(&addr), sizeof(addr)) < 0) {
        close(fd);
        return false;
    }

    std::string msg = json_line + "\n";
    ssize_t written = write(fd, msg.data(), msg.size());
    close(fd);
    return written == static_cast<ssize_t>(msg.size());
}

} // namespace lumina
