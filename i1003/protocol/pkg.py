"""I1003 片上 NoC 的 64 位 PKG。

依据《I1003 芯片手册》PKG 格式：
  [63:62]VC [61:60]RGN [59:56]TYPE [55:54]S_X [53:52]S_Y [51:50]D_X [49:48]D_Y [47:32]ADDR [31:0]DATA
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class PkgType(IntEnum):
    READ_REG = 0x0
    READ_INST = 0x1
    READ_DATA = 0x2
    READ_NI = 0x3
    WRITE_REG = 0x4
    WRITE_INST = 0x5
    WRITE_DATA = 0x6
    WRITE_NI = 0x7


TYPE_LABELS = {
    PkgType.WRITE_REG: "写核寄存器", PkgType.READ_REG: "读核寄存器",
    PkgType.WRITE_INST: "写指令区", PkgType.READ_INST: "读指令区",
    PkgType.WRITE_DATA: "写数据区", PkgType.READ_DATA: "读数据区",
    PkgType.WRITE_NI: "写NI寄存器", PkgType.READ_NI: "读NI寄存器",
}
LABEL_TO_TYPE = {v: k for k, v in TYPE_LABELS.items()}
_RW = {0: "读", 1: "写", 2: "send out", 3: "SKP"}
_OBJ = {0: "核寄存器", 1: "指令区", 2: "数据区", 3: "NI寄存器"}

NODES = ["{}{}".format(x, y) for x in range(4) for y in range(4)]   # "xy"，第一位为 X


@dataclass(frozen=True)
class Route:
    """包头里的路由部分。默认源节点 30 是推断：片外口 3 在 NOC_30 + REGION_1。"""
    dx: int = 0
    dy: int = 0
    sx: int = 3
    sy: int = 0
    rgn: int = 0
    vc: int = 0

    @classmethod
    def from_names(cls, core: str = "00", src: str = "30", rgn: int = 0) -> "Route":
        return cls(int(core[0]), int(core[1]), int(src[0]), int(src[1]), int(rgn))

    @property
    def core(self) -> str:
        return "{}{}".format(self.dx, self.dy)

    def coord_byte(self) -> int:
        return ((self.sx & 3) << 6) | ((self.sy & 3) << 4) | ((self.dx & 3) << 2) | (self.dy & 3)


def encode(type_: int, addr: int, data: int, route: Route) -> bytes:
    b0 = ((route.vc & 3) << 6) | ((route.rgn & 3) << 4) | (int(type_) & 0xF)
    return (bytes([b0, route.coord_byte()]) + (addr & 0xFFFF).to_bytes(2, "big")
            + (data & 0xFFFFFFFF).to_bytes(4, "big"))


@dataclass(frozen=True)
class Pkg:
    vc: int
    rgn: int
    type: int
    sx: int
    sy: int
    dx: int
    dy: int
    addr: int
    data: int

    @classmethod
    def decode(cls, b: bytes) -> "Pkg":
        if len(b) != 8:
            raise ValueError("PKG 必须是 8 字节")
        return cls(b[0] >> 6, (b[0] >> 4) & 3, b[0] & 0xF, b[1] >> 6, (b[1] >> 4) & 3, (b[1] >> 2) & 3,
                   b[1] & 3, int.from_bytes(b[2:4], "big"), int.from_bytes(b[4:8], "big"))

    def route(self) -> Route:
        return Route(self.dx, self.dy, self.sx, self.sy, self.rgn, self.vc)

    def describe(self) -> str:
        return "RGN={} {}{} S=({},{}) D=({},{}) ADDR=0x{:04X} DATA=0x{:08X}".format(
            self.rgn, _RW[self.type >> 2], _OBJ[self.type & 3], self.sx, self.sy, self.dx, self.dy,
            self.addr, self.data)
