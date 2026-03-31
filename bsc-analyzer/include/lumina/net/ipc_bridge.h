// ============================================================
// Lumina BSC Tier 1 — IPC Bridge
// ============================================================
// Bidirectional Unix domain socket bridge between C++ components.
// The hotpath runs the server; the KOL monitor connects as a client
// and pushes KOL buy signals. The hotpath receives them and updates
// the token registry's kol_buy_count.
//
// Protocol: newline-delimited JSON (one JSON object per line).
// ============================================================
#pragma once
#include "lumina/core/types.h"
#include <string>
#include <functional>
#include <thread>
#include <atomic>
#include <mutex>
#include <vector>

namespace lumina {

using OnIpcMessage = std::function<void(const std::string&)>;

class IPCBridge {
public:
    explicit IPCBridge(const std::string& socket_path);
    ~IPCBridge();

    void start_server();
    void stop();

    void on_message(OnIpcMessage callback);
    bool is_running() const { return running_.load(); }

    // Client-side: connect to a running server and send a single line.
    static bool send_line(const std::string& socket_path, const std::string& json_line);

private:
    void server_loop();
    void handle_client(int client_fd);

    std::string socket_path_;
    std::thread server_thread_;
    std::atomic<bool> running_{false};
    int server_fd_ = -1;
    OnIpcMessage on_message_;
    std::mutex mu_;
};

} // namespace lumina
