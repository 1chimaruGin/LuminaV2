#!/usr/bin/env python3
"""
Lumina BSC Tier 2 — IPC Client

Connects to C++ Tier 1 via shared memory and Unix socket.
Receives scored events and performs deeper analysis.

Usage:
    python scripts/tier2_client.py [--verbose]
"""

import argparse
import mmap
import os
import signal
import socket
import struct
import sys
import time
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, Optional

# IPC Constants (must match C++ side)
SHM_NAME = "/lumina_tier1_events"
SHM_PATH = "/dev/shm" + SHM_NAME
SOCKET_PATH = "/tmp/lumina_tier1.sock"
SHM_RING_SIZE = 4096
SHM_EVENT_SIZE = 512
SHM_HEADER_SIZE = 64


class IPCMessageType(IntEnum):
    HANDSHAKE = 0x01
    HANDSHAKE_ACK = 0x02
    EVENT = 0x10
    EVENT_BATCH = 0x11
    STATS_REQUEST = 0x20
    STATS_RESPONSE = 0x21
    SHUTDOWN = 0xFF


class Decision(IntEnum):
    HARD_REJECT = 0
    FORWARD_TIER2 = 1
    FAST_PASS = 2


class EventType(IntEnum):
    UNKNOWN = 0
    CONTRACT_CREATION = 1
    ADD_LIQUIDITY = 2
    REMOVE_LIQUIDITY = 3
    BUY = 4
    SELL = 5
    TRANSFER = 6
    APPROVAL = 7
    OWNERSHIP_CHANGE = 8


@dataclass
class SerializedEvent:
    """Matches C++ SerializedEvent struct"""
    timestamp_ns: int
    recv_time_ns: int
    decision_time_ns: int
    decision: Decision
    event_type: EventType
    checks_performed: int
    flags: int
    final_score: float
    deployer_score: float
    buy_tax: float
    sell_tax: float
    tx_hash: str
    from_address: str
    to_address: str
    token_address: str
    value_wei: int
    gas_price: int
    input_length: int

    @property
    def latency_us(self) -> float:
        return (self.decision_time_ns - self.recv_time_ns) / 1000.0

    @property
    def is_blacklisted(self) -> bool:
        return bool(self.flags & 0x01)

    @property
    def is_scam_bytecode(self) -> bool:
        return bool(self.flags & 0x02)

    @property
    def has_mint_authority(self) -> bool:
        return bool(self.flags & 0x04)

    @property
    def has_dangerous_funcs(self) -> bool:
        return bool(self.flags & 0x08)

    @property
    def is_lp_locked(self) -> bool:
        return bool(self.flags & 0x10)


