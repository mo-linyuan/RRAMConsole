"""Serialized, cancellable UDP requests. No transaction IDs exist on the wire."""
from __future__ import annotations
import socket
import threading
import time
from ..protocol import fpga
from ..protocol.pkg import Pkg


class UdpLink:
    def __init__(self, on_send=None, on_receive=None):
        self.on_send = on_send or (lambda *a: None)
        self.on_receive = on_receive or (lambda *a: None)
        self._sock = self._remote = self._thread = None
        self._cv = threading.Condition()
        self._requests = threading.Lock()
        self._waiting = self._matcher = self._result = None
        self._closed = threading.Event()
        self._closed.set()

    @property
    def is_open(self):
        return self._sock is not None

    def open(self, local_ip=fpga.PC_IP, local_port=fpga.PORT,
             remote_ip=fpga.BOARD_IP, remote_port=fpga.PORT):
        if self.is_open:
            raise RuntimeError("UDP 已打开，请先断开连接")
        remote = (socket.gethostbyname(remote_ip), remote_port)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind((local_ip, local_port))
            sock.settimeout(0.1)
        except Exception:
            sock.close()
            raise
        self._sock, self._remote = sock, remote
        self._closed = threading.Event()
        self._thread = threading.Thread(target=self._rx_loop, args=(sock, remote, self._closed),
                                        name="udp-rx", daemon=True)
        self._thread.start()

    def cancel_pending(self):
        with self._cv:
            self._waiting, self._result = None, None
            self._cv.notify_all()

    def close(self):
        self._closed.set()
        sock, self._sock = self._sock, None
        self.cancel_pending()
        if sock is not None:
            sock.close()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=0.3)

    def send(self, data, note="", quiet=False):
        sock = self._sock
        if sock is None:
            raise RuntimeError("UDP 未连接")
        sock.sendto(data, self._remote)
        self.on_send(data, note, quiet)

    @staticmethod
    def _reply_matcher(expect, request):
        if expect == "bit":
            return fpga.looks_like_bit_reply
        if expect == "fpga":
            return lambda data: len(data) == fpga.REPLY_LEN
        if expect != "chip":
            raise ValueError("未知回包类别：" + expect)
        write, addr, payload = fpga.parse_frame(request)
        if not write or addr != fpga.Addr.NOC_OUT:
            raise ValueError("芯片读请求必须封装为写 FPGA 地址 3")
        sent = Pkg.decode(payload)
        if not 0 <= sent.type <= 3:
            raise ValueError("仅芯片读命令可以等待读回包")

        def matches(data):
            if len(data) != fpga.REPLY_LEN:
                return False
            got = Pkg.decode(data)
            return (got.type == (8 | sent.type) and got.addr == sent.addr
                    and (got.sx, got.sy, got.dx, got.dy) == (sent.dx, sent.dy, sent.sx, sent.sy))
        return matches

    def request(self, expect, data, timeout, note="", quiet=False, cancel_event=None, reply_filter=None):
        base_matcher = self._reply_matcher(expect, data)
        matcher = lambda reply: base_matcher(reply) and (reply_filter is None or reply_filter(reply))
        with self._requests:
            if cancel_event is not None and cancel_event.is_set():
                return None
            with self._cv:
                self._waiting, self._matcher, self._result = expect, matcher, None
            try:
                self.send(data, note, quiet)
                end = time.monotonic() + max(0, timeout)
                with self._cv:
                    while self._waiting is not None:
                        if self._closed.is_set() or (cancel_event is not None and cancel_event.is_set()):
                            return None
                        left = end - time.monotonic()
                        if left <= 0:
                            return None
                        self._cv.wait(min(left, 0.05))
                    return self._result
            finally:
                with self._cv:
                    self._waiting = self._matcher = self._result = None

    def read_bit(self, addr, note="", quiet=False, timeout=0.3, cancel_event=None):
        data = self.request("bit", fpga.read_frame(addr), timeout, note, quiet, cancel_event)
        return None if data is None else data[7] & 1

    def wait_chip_ready(self, max_wait_s=1.0, cancel_event=None):
        end, last = time.monotonic() + max_wait_s, None
        while time.monotonic() < end:
            if cancel_event is not None and cancel_event.is_set():
                return None
            last = self.read_bit(fpga.Addr.CHIP_READY, "查询 Ready", quiet=True,
                                 timeout=min(0.3, max(0, end - time.monotonic())), cancel_event=cancel_event)
            if last == 1:
                return True
            if self._closed.wait(0.005):
                return None
        return None if last is None else False

    def _rx_loop(self, sock, remote, closed):
        while not closed.is_set():
            try:
                data, peer = sock.recvfrom(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            if peer != remote:
                self.on_receive("foreign", data)
                continue
            self.on_receive(self._classify(data), data)

    def _classify(self, data):
        with self._cv:
            if self._waiting is not None and self._matcher(data):
                kind = self._waiting
                self._result, self._waiting = data, None
                self._cv.notify_all()
                return kind
        return "unmatched"
