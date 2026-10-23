"""计算核的指令编码、配置寄存器和时序换算。

依据《I1003 芯片手册》指令位域图、配置寄存器表，以及 I1000 写测试流程（停止指令、reg[8] 用法）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from rram_console.hardware import RRAM_ARRAY

CHIP_CLK_HZ = 10_000_000      # FPGA clk_pll clk_out6 → clk_sys_rram
INST_DEPTH = 8192             # 每个核的指令存储器 8192×32
STOP_INST = 0x70F00000        # CTRL 00000000 15：指令序列结束
START_VALUE = 0x00000001      # reg[0] Core Status 启动值
END_FLAG = 0x80               # reg[0] Core Status 结束位

REG_STATUS = 0
REG_BASE_ADDR = 4
REG_WWV = 8

OPCODE_WRITEB = 0b0100
OPCODE_CTRL = 0b0111

REG_NAMES = {
    0: "状态/启动", 4: "基地址", 5: "RRAM计算基址", 6: "PC跳转基址", 7: "PE时钟等", 8: "写验证脉宽",
    9: "阵列使能 PE0-3", 10: "阵列使能 PE4-7",
}


def writeb(pe: int, set_: bool, rram_idx: int, cell_addr: int) -> int:
    """WRITEB：opcode 0100 | PE[27:24] | TYPE[23:20]（1 SET，0 RESET）| RRAM INDEX[19:16] | 地址[15:0]"""
    if not (0 <= pe <= 7 and 0 <= rram_idx <= 7):
        raise ValueError("PE 和阵列都是 0 到 7")
    CellEncoding.validate_address(cell_addr)
    return ((OPCODE_WRITEB << 28) | (pe << 24) | ((1 if set_ else 0) << 20) | (rram_idx << 16)
            | (cell_addr & 0xFFFF))


class CellEncoding:
    """器件地址里行、列的排法。手册未写明，I1000 例子只说明低位是列，两种都待确认。"""
    ROW_X128 = "行×128+列（待确认）"
    ROW_SHIFT8 = "行<<8 | 列（待确认）"
    ALL = (ROW_X128, ROW_SHIFT8)

    @staticmethod
    def encode(name: str, row: int, col: int) -> int:
        RRAM_ARRAY.validate_cell(row, col)
        if name not in CellEncoding.ALL:
            raise ValueError("未知的器件地址编码：{}".format(name))
        return row * RRAM_ARRAY.columns + col if name == CellEncoding.ROW_X128 else (row << 8) | col

    @staticmethod
    def decode(name: str, address: int) -> Tuple[int, int]:
        if type(address) is not int or not 0 <= address <= 0xFFFF:
            raise ValueError("器件地址必须为 16 位非负整数")
        if name == CellEncoding.ROW_X128:
            row, col = divmod(address, RRAM_ARRAY.columns)
        elif name == CellEncoding.ROW_SHIFT8:
            row, col = address >> 8, address & 0xFF
        else:
            raise ValueError("未知的器件地址编码：{}".format(name))
        RRAM_ARRAY.validate_cell(row, col)
        return row, col

    @staticmethod
    def validate_address(address: int) -> None:
        # A legacy raw address does not declare an encoding. Accept it only if
        # at least one of I1003's supported encodings maps it into the array.
        for name in CellEncoding.ALL:
            try:
                CellEncoding.decode(name, address)
                return
            except ValueError:
                pass
        raise ValueError("器件地址超出 128×128 阵列范围")


def validate_instruction(word: int) -> None:
    if type(word) is not int or not 0 <= word <= 0xFFFFFFFF:
        raise ValueError("指令字必须为 32 位非负整数")
    if word >> 28 == OPCODE_WRITEB:
        if ((word >> 24) & 0xF) > 7 or ((word >> 16) & 0xF) > 7:
            raise ValueError("WRITEB 的 PE 和阵列都是 0 到 7")
        CellEncoding.validate_address(word & 0xFFFF)


def pulse_pair(ms: float, clk_hz: int = CHIP_CLK_HZ) -> Tuple[int, int]:
    """目标脉宽（ms）→ (基时间, 倍数)，两者都在 1..255，取最接近的组合。"""
    target = max(1, round(ms * clk_hz / 1000))
    best = (1, 1, target - 1)
    for times in range(1, 256):
        base = min(255, max(1, round(target / times)))
        err = abs(base * times - target)
        if err < best[2] or (err == best[2] and times > best[1]):
            best = (base, times, err)
    return best[0], best[1]


@dataclass(frozen=True)
class WwvConfig:
    """reg[8] 写验证配置：Mode[31:24] TimeTimes[23:16] TimeoutTimes[15:8] TimesBase[7:0]"""
    mode: int = 0          # 0 对应 WRITEB，1 对应 WRITED
    times: int = 255
    timeout: int = 0
    base: int = 254

    MAX_MS = 255 * 255 * 1000 / CHIP_CLK_HZ

    def __post_init__(self):
        for v in (self.mode, self.times, self.timeout, self.base):
            if not 0 <= v <= 255:
                raise ValueError("reg[8] 每个字段都是 0 到 255")

    @classmethod
    def from_pulse_ms(cls, ms: float, timeout: int = 0, mode: int = 0) -> "WwvConfig":
        if not 0 < ms <= cls.MAX_MS:
            raise ValueError("脉宽要在 0 到 {:.1f} ms 之间".format(cls.MAX_MS))
        base, times = pulse_pair(ms)
        return cls(mode, times, timeout, base)

    @classmethod
    def from_word(cls, w: int) -> "WwvConfig":
        return cls((w >> 24) & 0xFF, (w >> 16) & 0xFF, (w >> 8) & 0xFF, w & 0xFF)

    @property
    def word(self) -> int:
        return (self.mode << 24) | (self.times << 16) | (self.timeout << 8) | self.base

    @property
    def cycles(self) -> int:
        return self.base * self.times

    @property
    def pulse_ms(self) -> float:
        return self.cycles * 1000.0 / CHIP_CLK_HZ
