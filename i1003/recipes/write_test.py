"""RRAM 写测试配方：把"测哪些器件、怎么测"翻译成序列条目。

生成FPGA控制报文：配置reg[8]、写入指令（含STOP）、发送启动命令。
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from typing import Dict, List, Optional

from rram_console.hardware import RRAM_ARRAY

from ..model.items import Item, PkgItem, PollItem, ProgItem, VerifyItem, FpgaItem, FpgaProbeItem
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
    repeat: int = 1
    wwv_base: int = 254                 # reg[8] 默认值：00FF_00FE
    wwv_times: int = 255
    hold_s: float = 0.0                 # 兼容旧脚本；界面不再使用秒数反推次数
    pulse_ms: Optional[float] = None    # 兼容旧脚本；None 表示直接使用基时间和倍数
    verify_times: int = 0
    poll_after: bool = False
    check_reg8: bool = False
    check_inst: bool = False
    remind_4200: bool = False          # 兼容旧脚本参数；不再生成外部仪器提醒

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "WriteTestSpec":
        names = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in names})


SCENES: Dict[str, WriteTestSpec] = {
    "单器件长时间（I1000 实验台：4095 次）": WriteTestSpec(repeat=4095),
    "单器件只打一次": WriteTestSpec(repeat=1),
    "一行遍历 128 个器件（I1000 traversal）": WriteTestSpec(col_from=0, col_to=RRAM_ARRAY.columns - 1, repeat=1),
    "Forming 单器件（反向，4095 次）": WriteTestSpec(op=OP_FORMING, col_from=1, col_to=1, repeat=4095),
}

# Stable internal keys preserve old scripts/settings; these labels are shown in the UI.
SCENE_LABELS = {
    "单器件长时间（I1000 实验台：4095 次）": "单个器件 · 自定义重复次数",
    "单器件只打一次": "单个器件 · 操作 1 次",
    "一行遍历 128 个器件（I1000 traversal）": "一整行 · 每个器件操作 1 次",
    "Forming 单器件（反向，4095 次）": "单个器件 · 成形（Forming）",
}
SCENE_DESCRIPTIONS = {
    "单器件长时间（I1000 实验台：4095 次）": "对一个器件重复操作，次数由下方“重复次数”设置；切换到此模板时保留已填次数。",
    "单器件只打一次": "对一个器件执行一次操作；可在下方修改位置和操作类型。",
    "一行遍历 128 个器件（I1000 traversal）": "依次操作同一行的第 0～127 列，每个器件一次；可在下方修改目标行。",
    "Forming 单器件（反向，4095 次）": "载入成形实验参数，保留已填重复次数；使用 RESET 类型指令，外部电压由 4200 设置。",
}
VARIABLE_REPEAT_SCENES = frozenset(("单器件长时间（I1000 实验台：4095 次）", "Forming 单器件（反向，4095 次）"))


def scene_key(name: str) -> str:
    if name == "单个器件 · 重复 4095 次":  # Earlier display label.
        return "单器件长时间（I1000 实验台：4095 次）"
    if name in SCENES:
        return name
    for key, label in SCENE_LABELS.items():
        if name == label:
            return key
    raise ValueError("未知的测试模板：{}".format(name))


@dataclass
class Plan:
    items: List[Item]
    wwv: WwvConfig
    cells: int
    instructions: int
    first_word: int
    est_s: float
    summary: str

    @property
    def nominal_selection_s(self) -> float:
        """Configured WRITEB pulse time summed over all instructions, not wall time."""
        return self.instructions * self.wwv.cycles / isa.CHIP_CLK_HZ

    @property
    def per_cell_selection_s(self) -> float:
        return self.nominal_selection_s / self.cells

    def download_gap_budget_s(self, gap_s: float) -> float:
        """Explicit PC waits for WRITEB downloads plus STOP, excluding Ready/I/O."""
        if not math.isfinite(gap_s) or gap_s < 0:
            raise ValueError("发送间隔必须为非负有限数")
        return (self.instructions + 1) * gap_s


def plan(spec: WriteTestSpec) -> Plan:
    s = spec
    if not (0 <= s.pe <= 7 and 0 <= s.array <= 7):
        raise SpecError("PE 和阵列都是 0 到 7")
    try:
        RRAM_ARRAY.validate_cell(s.row_from, s.col_from)
        RRAM_ARRAY.validate_cell(s.row_to, s.col_to)
    except ValueError as exc:
        raise SpecError(str(exc))
    if s.row_to < s.row_from or s.col_to < s.col_from:
        raise SpecError("“到”不能小于“从”")
    if s.encoding not in CellEncoding.ALL:
        raise SpecError("未知的器件地址编码：{}".format(s.encoding))
    if s.hold_s < 0:
        raise SpecError("选通时间不能是负数")
    if s.repeat < 1 and s.hold_s == 0:
        raise SpecError("每个器件至少重复 1 次")
    try:
        if s.pulse_ms is not None:
            wwv = WwvConfig.from_pulse_ms(s.pulse_ms, timeout=s.verify_times, mode=0)
        else:
            if not (1 <= s.wwv_base <= 255 and 1 <= s.wwv_times <= 255):
                raise ValueError("基时间和时间倍数都要在 1 到 255 之间")
            wwv = WwvConfig(mode=0, times=s.wwv_times, timeout=s.verify_times, base=s.wwv_base)
    except ValueError as e:
        raise SpecError(str(e))

    cells = [(r, c) for r in range(s.row_from, s.row_to + 1) for c in range(s.col_from, s.col_to + 1)]
    pulse_s = wwv.cycles * (1 + s.verify_times) / isa.CHIP_CLK_HZ
    repeat = max(1, math.ceil(s.hold_s / pulse_s - 1e-9)) if s.hold_s > 0 else s.repeat
    n = len(cells) * repeat
    if n + 1 > isa.INST_DEPTH:
        raise SpecError("指令一共 {} 条，加停止指令超过指令区 {} 条。请减少重复次数或器件数；"
                        "当前每个器件最多重复 {} 次".format(n, isa.INST_DEPTH, (isa.INST_DEPTH - 1) // len(cells)))

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
    if s.poll_after:
        items.append(PollItem(desc="确认执行结束", timeout_s=max(10, est + 10)))

    summary = ("RRAM {} · {} · PE{} 阵列{} · {} · 每个重复 {} 次\n"
               "指令 {} 条 + 停止，占指令区 0x0000–0x{:04X}，首条指令字 {:08X}\n"
               "时钟 {:g} MHz · 基时间 {} × 时间倍数 {} = {} 周期\n"
               "reg[8] = {:08X} · 换算脉宽约 {:.3f} ms · 名义累计时间约 {:.3f} s").format(
        RRAM_ARRAY.label, opname, s.pe, s.array, where, repeat, n, n, segs[0][0], isa.CHIP_CLK_HZ / 1e6,
        wwv.base, wwv.times, wwv.cycles, wwv.word, wwv.pulse_ms, est)
    return Plan(items, wwv, len(cells), n, segs[0][0], est, summary)


def path_check(wwv: WwvConfig = None) -> List[Item]:
    """Read board state and verify its command staging; never write RRAM."""
    return [FpgaItem(desc="查询 Ready", addr=fpga.Addr.CHIP_READY),
            FpgaItem(desc="读取 FPGA 接收使能", addr=fpga.Addr.RX_ENABLE),
            FpgaItem(desc="读取 boot_mode", addr=fpga.Addr.BOOT_MODE),
            FpgaProbeItem(desc="FPGA发送寄存器自检")]


def readback_check(wwv: WwvConfig = None) -> List[Item]:
    """Optional register check for hardware with a supported chip reply path."""
    wwv = wwv or WwvConfig()
    return [FpgaItem(desc="查询 Ready", addr=fpga.Addr.CHIP_READY),
            PkgItem(desc="写 reg[8] = {:08X}".format(wwv.word), type=PkgType.WRITE_REG, addr=isa.REG_WWV, data=wwv.word),
            VerifyItem(desc="核对 reg[8]", type=PkgType.READ_REG, addr=isa.REG_WWV, expect=wwv.word)]


def scene(name: str) -> WriteTestSpec:
    if name == "单器件持续选通 8 s（配合 4200 测量）":
        # 仅为旧脚本保留旧场景；新的界面场景只使用寄存器参数与次数。
        return WriteTestSpec(hold_s=8.0, pulse_ms=1.0)
    return replace(SCENES[scene_key(name)])
