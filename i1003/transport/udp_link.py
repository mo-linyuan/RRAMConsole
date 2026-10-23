"""UDP 收发。只负责字节进出和"请求-回包"配对，不涉及界面和业务流程。

回包分三类，通过 on_receive(kind, data) 交给上层：
  "bit"  0001/0002/0004 这类单比特寄存器的回包
  "fpga" 0003 读回 FPGA 存值
  "chip" 其他：没有对应请求、自己到达的包，通常来自芯片
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Callable, Optional

from ..protocol import fpga

SendHook = Callable[[bytes, str, bool], None]          # (数据, 备注, 是否 Ready 查询)
ReceiveHook = Callable[[str, bytes], None]             # (类别, 数据)


class UdpLink:
    def __init__(self, on_send: Optional[SendHook] = None, on_receive: Optional[ReceiveHook] = None):
        self.on_send = on_send or (lambda *a: None)
        self.on_receive = on_receive or (lambda *a: None)
        self._sock: Optional[socket.socket] = None
        self._remote = None
        self._running = False
        self._cv = threading.Condition()
        self._waiting: Optional[str] = None
        self._result: Optional[bytes] = None

    # ---------------------------------------------------------------- 连接
    @property
    def is_open(self) -> bool:
        return self._sock is not None

    def open(self, local_ip: str = fpga.PC_IP, local_port: int = fpga.PORT,
             remote_ip: str = fpga.BOARD_IP, remote_port: int = fpga.PORT) -> None:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind((local_ip, local_port))
        s.settimeout(0.2)
        self._sock, self._remote, self._running = s, (remote_ip, remote_port), True
        threading.Thread(target=self._rx_loop, name="udp-rx", daemon=True).start()

    def close(self) -> None:
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None

    # ---------------------------------------------------------------- 发送
    def send(self, data: bytes, note: str = "", quiet: bool = False) -> None:
        if not self._sock:
            raise RuntimeError("UDP 未连接")
        self._sock.sendto(data, self._remote)
        self.on_send(data, note, quiet)

    def request(self, expect: str, data: bytes, timeout: float, note: str = "", quiet: bool = False) -> Optional[bytes]:
        """发送并等待一个指定类别（bit / fpga / chip）的回包，超时返回 None。"""
        with self._cv:
            self._waiting, self._result = expect, None
        self.send(data, note, quiet)
        with self._cv:
            self._cv.wait_for(lambda: self._waiting is None, timeout)
            r, self._waiting = self._result, None
        return r

    def read_bit(self, addr: int, note: str = "", quiet: bool = False, timeout: float = 0.3) -> Optional[int]:
        r = self.request("bit", fpga.read_frame(addr), timeout, note, quiet)
        return None if r is None else r[7] & 1

    def wait_chip_ready(self, max_wait_s: float = 1.0) -> Optional[bool]:
        """反复查 0002，直到芯片 Ready=1。返回 True；一直为 0 返回 False；没有回包返回 None。"""
        t_end = time.time() + max_wait_s
        last = None
        while True:
            last = self.read_bit(fpga.Addr.CHIP_READY, "查询 Ready", quiet=True)
            if last == 1:
                return True
            if time.time() >= t_end:
                return None if last is None else False
            time.sleep(0.005)

    # ---------------------------------------------------------------- 接收
    def _rx_loop(self) -> None:
        while self._running:
            try:
                data, _ = self._sock.recvfrom(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            self.on_receive(self._classify(data), data)

    def _classify(self, d: bytes) -> str:
        with self._cv:
            w = self._waiting
            if w == "bit" and fpga.looks_like_bit_reply(d):
                kind = "bit"
            elif w == "fpga" and len(d) == fpga.REPLY_LEN:
                kind = "fpga"
            elif w == "chip":
                kind = "chip"
            else:
                return "chip"
            self._result, self._waiting = d, None
            self._cv.notify_all()
            return kind
