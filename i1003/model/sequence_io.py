"""序列的导入导出：本项目 .json、网络调试助手批量发送 .ini、纯文本 HEX。"""

from __future__ import annotations

import json
import re
from typing import Dict, List, Tuple

from ..protocol import fpga
from ..protocol.pkg import LABEL_TO_TYPE, TYPE_LABELS, Pkg, PkgType, Route
from .items import FpgaItem, Item, PkgItem, ProgItem, RawItem, WaitItem, from_dict, hexs
from ..protocol import isa

FORMAT_VERSION = 2


# ---------------------------------------------------------------- JSON
def save_json(path: str, items: List[Item], header: Dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"version": FORMAT_VERSION, "header": header, "items": [it.to_dict() for it in items]},
                  f, ensure_ascii=False, indent=2)


def load_json(path: str) -> Tuple[List[Item], Dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return [from_dict(d) for d in data["items"]], data.get("header", {})


# ---------------------------------------------------------------- 展开成帧
def expand(items: List[Item], route: Route, insert_ready: bool) -> Tuple[List[bytes], int]:
    """展开成逐帧列表。等待条目无法用帧表示，返回跳过的个数。"""
    lines, skipped = [], 0
    ready = fpga.read_frame(fpga.Addr.CHIP_READY)
    for it in items:
        if isinstance(it, WaitItem):
            skipped += 1
            continue
        for fr, to_chip in it.frames(route):
            if to_chip and insert_ready:
                lines.append(ready)
            lines.append(fr)
    return lines, skipped


def export_netassist(path: str, items: List[Item], route: Route, insert_ready: bool = True) -> Tuple[int, int]:
    lines, skipped = expand(items, route, insert_ready)
    with open(path, "w", encoding="utf-8") as f:
        f.write("[BATCHSEND]\n")
        for n, fr in enumerate(lines, 1):
            f.write("{}=1|1|1||{} \n".format(n, hexs(fr)))
    return len(lines), skipped


def export_text(path: str, items: List[Item], route: Route, insert_ready: bool = True) -> Tuple[int, int]:
    lines, skipped = expand(items, route, insert_ready)
    with open(path, "w", encoding="utf-8") as f:
        for fr in lines:
            f.write(hexs(fr) + "\n")
    return len(lines), skipped


# ---------------------------------------------------------------- 文本导入
_NETASSIST_LINE = re.compile(r"^\d+\s*=.*\|\|(.*)$")


def parse_text(text: str, route: Route, drop_ready: bool = True) -> Tuple[List[Item], int]:
    """解析网络调试助手 .ini 或纯文本（每行一帧，# 后为备注）。
    drop_ready：去掉紧挨在芯片帧前面的 0002 查询（运行时会自动查）。返回 (条目, 去掉的查询数)。"""
    frames: List[Tuple[bytes, str]] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith(("[", ";")):
            continue
        note = ""
        if "#" in s:
            s, note = s.split("#", 1)
        m = _NETASSIST_LINE.match(s)
        if m:
            s = m.group(1)
        s = re.sub(r"0[xX]", "", s).replace("_", "")
        if s.strip():
            frames.append((bytes.fromhex("".join(s.split())), note.strip()))

    items: List[Item] = []
    dropped = 0
    for k, (b, note) in enumerate(frames):
        nxt = frames[k + 1][0] if k + 1 < len(frames) else b""
        try:
            write, addr, data = fpga.parse_frame(b)
        except ValueError:
            items.append(RawItem(desc=note or "原始报文", hex=hexs(b)))
            continue
        if not write and addr == fpga.Addr.CHIP_READY and drop_ready and fpga.is_chip_frame(nxt):
            dropped += 1
            continue
        if write and addr == fpga.Addr.NOC_OUT:
            p = Pkg.decode(data)
            if p.route() == route and p.type in TYPE_LABELS:
                items.append(PkgItem(desc=note or "{} {:04X} {:08X}".format(TYPE_LABELS[p.type], p.addr, p.data),
                                     type=p.type, addr=p.addr, data=p.data))
            else:
                items.append(RawItem(desc=note or "芯片报文（路由与当前设置不同）", hex=hexs(b)))
        else:
            label = fpga.ADDR_LABELS.get(addr, "地址 {}".format(addr))
            items.append(FpgaItem(desc=note or ("写" if write else "读") + label, addr=addr, write=write,
                                  data=int.from_bytes(data, "big")))
    return collapse(items), dropped


def collapse(items: List[Item], min_run: int = 3) -> List[Item]:
    """把地址连续、内容相同的写指令合并成一个 ProgItem（后面紧跟的停止指令一并吸收）。"""
    def is_w(it):
        return isinstance(it, PkgItem) and it.type == PkgType.WRITE_INST

    out: List[Item] = []
    i, n = 0, len(items)
    while i < n:
        it = items[i]
        j = i
        if is_w(it) and it.data != isa.STOP_INST:
            while (j + 1 < n and is_w(items[j + 1]) and items[j + 1].data == it.data
                   and items[j + 1].addr == items[j].addr + 1):
                j += 1
        run = j - i + 1
        if run >= min_run:
            stop = (j + 1 < n and is_w(items[j + 1]) and items[j + 1].data == isa.STOP_INST
                    and items[j + 1].addr == items[j].addr + 1)
            out.append(ProgItem(desc="批量写指令 {:08X}".format(it.data), start=it.addr, segs=[[it.data, run]], stop=stop))
            i = j + (2 if stop else 1)
        else:
            out.append(it)
            i += 1
    return out


def load_any(path: str, route: Route) -> Tuple[List[Item], Dict, str]:
    """按扩展名导入，返回 (条目, 头信息, 提示文字)。"""
    if path.lower().endswith(".json"):
        items, header = load_json(path)
        return items, header, ""
    with open(path, encoding="utf-8", errors="ignore") as f:
        items, dropped = parse_text(f.read(), route)
    return items, {}, ("去掉了 {} 条紧挨在芯片报文前的 0002 查询（运行时会自动查）".format(dropped) if dropped else "")


__all__ = ["save_json", "load_json", "export_netassist", "export_text", "parse_text", "collapse", "load_any",
           "LABEL_TO_TYPE"]