class Tier2Client:
    """Python client for Lumina Tier 1 IPC"""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.sock: Optional[socket.socket] = None
        self.shm_fd: Optional[int] = None
        self.shm_mm: Optional[mmap.mmap] = None
        self.running = False
        self.last_read_pos = 0
        self.events_processed = 0

    def connect(self) -> bool:
        """Connect to Tier 1 via Unix socket and shared memory"""
        # Connect to control socket
        try:
            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.sock.connect(SOCKET_PATH)
            self.sock.settimeout(5.0)
            print(f"[Tier2] Connected to socket: {SOCKET_PATH}")
        except Exception as e:
            print(f"[Tier2] Failed to connect to socket: {e}")
            return False

        # Receive handshake
        try:
            data = self.sock.recv(16)
            if len(data) < 16:
                print("[Tier2] Invalid handshake")
                return False

            msg_type = data[0]
            if msg_type != IPCMessageType.HANDSHAKE:
                print(f"[Tier2] Expected handshake, got {msg_type}")
                return False

            protocol_version = data[1]
            ring_size = struct.unpack("<I", data[4:8])[0]
            event_size = struct.unpack("<I", data[8:12])[0]

            print(f"[Tier2] Handshake: protocol={protocol_version}, ring={ring_size}, event_size={event_size}")

            # Send handshake ack
            ack = bytearray(16)
            ack[0] = IPCMessageType.HANDSHAKE_ACK
            struct.pack_into("<I", ack, 4, os.getpid())
            self.sock.send(bytes(ack))

        except Exception as e:
            print(f"[Tier2] Handshake failed: {e}")
            return False

        # Open shared memory
        try:
            self.shm_fd = os.open(SHM_PATH, os.O_RDWR)
            shm_size = SHM_HEADER_SIZE + SHM_RING_SIZE * SHM_EVENT_SIZE
            self.shm_mm = mmap.mmap(self.shm_fd, shm_size, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
            print(f"[Tier2] Mapped shared memory: {SHM_PATH} ({shm_size} bytes)")
        except Exception as e:
            print(f"[Tier2] Failed to map shared memory: {e}")
            return False

        return True

    def disconnect(self):
        """Disconnect from Tier 1"""
        if self.shm_mm:
            self.shm_mm.close()
            self.shm_mm = None
        if self.shm_fd:
            os.close(self.shm_fd)
            self.shm_fd = None
        if self.sock:
            try:
                # Send shutdown
                msg = bytearray(16)
                msg[0] = IPCMessageType.SHUTDOWN
                self.sock.send(bytes(msg))
            except:
                pass
            self.sock.close()
            self.sock = None
        print("[Tier2] Disconnected")

    def read_header(self) -> tuple[int, int]:
        """Read write_pos and read_pos from shared memory header"""
        self.shm_mm.seek(0)
        data = self.shm_mm.read(SHM_HEADER_SIZE)
        write_pos = struct.unpack("<Q", data[0:8])[0]
        read_pos = struct.unpack("<Q", data[8:16])[0]
        return write_pos, read_pos

    def update_read_pos(self, pos: int):
        """Update read position in shared memory"""
        self.shm_mm.seek(8)
        self.shm_mm.write(struct.pack("<Q", pos))

    def read_event(self, index: int) -> SerializedEvent:
        """Read a single event from the ring buffer"""
        offset = SHM_HEADER_SIZE + (index % SHM_RING_SIZE) * SHM_EVENT_SIZE
        self.shm_mm.seek(offset)
        data = self.shm_mm.read(SHM_EVENT_SIZE)

        # Parse event (matches C++ SerializedEvent struct)
        timestamp_ns = struct.unpack("<Q", data[0:8])[0]
        recv_time_ns = struct.unpack("<Q", data[8:16])[0]
        decision_time_ns = struct.unpack("<Q", data[16:24])[0]

        decision = Decision(data[24])
        event_type = EventType(data[25])
        checks_performed = data[26]
        flags = data[27]

        final_score = struct.unpack("<f", data[28:32])[0]
        deployer_score = struct.unpack("<f", data[32:36])[0]
        buy_tax = struct.unpack("<f", data[36:40])[0]
        sell_tax = struct.unpack("<f", data[40:44])[0]

        tx_hash = data[44:110].decode("utf-8", errors="ignore").rstrip("\x00")
        from_address = data[110:152].decode("utf-8", errors="ignore").rstrip("\x00")
        to_address = data[152:194].decode("utf-8", errors="ignore").rstrip("\x00")
        token_address = data[194:236].decode("utf-8", errors="ignore").rstrip("\x00")

        value_wei = struct.unpack("<Q", data[236:244])[0]
        gas_price = struct.unpack("<Q", data[244:252])[0]
        input_length = struct.unpack("<I", data[252:256])[0]

        return SerializedEvent(
            timestamp_ns=timestamp_ns,
            recv_time_ns=recv_time_ns,
            decision_time_ns=decision_time_ns,
            decision=decision,
            event_type=event_type,
            checks_performed=checks_performed,
            flags=flags,
            final_score=final_score,
            deployer_score=deployer_score,
            buy_tax=buy_tax,
            sell_tax=sell_tax,
            tx_hash=tx_hash,
            from_address=from_address,
            to_address=to_address,
            token_address=token_address,
            value_wei=value_wei,
            gas_price=gas_price,
            input_length=input_length,
        )

    def poll_events(self, callback: Callable[[SerializedEvent], None], batch_size: int = 100):
        """Poll for new events and call callback for each"""
        write_pos, _ = self.read_header()

        count = 0
        while self.last_read_pos < write_pos and count < batch_size:
            event = self.read_event(self.last_read_pos)
            self.last_read_pos += 1
            self.events_processed += 1
            count += 1
            callback(event)

        # Update read position
        if count > 0:
            self.update_read_pos(self.last_read_pos)

        return count

    def run(self, callback: Callable[[SerializedEvent], None]):
        """Main event loop"""
        self.running = True
        print("[Tier2] Starting event loop...")

        last_stats_time = time.time()
        events_since_stats = 0

        while self.running:
            count = self.poll_events(callback)
            events_since_stats += count

            if count == 0:
                time.sleep(0.001)  # 1ms sleep when no events

            # Print stats every 10 seconds
            now = time.time()
            if now - last_stats_time >= 10.0:
                rate = events_since_stats / (now - last_stats_time)
                print(f"[Tier2] Processed {self.events_processed} total, {rate:.1f} events/sec")
                last_stats_time = now
                events_since_stats = 0

    def stop(self):
        """Stop the event loop"""
        self.running = False


def default_event_handler(event: SerializedEvent):
    """Default handler that prints events"""
    decision_str = {
        Decision.HARD_REJECT: "REJECT",
        Decision.FORWARD_TIER2: "FORWARD",
        Decision.FAST_PASS: "PASS",
    }.get(event.decision, "???")

    event_str = {
        EventType.CONTRACT_CREATION: "CREATE",
        EventType.ADD_LIQUIDITY: "ADD_LIQ",
        EventType.REMOVE_LIQUIDITY: "REM_LIQ",
        EventType.BUY: "BUY",
        EventType.SELL: "SELL",
    }.get(event.event_type, "???")

    flags = []
    if event.is_blacklisted:
        flags.append("BLACKLIST")
    if event.is_scam_bytecode:
        flags.append("SCAM_CODE")
    if event.has_dangerous_funcs:
        flags.append("DANGER")
    if event.is_lp_locked:
        flags.append("LP_LOCK")

    print(
        f"[{decision_str}] {event_str} score={event.final_score:.3f} "
        f"from={event.from_address[:10]}... "
        f"latency={event.latency_us:.1f}us "
        f"flags={','.join(flags) if flags else 'none'}"
    )


def main():
    parser = argparse.ArgumentParser(description="Lumina Tier 2 IPC Client")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    client = Tier2Client(verbose=args.verbose)

    # Handle Ctrl+C
    def signal_handler(sig, frame):
        print("\n[Tier2] Shutting down...")
        client.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Connect
    if not client.connect():
        print("[Tier2] Failed to connect to Tier 1")
        sys.exit(1)

    try:
        client.run(default_event_handler)
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
