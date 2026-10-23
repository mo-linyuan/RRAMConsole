"""序列条目。每种条目知道自己怎么展开成帧、怎么序列化，不关心怎么发送。

芯片相关的条目只存 TYPE、地址、数据，路由（目标核等）在展开时传入，所以同一个序列换核就能复用。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Dict, List, Optional, Tuple, Type

from ..protocol import fpga, isa
from ..protocol.pkg import PkgType, Route, encode

Frame = Tuple[bytes, bool]          # (帧, 是否发往芯片)


def hexs(b: bytes) -> str:
    return " ".join("{:02X}".format(x) for x in b)


@dataclass
class Item:
    desc: str = ""
    meta: Dict = field(default_factory=dict)      # 界面用：记录由哪个模板、什么参数生成

    kind = "base"

    def validate(self) -> None:
        pass

    def frames(self, route: Route, limit: Optional[int] = None) -> List[Frame]:
        return []

    def count(self) -> int:
        return 1

    def summary(self, route: Route) -> str:
        f = self.frames(route, 1)
        return hexs(f[0][0]) if f else ""

    def is_start(self) -> bool:
        return False

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["kind"] = self.kind
        return d


@dataclass
class FpgaItem(Item):
    """读写 FPGA 自己的寄存器（0001、0002、0003、0004…）。"""
    addr: int = 2
    write: bool = False
    data: int = 0
    kind = "fpga"

    def validate(self):
        if type(self.addr) is not int or not 0 <= self.addr <= 0x7FFF:
            raise ValueError("FPGA 地址必须为 0～32767")
        if type(self.data) is not int or not 0 <= self.data < 2**64:
            raise ValueError("FPGA 数据必须为 64 位无符号整数")
        if self.write and self.addr in fpga.FORBIDDEN_WRITES:
            raise ValueError("该 FPGA 地址不允许写")

    def frames(self, route, limit=None):
        self.validate()
        f = fpga.write_frame(self.addr, self.data) if self.write else fpga.read_frame(self.addr)
        return [(f, False)]


@dataclass
class PkgItem(Item):
    """一个发给芯片的 PKG。"""
    type: int = PkgType.READ_REG
    addr: int = 0
    data: int = 0
    kind = "pkg"

    def validate(self):
        if not isinstance(self.type, int) or not 0 <= self.type <= 7:
            raise ValueError("芯片命令 TYPE 必须为 0～7")
        if type(self.addr) is not int or not 0 <= self.addr <= 0xFFFF:
            raise ValueError("芯片地址必须为 16 位无符号整数")
        if type(self.data) is not int or not 0 <= self.data <= 0xFFFFFFFF:
            raise ValueError("芯片数据必须为 32 位无符号整数")
        if self.type == PkgType.WRITE_INST:
            if type(self.addr) is not int or not 0 <= self.addr < isa.INST_DEPTH:
                raise ValueError("指令地址必须为 0～{}".format(isa.INST_DEPTH - 1))
            isa.validate_instruction(self.data)

    def frames(self, route, limit=None):
        self.validate()
        return [(fpga.chip_frame(encode(self.type, self.addr, self.data, route)), True)]

    def is_start(self):
        return self.type == PkgType.WRITE_REG and self.addr == isa.REG_STATUS and bool(self.data & isa.START_VALUE)


@dataclass
class ProgItem(Item):
    """连续写指令区：segs = [[指令字, 重复次数], ...]，从 start 起逐条地址加 1，可在末尾加停止指令。
    相当于 I1000 的 long_tx（单段）和 traversal（多段）。"""
    start: int = 0
    segs: List[List[int]] = field(default_factory=list)
    stop: bool = True
    kind = "prog"

    def validate(self):
        if type(self.start) is not int or not 0 <= self.start < isa.INST_DEPTH:
            raise ValueError("起始指令地址必须为 0～{}".format(isa.INST_DEPTH - 1))
        count = 1 if self.stop else 0
        for word, repeat in self.segs:
            isa.validate_instruction(word)
            if type(repeat) is not int or repeat < 1:
                raise ValueError("指令重复次数必须为正整数")
            count += repeat
        if self.start + count > isa.INST_DEPTH:
            raise ValueError("指令总数超过指令区容量 {} 条".format(isa.INST_DEPTH))

    def words(self, limit=None) -> List[int]:
        self.validate()
        out: List[int] = []
        for w, c in self.segs:
            out.extend([w] * c)
            if limit is not None and len(out) >= limit:
                return out[:limit]
        if self.stop:
            out.append(isa.STOP_INST)
        return out if limit is None else out[:limit]

    def frames(self, route, limit=None):
        return [(fpga.chip_frame(encode(PkgType.WRITE_INST, self.start + i, w, route)), True)
                for i, w in enumerate(self.words(limit))]

    def count(self):
        return sum(c for _, c in self.segs) + (1 if self.stop else 0)

    def summary(self, route):
        return "{} ...  共 {} 条".format(hexs(self.frames(route, 1)[0][0]), self.count())


@dataclass
class WaitItem(Item):
    ms: int = 1000
    notify: str = ""          # 开始等待时弹窗提示的内容，空则不弹
    kind = "wait"

    def validate(self):
        if not isinstance(self.ms, (int, float)) or not math.isfinite(self.ms) or self.ms < 0:
            raise ValueError("等待时间必须为非负有限数")

    def count(self):
        return 0

    def summary(self, route):
        return "等待 {:.1f} s".format(self.ms / 1000)


@dataclass
class VerifyItem(Item):
    """Read and compare chip data; timeout or mismatch stops the task."""
    type: int = PkgType.READ_REG
    addr: int = 0
    expect: int = 0
    kind = "verify"

    def validate(self):
        PkgItem(type=self.type, addr=self.addr, data=self.expect).validate()
        if self.type not in range(4):
            raise ValueError("核对操作必须使用读命令")

    def frames(self, route, limit=None):
        return [(fpga.chip_frame(encode(self.type, self.addr, 0, route)), True)]


@dataclass
class PollItem(Item):
    """反复读 reg[0]，直到出现结束位或超时。"""
    timeout_s: float = 10.0
    kind = "poll"

    def validate(self):
        if not isinstance(self.timeout_s, (int, float)) or not math.isfinite(self.timeout_s) or self.timeout_s <= 0:
            raise ValueError("查询超时必须为正有限数")

    def frames(self, route, limit=None):
        return [(fpga.chip_frame(encode(PkgType.READ_REG, isa.REG_STATUS, 0, route)), True)]

    def summary(self, route):
        return "{}   反复读，最长 {:.0f} s".format(super().summary(route), self.timeout_s)


@dataclass
class RawItem(Item):
    """原样发送的字节，可以是一帧或多帧。"""
    hex: str = ""
    kind = "raw"

    def validate(self):
        if not bytes.fromhex(self.hex):
            raise ValueError("原始报文不能为空")

    def frames(self, route, limit=None):
        b = bytes.fromhex(self.hex)
        return [(b, fpga.is_chip_frame(b))]


KINDS: Dict[str, Type[Item]] = {c.kind: c for c in (FpgaItem, PkgItem, ProgItem, WaitItem, VerifyItem, PollItem, RawItem)}
BULK_KINDS = (ProgItem,)


def from_dict(d: Dict) -> Item:
    d = dict(d)
    kind = d.pop("kind")
    d.pop("_st", None)
    if kind == "batch":                 # 兼容旧版单文件工具导出的序列
        kind = "prog"
        d = {"desc": d.get("desc", ""), "start": d["start"], "segs": [[d["data"], d["count"]]], "stop": d["stop"]}
    if kind == "fpga" and "ctrl" in d:  # 旧版：ctrl + 16 位十六进制数据
        ctrl = d.pop("ctrl")
        d.update(addr=ctrl & 0x7FFF, write=bool(ctrl & 0x8000), data=int(d.get("data", "0"), 16))
    cls = KINDS[kind]
    names = set(cls.__dataclass_fields__)
    item = cls(**{k: v for k, v in d.items() if k in names})
    item.validate()
    return item


def total_frames(items: List[Item]) -> int:
    return sum(it.count() for it in items)
