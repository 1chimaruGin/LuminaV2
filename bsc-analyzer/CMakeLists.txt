# ==============================================================================
# Lumina BSC Tier-1 Hot Path
# ==============================================================================
# C++20 Four.meme intelligence (filter_1 / filter_2): WS + RPC, heuristic scoring.
#
# Layout:
#   fourmeme/   TokenCreate ingest, per-token state, scoring (hot path)
#   net/        bsc_ws_client, rpc_client, honeypot_checker (GoPlus), json_minimal
#   pipeline/   tx_parser, detector, scorer (micro-benchmark components only)
#
# Targets:
#   lumina_hotpath          – Live Four.meme JSONL
#   lumina_bench            – Pipeline micro-benchmarks
#   lumina_replay_fourmeme  – Four.meme TokenCreate replay / --recent N (chunked getLogs); same scorer as hotpath
#
# Build:
#   mkdir -p build && cd build && cmake .. && make -j$(nproc)
#
# Dependencies:
#   - C++20 compiler (GCC 11+ or Clang 14+)
#   - OpenSSL (for WebSocket TLS)
#   - libcurl (for HTTP requests)
#   - pthreads
# ==============================================================================

cmake_minimum_required(VERSION 3.20)
project(lumina_bsc_tier1 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

set(CMAKE_CXX_FLAGS_RELEASE "-O3 -march=native -DNDEBUG")
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

# --- Dependencies ---
find_package(Threads REQUIRED)
find_package(OpenSSL REQUIRED)
find_package(CURL REQUIRED)

# --- Static library from src/ (excludes main.cpp) ---
set(LUMINA_LIB_SOURCES
    src/core/types.cpp
    src/data/deployer_db.cpp
    src/data/clickhouse_writer.cpp
    src/data/live_writer.cpp
    src/pipeline/tx_parser.cpp
    src/pipeline/detector.cpp
    src/pipeline/scorer.cpp
    src/net/honeypot_checker.cpp
    src/net/ipc_bridge.cpp
    src/net/json_minimal.cpp
    src/net/rpc_client.cpp
    src/net/bsc_ws_client.cpp
    src/net/binance_klines.cpp
    src/fourmeme/constants.cpp
    src/fourmeme/token_create_abi.cpp
    src/fourmeme/token_registry.cpp
    src/fourmeme/fourmeme_service.cpp
    src/tracking/logger.cpp
)

add_library(lumina_core STATIC ${LUMINA_LIB_SOURCES})
target_include_directories(lumina_core PUBLIC include)
target_link_libraries(lumina_core PUBLIC
    Threads::Threads
    OpenSSL::SSL
    OpenSSL::Crypto
    CURL::libcurl
)

# --- Live pipeline ---
add_executable(lumina_hotpath src/main.cpp)
target_link_libraries(lumina_hotpath PRIVATE lumina_core)

# --- Pipeline benchmark (latency + throughput) ---
add_executable(lumina_bench bench/benchmark.cpp)
target_link_libraries(lumina_bench PRIVATE lumina_core)

add_executable(lumina_replay_fourmeme bench/replay_fourmeme.cpp)
target_link_libraries(lumina_replay_fourmeme PRIVATE lumina_core)

# --- KOL copy-trade monitor (real-time WSS) ---
add_executable(lumina_kol_monitor bench/kol_monitor.cpp)
target_link_libraries(lumina_kol_monitor PRIVATE lumina_core)
