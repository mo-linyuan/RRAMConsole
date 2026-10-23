"""PC 与板卡 FPGA 之间的 UDP 帧协议。

依据同事工程 I1003_NOC_1012：decode.v（帧解析）、common_reg.sv（寄存器）、ethernet_top.sv（IP/端口）。

帧格式（12 字节）：55 D5 | 读写+地址 16 位（最高位 1 为写）| 64 位数据
FPGA 每收到一个读请求，回 8 字节数据；芯片从 Noc_o_3 发出的每个包，也以 8 字节 UDP 包回传。
"""

from __future__ import annotations

from enum import IntEnum
from typing import List, Tuple

HEAD = b"\x55\xD5"
FRAME_LEN = 12
REPLY_LEN = 8
WRITE_FLAG = 0x8000

BOARD_IP = "192.168.1.10"     # SRC_IP_ADDR
PC_IP = "192.168.1.9"         # DES_IP_ADDR，FPGA 的回包固定发往这里
PORT = 8080                   # UDP_SRC_PORT / UDP_DES_PORT
MAX_FRAMES_PER_PACKET = 100   # 一个 UDP 包里放多帧时的上限（单包 1472 字节内）


class Addr(IntEnum):
    TEST = 0          # 写 bit63 打开以太网测速模式，会持续灌数据，禁止写
    RX_ENABLE = 1     # noc_in_ready：FPGA 是否接收芯片输出，复位 1
    CHIP_READY = 2    # 只读，芯片 pad_Noc_i_3_Ready
    NOC_OUT = 3       # 写：发 64 位 PKG 给芯片；读：FPGA 最后发出的 PKG
    BOOT_MODE = 4     # 芯片 boot_mode 引脚，复位 1


ADDR_LABELS = {
    Addr.TEST: "测速模式",
    Addr.RX_ENABLE: "接收使能",
    Addr.CHIP_READY: "芯片 Ready",
    Addr.NOC_OUT: "发往芯片的 PKG",
    Addr.BOOT_MODE: "boot_mode",
}

FORBIDDEN_WRITES = {Addr.TEST, Addr.CHIP_READY}


def frame(addr: int, data: int = 0, write: bool = False) -> bytes:
    ctrl = (WRITE_FLAG if write else 0) | (addr & 0x7FFF)
    return HEAD + ctrl.to_bytes(2, "big") + (data & (2 ** 64 - 1)).to_bytes(8, "big")


def read_frame(addr: int) -> bytes:
    return frame(addr, 0, False)


def write_frame(addr: int, data: int) -> bytes:
    if addr in FORBIDDEN_WRITES:
        raise ValueError("FPGA 地址 {} 不允许写".format(addr))
    return frame(addr, data, True)


def chip_frame(pkg8: bytes) -> bytes:
    """把 8 字节 PKG 包装成发往芯片的帧（写地址 3）。"""
    assert len(pkg8) == 8
    return HEAD + (WRITE_FLAG | Addr.NOC_OUT).to_bytes(2, "big") + pkg8


def parse_frame(b: bytes) -> Tuple[bool, int, bytes]:
    """返回 (是否写, 地址, 8 字节数据)。不是合法帧时抛 ValueError。"""
    if len(b) != FRAME_LEN or b[:2] != HEAD:
        raise ValueError("不是 12 字节、以 55 D5 开头的帧")
    ctrl = int.from_bytes(b[2:4], "big")
    return bool(ctrl & WRITE_FLAG), ctrl & 0x7FFF, b[4:]


def is_chip_frame(b: bytes) -> bool:
    try:
        w, a, _ = parse_frame(b)
    except ValueError:
        return False
    return w and a == Addr.NOC_OUT


def split_frames(b: bytes) -> List[bytes]:
    """把连续的多帧切开；长度不是 12 的整数倍时抛 ValueError。"""
    if len(b) % FRAME_LEN:
        raise ValueError("长度 {} 不是 12 的整数倍".format(len(b)))
    return [b[i:i + FRAME_LEN] for i in range(0, len(b), FRAME_LEN)]


def looks_like_bit_reply(d: bytes) -> bool:
    """0001/0002/0004 这类单比特寄存器的回包：前 7 字节全 0，最后一字节 0 或 1。"""
    return len(d) == REPLY_LEN and d[:7] == bytes(7) and d[7] in (0, 1)
