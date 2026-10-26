"""Loopback UDP protocol simulator, not an FPGA or RRAM execution model."""
from __future__ import annotations

import heapq
import socket
import threading
import time

from ..protocol import fpga
from ..protocol.pkg import Pkg, Route, encode
from .udp_link import UdpLink


PROFILES = {
    "标准（无芯片回包）": "standard",
    "寄存器读回（模拟）": "readback",
    "Ready 保持 0": "not_ready",
    "全部回包超时": "timeout",
    "回包延迟（800 ms）": "delay",
    "间歇丢包（每 2 包）": "loss",
}


class BoardSimulator:
    """Minimal 0..4 FPGA register and optional per-route PKG memory model.

    All sockets bind exclusively to loopback. Delays use a scheduler rather than
    sleeping in the receive loop. No chip execution or conduction is inferred.
    """
    def __init__(self, profile="standard"):
        if profile not in PROFILES.values():
            raise ValueError("未知模拟场景：" + str(profile))
        self.profile = profile
        self._stop = threading.Event()
        self._sock = None
        self._thread = None
        self._pending = []
        self._serial = 0
        self._reply_count = 0
        self._registers = {0: 0, 1: 1, 2: int(profile != "not_ready"), 3: 0, 4: 1}
        self._memory = {}
        self.received_frames = 0
        self.invalid_datagrams = 0

    def start(self):
        if self._sock is not None:
            raise RuntimeError("模拟板卡已启动")
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
            sock.bind(("127.0.0.1", 0))
            sock.settimeout(.02)
        except Exception:
            sock.close()
            raise
        self._sock = sock
        self._thread = threading.Thread(target=self._serve, args=(sock,), name="simulated-board", daemon=True)
        self._thread.start()
        return sock.getsockname()

    def close(self):
        self._stop.set()
        sock, self._sock = self._sock, None
        if sock is not None:
            sock.close()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(.3)

    def _handle(self, frame):
        write, addr, payload = fpga.parse_frame(frame)
        if not write:
            value = self._registers.get(addr)
            return [] if value is None else [value.to_bytes(8, "big")]
        if addr in (fpga.Addr.RX_ENABLE, fpga.Addr.BOOT_MODE):
            self._registers[addr] = int.from_bytes(payload, "big") & 1
            return []
        if addr != fpga.Addr.NOC_OUT:
            return []
        self._registers[3] = int.from_bytes(payload, "big")
        pkg = Pkg.decode(payload)
        # Ready=0 means this model does not accept PKGs into chip storage.
        if not self._registers[2] or pkg.type not in range(8):
            return []
        key = (pkg.rgn, pkg.dx, pkg.dy, pkg.type & 3, pkg.addr)
        if pkg.type >= 4:
            self._memory[key] = pkg.data
            return []
        if self.profile != "readback" or not self._registers[1]:
            return []
        route = Route(dx=pkg.sx, dy=pkg.sy, sx=pkg.dx, sy=pkg.dy, rgn=pkg.rgn, vc=pkg.vc)
        return [encode(8 | pkg.type, pkg.addr, self._memory.get(key, 0), route)]

    def _schedule(self, reply, peer):
        self._reply_count += 1
        if self.profile == "timeout" or (self.profile == "loss" and self._reply_count % 2 == 0):
            return
        self._serial += 1
        heapq.heappush(self._pending, (time.monotonic() + (.8 if self.profile == "delay" else 0),
                                      self._serial, reply, peer))

    def _serve(self, sock):
        while not self._stop.is_set():
            try:
                while self._pending and self._pending[0][0] <= time.monotonic():
                    _, _, reply, peer = heapq.heappop(self._pending)
                    sock.sendto(reply, peer)
                data, peer = sock.recvfrom(65536)
                frames = fpga.split_frames(data)
                # Validate the entire datagram before applying any writes.
                if not frames:
                    raise ValueError("空报文")
                for frame in frames:
                    fpga.parse_frame(frame)
                for frame in frames:
                    self.received_frames += 1
                    for reply in self._handle(frame):
                        self._schedule(reply, peer)
            except ValueError:
                self.invalid_datagrams += 1
            except socket.timeout:
                continue
            except OSError:
                break


class SimulatableUdpLink(UdpLink):
    """Real transport unless open_simulation() was explicitly selected."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._simulator = None
        self.simulation_profile = None

    @property
    def is_simulation(self):
        return self.simulation_profile is not None

    @property
    def endpoints(self):
        if self._sock is None:
            return None
        return (*self._sock.getsockname(), *self._remote)

    def open(self, *args, **kwargs):
        super().open(*args, **kwargs)
        self.simulation_profile = None

    def open_simulation(self, profile="standard"):
        if self.is_open:
            raise RuntimeError("请先断开连接")
        simulator = BoardSimulator(profile)
        try:
            remote = simulator.start()
            super().open("127.0.0.1", 0, *remote)
        except Exception:
            simulator.close()
            raise
        self._simulator = simulator
        self.simulation_profile = profile

    def close(self):
        super().close()
        simulator, self._simulator = self._simulator, None
        if simulator is not None:
            simulator.close()
