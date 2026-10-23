"""模拟板卡（FPGA + 一个会回包的芯片），用于离线调试界面和跑测试。

    python -m tools.fake_board              # 在 127.0.0.1:9080 监听，回包发往 127.0.0.1:9081
调试台里把本机设成 127.0.0.1:9081、板卡设成 127.0.0.1:9080 即可连上。

模拟的行为：
  FPGA：0001/0002/0004 回单比特，0003 回最后一次发往芯片的 8 字节，8003 把 PKG 交给芯片；一个包里可以有多帧。
  芯片：写/读核寄存器和指令区；读请求回一个 send out 包；写 reg[0]=1 后立刻置结束位 0x80。
注意：这是按手册推测的理想行为，真实芯片的回包格式以实测为准。
"""

from __future__ import annotations

import argparse
import socket
import threading
from typing import Dict, Tuple

from i1003.protocol import fpga
from i1003.protocol.pkg import Pkg, PkgType


class FakeBoard:
    def __init__(self, listen: Tuple[str, int] = ("127.0.0.1", 9080), reply_to: Tuple[str, int] = ("127.0.0.1", 9081),
                 chip_replies: bool = True):
        self.listen, self.reply_to, self.chip_replies = listen, reply_to, chip_replies
        self.regs: Dict[int, int] = {}
        self.inst: Dict[int, int] = {}
        self.last_out = bytes(8)
        self.frames_to_chip = 0
        self._sock = None

    def start(self) -> "FakeBoard":
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(self.listen)
        threading.Thread(target=self._loop, daemon=True).start()
        return self

    def stop(self):
        if self._sock:
            self._sock.close()

    def _reply(self, b: bytes):
        self._sock.sendto(b, self.reply_to)

    def _loop(self):
        while True:
            try:
                d, _ = self._sock.recvfrom(65536)
            except OSError:
                return
            for k in range(0, len(d) - len(d) % 12, 12):
                try:
                    write, addr, data = fpga.parse_frame(d[k:k + 12])
                except ValueError:
                    continue
                if not write:
                    if addr in (fpga.Addr.RX_ENABLE, fpga.Addr.CHIP_READY, fpga.Addr.BOOT_MODE):
                        self._reply(bytes(7) + b"\x01")
                    elif addr == fpga.Addr.NOC_OUT:
                        self._reply(self.last_out)
                elif addr == fpga.Addr.NOC_OUT:
                    self.last_out = data
                    self.frames_to_chip += 1
                    self._chip(Pkg.decode(data))

    def _chip(self, p: Pkg):
        if p.type == PkgType.WRITE_REG:
            self.regs[p.addr] = p.data
            if p.addr == 0 and p.data & 1:
                self.regs[0] = 0x80
        elif p.type == PkgType.WRITE_INST:
            self.inst[p.addr] = p.data
        elif p.type in (PkgType.READ_REG, PkgType.READ_INST) and self.chip_replies:
            v = (self.regs if p.type == PkgType.READ_REG else self.inst).get(p.addr, 0)
            b0 = (2 << 4) | 0x8 | (p.type & 3)               # RGN=2(offchip)，send out
            b1 = (p.dx << 6) | (p.dy << 4) | (p.sx << 2) | p.sy
            self._reply(bytes([b0, b1]) + p.addr.to_bytes(2, "big") + v.to_bytes(4, "big"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9080)
    ap.add_argument("--reply-port", type=int, default=9081)
    ap.add_argument("--no-chip-reply", action="store_true", help="模拟现在真实板卡的情况：芯片不回包")
    a = ap.parse_args()
    FakeBoard(("127.0.0.1", a.port), ("127.0.0.1", a.reply_port), not a.no_chip_reply).start()
    print("模拟板卡运行中：监听 127.0.0.1:{}，回包发往 127.0.0.1:{}。Ctrl+C 退出".format(a.port, a.reply_port))
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
