"""RRAM 写测试配方：把"测哪些器件、怎么测"翻译成序列条目。

对应 I1000 实验台流程：配 reg[8] → 读回 → 写指令（long_tx / traversal）→ 停止指令 → 启动 → 4200 run → 读 reg[0]。
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from typing import Dict, List

from ..model.items import Item, PkgItem, PollItem, ProgItem, VerifyItem, WaitItem, FpgaItem
from ..protocol import fpga, isa
from ..protocol.isa import CellEncoding, WwvConfig
from ..protocol.pkg import PkgType


class SpecError(ValueError):
    """填写不合理，消息是给人看的中文。"""


OP_SET = "SET（写1）"
OP_RESET = "RESET（写0）"
OP_FORMING = "Forming（反向，RESET 类型）"
OPS = (OP_SET, OP_RESET, OP_FORMING)


@dataclass
class WriteTestSpec:
    op: str = OP_SET
    pe: int = 0
    array: int = 0
    row_from: int = 0
    row_to: int = 0
    col_from: int = 2
    col_to: int = 2
    encoding: str = CellEncoding.ROW_X128
    repeat: int = 4095
    hold_s: float = 0.0                 # 每个器件的选通时间（秒）。大于 0 时按它算重复次数，忽略 repeat
    pulse_ms: float = 1.0               # 默认 1 ms；I1000 实验台用的是 6.477 ms（00FF_00FE）
    verify_times: int = 0
    poll_after: bool = True
    check_reg8: bool = True
    check_inst: bool = True
    remind_4200: bool = True

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "WriteTestSpec":
        names = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in names})


SCENES: Dict[str, WriteTestSpec] = {
    "单器件持续选通 8 s（配合 4200 测量）": WriteTestSpec(hold_s=8.0),
    "单器件长时间（I1000 实验台：4095 次）": WriteTestSpec(),
    "单器件只打一次": WriteTestSpec(repeat=1),
    "一行遍历 128 个器件（I1000 traversal）": WriteTestSpec(col_from=0, col_to=127, repeat=1),
    "Forming 单器件（反向，4095 次）": WriteTestSpec(op=OP_FORMING, col_from=1, col_to=1),
}


@dataclass
class Plan:
    items: List[Item]
    wwv: WwvConfig
    cells: int
    instructions: int
    first_word: int
    est_s: float
    summary: str


def plan(spec: WriteTestSpec) -> Plan:
    s = spec
    if not (0 <= s.pe <= 7 and 0 <= s.array <= 7):
        raise SpecError("PE 和阵列都是 0 到 7")
    if s.row_to < s.row_from or s.col_to < s.col_from:
        raise SpecError("“到”不能小于“从”")
    if not (0 <= s.row_from and s.row_to <= 127 and 0 <= s.col_from and s.col_to <= 127):
        raise SpecError("行、列都是 0 到 127")
    if s.hold_s < 0:
        raise SpecError("选通时间不能是负数")
    if s.repeat < 1 and s.hold_s == 0:
        raise SpecError("每个器件至少重复 1 次")
    try:
        wwv = WwvConfig.from_pulse_ms(s.pulse_ms, timeout=s.verify_times, mode=0)
    except ValueError as e:
        raise SpecError(str(e))

    cells = [(r, c) for r in range(s.row_from, s.row_to + 1) for c in range(s.col_from, s.col_to + 1)]
    pulse_s = wwv.cycles * (1 + s.verify_times) / isa.CHIP_CLK_HZ
    repeat = max(1, math.ceil(s.hold_s / pulse_s - 1e-9)) if s.hold_s > 0 else s.repeat
    max_hold = (isa.INST_DEPTH - 1) // len(cells) * pulse_s
    n = len(cells) * repeat
    if n + 1 > isa.INST_DEPTH:
        raise SpecError("指令一共 {} 条，加停止指令超过指令区 {} 条。当前脉宽下每个器件最多选通 {:.2f} s，"
                        "要更久就加大脉宽（最大约 6.5 ms）或减少器件数".format(n, isa.INST_DEPTH, max_hold))

    set_ = s.op == OP_SET
    segs = [[isa.writeb(s.pe, set_, s.array, CellEncoding.encode(s.encoding, r, c)), repeat] for r, c in cells]
    est = n * pulse_s
    opname = s.op.split("（")[0]
    where = ("第{}行第{}列".format(s.row_from, s.col_from) if len(cells) == 1 else
             "行{}-{} 列{}-{}，共 {} 个器件".format(s.row_from, s.row_to, s.col_from, s.col_to, len(cells)))

    items: List[Item] = [PkgItem(desc="写 reg[8] = {:08X}".format(wwv.word), type=PkgType.WRITE_REG,
                                 addr=isa.REG_WWV, data=wwv.word)]
    if s.check_reg8:
        items.append(VerifyItem(desc="核对 reg[8]", type=PkgType.READ_REG, addr=isa.REG_WWV, expect=wwv.word))
    items.append(ProgItem(desc="{} PE{} 阵列{} {} ×{}".format(opname, s.pe, s.array, where, repeat),
                          start=0, segs=segs, stop=True))
    if s.check_inst:
        items.append(VerifyItem(desc="核对指令[0000]", type=PkgType.READ_INST, addr=0, expect=segs[0][0]))
    items.append(PkgItem(desc="启动 reg[0]=1", type=PkgType.WRITE_REG, addr=isa.REG_STATUS, data=isa.START_VALUE))
    items.append(WaitItem(desc="芯片工作中", ms=int(est * 1000) + 300,
                          notify=("芯片已启动，预计工作 {:.1f} s。需要的话现在去 4200 点 run。".format(est)
                                  if s.remind_4200 else "")))
    if s.poll_after:
        items.append(PollItem(desc="确认执行结束", timeout_s=10))

    summary = ("{} · PE{} 阵列{} · {} · 每个重复 {} 次，每个器件选通约 {:.2f} s\n"
               "指令 {} 条 + 停止，占指令区 0x0000–0x{:04X}，首条指令字 {:08X}\n"
               "脉宽 {} × {} = {} 周期 ≈ {:.3f} ms（reg[8] = {:08X}），预计芯片工作 {:.1f} s，"
               "此脉宽下每个器件最长可选通 {:.1f} s").format(
        opname, s.pe, s.array, where, repeat, repeat * pulse_s, n, n, segs[0][0], wwv.base, wwv.times, wwv.cycles,
        wwv.pulse_ms, wwv.word, est, max_hold)
    if s.op == OP_FORMING:
        summary += "\nForming 按 I1000 的做法用 RESET 类型指令，电压（SL 3.3V、WL 1.8V、BL 接地）由 4200 提供"
    return Plan(items, wwv, len(cells), n, segs[0][0], est, summary)


def path_check(wwv: WwvConfig = None) -> List[Item]:
    """只检查通路：查 Ready → 写 reg[8] → 读回核对。不碰 RRAM。"""
    wwv = wwv or WwvConfig.from_pulse_ms(1.0)
    return [FpgaItem(desc="查询 Ready", addr=fpga.Addr.CHIP_READY),
            PkgItem(desc="写 reg[8] = {:08X}".format(wwv.word), type=PkgType.WRITE_REG, addr=isa.REG_WWV, data=wwv.word),
            VerifyItem(desc="核对 reg[8]", type=PkgType.READ_REG, addr=isa.REG_WWV, expect=wwv.word)]


def scene(name: str) -> WriteTestSpec:
    return replace(SCENES[name])
