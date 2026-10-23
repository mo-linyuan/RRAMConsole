"""报文模板：每个模板是一张小表单，填完生成一个序列条目。只描述数据，不含界面代码。

字段：Field(键, 标签, 类型, 默认值, 选项)；类型 int（选项为范围）/ hex / count / choice
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from ..model.items import FpgaItem, Item, PkgItem, PollItem, ProgItem, RawItem, WaitItem
from ..protocol import fpga, isa
from ..protocol.pkg import LABEL_TO_TYPE, TYPE_LABELS, PkgType


@dataclass
class Field:
    key: str
    label: str
    kind: str
    default: object
    options: object = None


@dataclass
class Template:
    name: str
    group: str
    fields: List[Field]
    build: Callable[[Dict[str, str]], Item]
    hint: str = ""
    hint_fn: Optional[Callable[[Dict[str, str]], str]] = None

    def defaults(self) -> Dict[str, str]:
        return {f.key: str(f.default) for f in self.fields}

    def make(self, values: Optional[Dict[str, str]] = None) -> Item:
        v = self.defaults()
        v.update(values or {})
        it = self.build(v)
        it.meta = {"tpl": self.name, "vals": v}
        return it

    def describe(self, values: Dict[str, str]) -> str:
        parts = []
        if self.hint_fn:
            parts.append(self.hint_fn(values))
        if self.hint:
            parts.append(self.hint)
        return "\n".join(parts)


def hex_int(s) -> int:
    s = str(s).strip().replace("_", "").replace(" ", "")
    return int(s[2:] if s.lower().startswith("0x") else s, 16)


def count_int(s) -> int:
    s = str(s).strip().replace("_", "")
    return int(s, 16) if s.lower().startswith("0x") else int(s, 10)


REG_CHOICES = ["{} {}".format(n, isa.REG_NAMES.get(n, "")).strip() for n in (0, 4, 5, 6, 7, 8, 9, 10)] + \
              [str(n) for n in range(11, 20)]
OPS = ["SET（写1）", "RESET（写0）"]


def reg_no(s: str) -> int:
    return int(str(s).split()[0])


def _wb(v) -> int:
    return isa.writeb(int(v["pe"]), v["op"].startswith("SET"), int(v["idx"]), hex_int(v["dev"]))


def _wwv(v) -> isa.WwvConfig:
    return isa.WwvConfig(0 if v["mode"].startswith("单") else 1, int(v["times"]), int(v["timeout"]), int(v["base"]))


_CELL = [Field("op", "操作", "choice", OPS[0], OPS), Field("pe", "PE", "int", 0, (0, 7)),
         Field("idx", "阵列", "int", 0, (0, 7)), Field("dev", "器件地址 HEX", "hex", "0002")]

TEMPLATES: List[Template] = [
    # ---- 板卡（地址定义见 FPGA 工程 common_reg.sv）
    Template("查询芯片 Ready 0002", "板卡", [],
             lambda v: FpgaItem(desc="查询 Ready", addr=fpga.Addr.CHIP_READY),
             "芯片 pad_Noc_i_3_Ready，1 才能接收。勾选“发送前查 Ready”时，发芯片报文前会自动查。"),
    Template("读回 FPGA 存值 0003", "板卡", [],
             lambda v: FpgaItem(desc="读回 FPGA 存值", addr=fpga.Addr.NOC_OUT),
             "FPGA 最后一次发给芯片的 8 字节，不是芯片里的数据。"),
    Template("接收使能 0001", "板卡",
             [Field("op", "操作", "choice", "读", ["读", "写 1", "写 0"])],
             lambda v: FpgaItem(desc="读接收使能", addr=fpga.Addr.RX_ENABLE) if v["op"] == "读" else
             FpgaItem(desc="写接收使能 = " + v["op"][-1], addr=fpga.Addr.RX_ENABLE, write=True, data=int(v["op"][-1])),
             "FPGA 是否接收芯片输出（noc_in_ready），复位就是 1。同事给的“初始使能 0001”其实是读这一位。"),
    Template("boot_mode 0004", "板卡",
             [Field("op", "操作", "choice", "读", ["读", "写 1", "写 0"])],
             lambda v: FpgaItem(desc="读 boot_mode", addr=fpga.Addr.BOOT_MODE) if v["op"] == "读" else
             FpgaItem(desc="写 boot_mode = " + v["op"][-1], addr=fpga.Addr.BOOT_MODE, write=True, data=int(v["op"][-1])),
             "FPGA 给芯片的 boot_mode 引脚，复位 1。含义要问芯片设计者，没确认前别改。"),
    # ---- 配置
    Template("写验证脉宽 reg[8]", "配置",
             [Field("mode", "模式", "choice", "单器件（WRITEB）", ["单器件（WRITEB）", "一组数据（WRITED）"]),
              Field("times", "时间倍数", "int", 250, (0, 255)), Field("timeout", "验证次数", "int", 0, (0, 255)),
              Field("base", "基时间", "int", 40, (0, 255))],
             lambda v: PkgItem(desc="写 reg[8] = {:08X}".format(_wwv(v).word), type=PkgType.WRITE_REG,
                               addr=isa.REG_WWV, data=_wwv(v).word),
             "默认 1 ms（40×250）。I1000 实验台用的是 00FF_00FE（254×255，约 6.5 ms）。",
             lambda v: "脉宽 = {} 周期 ≈ {:.3f} ms（10 MHz）".format(_wwv(v).cycles, _wwv(v).pulse_ms)),
    Template("读寄存器", "配置", [Field("reg", "寄存器", "choice", REG_CHOICES[5], REG_CHOICES)],
             lambda v: PkgItem(desc="读 reg[{}]".format(reg_no(v["reg"])), type=PkgType.READ_REG, addr=reg_no(v["reg"])),
             "芯片的回包会自己出现在日志里（橙色）。"),
    Template("写寄存器", "配置",
             [Field("reg", "寄存器", "choice", REG_CHOICES[1], REG_CHOICES), Field("val", "写入值 HEX", "hex", "00000000")],
             lambda v: PkgItem(desc="写 reg[{}] = {:08X}".format(reg_no(v["reg"]), hex_int(v["val"])),
                               type=PkgType.WRITE_REG, addr=reg_no(v["reg"]), data=hex_int(v["val"]))),
    Template("NI 节点使能（推断）", "配置", [],
             lambda v: PkgItem(desc="NI reg[0] 节点使能", type=PkgType.WRITE_NI, addr=0, data=0x01000000),
             "手册里 NI reg[0] 复位为 0，这条是推断的尝试，只改网络接口寄存器，不碰 RRAM。"),
    # ---- 指令
    Template("写 WRITEB 指令", "指令", [Field("at", "存到指令地址 HEX", "hex", "0000")] + _CELL,
             lambda v: PkgItem(desc="指令[{:04X}] WRITEB {:08X}".format(hex_int(v["at"]), _wb(v)),
                               type=PkgType.WRITE_INST, addr=hex_int(v["at"]), data=_wb(v)),
             "", lambda v: "指令字 = {:08X}".format(_wb(v))),
    Template("批量写指令（long_tx）", "指令",
             [Field("start", "起始指令地址 HEX", "hex", "0000"), Field("count", "条数（0x 开头为十六进制）", "count", "0x0FFF")]
             + _CELL + [Field("stop", "末尾加停止指令", "choice", "是", ["是", "否"])],
             lambda v: ProgItem(desc="批量 {:08X}".format(_wb(v)), start=hex_int(v["start"]),
                                segs=[[_wb(v), count_int(v["count"])]], stop=v["stop"] == "是"),
             "", lambda v: "指令 {:08X} 写到 0x{:04X} 起共 {} 条".format(_wb(v), hex_int(v["start"]), count_int(v["count"]))),
    Template("写停止指令", "指令", [Field("at", "指令地址 HEX", "hex", "0FFF")],
             lambda v: PkgItem(desc="指令[{:04X}] 停止".format(hex_int(v["at"])), type=PkgType.WRITE_INST,
                               addr=hex_int(v["at"]), data=isa.STOP_INST),
             "CTRL 00000000 15 = 70F0_0000，放在最后一条指令后面。"),
    Template("读指令", "指令", [Field("at", "指令地址 HEX", "hex", "0000")],
             lambda v: PkgItem(desc="读指令[{:04X}]".format(hex_int(v["at"])), type=PkgType.READ_INST,
                               addr=hex_int(v["at"]))),
    # ---- 运行
    Template("启动核", "运行", [],
             lambda v: PkgItem(desc="启动 reg[0]=1", type=PkgType.WRITE_REG, addr=isa.REG_STATUS, data=isa.START_VALUE),
             "芯片开始执行指令区，可能真正写器件。运行前会弹窗确认。"),
    Template("等待执行结束", "运行", [Field("s", "最长等待秒数", "int", 10, (1, 600))],
             lambda v: PollItem(desc="确认执行结束", timeout_s=int(v["s"])), "反复读 reg[0]，直到出现结束位 0x80。"),
    Template("等待", "运行", [Field("ms", "毫秒", "int", 1000, (0, 600000))],
             lambda v: WaitItem(desc="等待", ms=int(v["ms"]))),
    # ---- 自定义
    Template("自定义芯片报文", "自定义",
             [Field("type", "操作", "choice", TYPE_LABELS[PkgType.READ_REG], list(TYPE_LABELS.values())),
              Field("addr", "地址 HEX", "hex", "0000"), Field("data", "数据 HEX", "hex", "00000000")],
             lambda v: PkgItem(desc="{} {:04X} {:08X}".format(v["type"], hex_int(v["addr"]), hex_int(v["data"])),
                               type=LABEL_TO_TYPE[v["type"]], addr=hex_int(v["addr"]), data=hex_int(v["data"]))),
    Template("原始 HEX", "自定义", [Field("hex", "整帧 HEX", "hex", "55 D5 00 02 00 00 00 00 00 00 00 00")],
             lambda v: RawItem(desc="原始报文", hex=" ".join("{:02X}".format(x) for x in bytes.fromhex(
                 "".join(v["hex"].replace("0x", "").split())))),
             "可以一次填多帧（12 字节的整数倍），会放在同一个 UDP 包里发出。"),
]

BY_NAME: Dict[str, Template] = {t.name: t for t in TEMPLATES}


def groups() -> List[Tuple[str, List[Template]]]:
    out: Dict[str, List[Template]] = {}
    for t in TEMPLATES:
        out.setdefault(t.group, []).append(t)
    return list(out.items())
