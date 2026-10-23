"""Registered chip families. Only implemented backends appear in the selector."""

from dataclasses import dataclass
from typing import Callable, Dict

from rram_console.hardware import RRAM_ARRAY

from .i1003 import I1003Backend


@dataclass(frozen=True)
class ChipFamily:
    id: str
    name: str
    create_backend: Callable

    @property
    def array_geometry(self):
        return RRAM_ARRAY


_families: Dict[str, ChipFamily] = {}
DEFAULT_FAMILY = "i1003"


def register_family(family: ChipFamily) -> None:
    if not family.id or not family.name or not callable(family.create_backend):
        raise ValueError("芯片系列必须提供标识、名称和后端工厂")
    if family.id in _families:
        raise ValueError("芯片系列已注册：{}".format(family.id))
    if any(item.name == family.name for item in _families.values()):
        raise ValueError("芯片系列名称已使用：{}".format(family.name))
    _families[family.id] = family


def get_family(family_id: str) -> ChipFamily:
    if family_id not in _families:
        raise ValueError("尚未支持的芯片系列：{}".format(family_id))
    return _families[family_id]


def families():
    return tuple(_families.values())


register_family(ChipFamily("i1003", "I1003 系列", I1003Backend))
