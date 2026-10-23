"""执行序列。只依赖 UdpLink 和条目模型，通过 RunEvents 向外报告，不碰界面。"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Sequence

from ..model.items import FpgaItem, Item, PollItem, ProgItem, VerifyItem, WaitItem, hexs, total_frames
from ..protocol import fpga, isa
from ..protocol.pkg import Pkg, Route
from ..transport.udp_link import UdpLink


class RunEvents:
    """运行过程的回调。界面层继承它并转到自己的线程；默认什么都不做，方便测试。"""

    def log(self, tag: str, head: str, text: str) -> None: ...          # tag: send/recv/chip/ok/err/info
    def progress(self, done: int, total: int) -> None: ...
    def status(self, text: str) -> None: ...                             # 顶部状态文字，空串表示清除
    def notify(self, text: str) -> None: ...                             # 需要人去操作时的提醒
    def item_state(self, row: Optional[int], state: str) -> None: ...
    def finished(self, ok: bool) -> None: ...


@dataclass
class RunOptions:
    route: Route
    check_ready: bool = True       # 每次发往芯片前查 0002
    gap_s: float = 0.02            # 普通条目之间的间隔
    fast: bool = False             # 批量写指令时每个 UDP 包装多帧
    chunk: int = fpga.MAX_FRAMES_PER_PACKET
    ready_wait_s: float = 1.0


class Runner:
    def __init__(self, link: UdpLink, events: RunEvents):
        self.link = link
        self.ev = events
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def stop(self) -> None:
        self._stop.set()

    def start(self, items: Sequence[Item], opt: RunOptions, rows: Optional[Sequence[Optional[int]]] = None) -> bool:
        if self.busy:
            return False
        self._stop.clear()
        rows = list(rows) if rows is not None else [None] * len(items)
        self._thread = threading.Thread(target=self.run, args=(list(items), opt, rows), name="runner", daemon=True)
        self._thread.start()
        return True

    # ---------------------------------------------------------------- 主循环
    def run(self, items: List[Item], opt: RunOptions, rows: List[Optional[int]]) -> bool:
        self._sent, self._total, t0, all_ok = 0, total_frames(items), time.time(), True
        try:
            for it, row in zip(items, rows):
                if self._stop.is_set():
                    all_ok = False
                    break
                self.ev.item_state(row, "…")
                ok = self._run_item(it, opt)
                self.ev.item_state(row, "完成" if ok and not self._stop.is_set() else "中断")
                self.ev.progress(self._sent, self._total)
                if not ok:
                    all_ok = False
                    break
        except Exception as e:  # noqa: BLE001  运行线程里任何异常都要报告出来
            self.ev.log("err", "错误", repr(e))
            all_ok = False
        finally:
            if self._stop.is_set():
                self.ev.log("err", "错误", "已手动停止")
            self.ev.log("info", "提示", "结束：发出 {} 条，用时 {:.1f} s".format(self._sent, time.time() - t0))
            self.ev.status("")
            self.ev.finished(all_ok)
        return all_ok

    def _run_item(self, it: Item, opt: RunOptions) -> bool:
        if isinstance(it, WaitItem):
            if it.notify:
                self.ev.log("info", "提示", it.notify)
                self.ev.notify(it.notify)
            self._countdown(it.ms / 1000.0, it.desc or "等待")
            return True
        if isinstance(it, ProgItem):
            return self._send_prog(it, opt)
        if isinstance(it, VerifyItem):
            return self._verify(it, opt)
        if isinstance(it, PollItem):
            return self._poll(it, opt)
        return self._send_simple(it, opt)

    # ---------------------------------------------------------------- 各类条目
    def _ready(self, opt: RunOptions, what: str) -> bool:
        if not opt.check_ready:
            return True
        r = self.link.wait_chip_ready(opt.ready_wait_s)
        if r:
            return True
        self.ev.log("err", "错误", "{}：{}".format(what, "0002 查询没有回包" if r is None else "芯片 Ready 一直为 0"))
        return False

    def _send_simple(self, it: Item, opt: RunOptions) -> bool:
        for fr, to_chip in it.frames(opt.route):
            if self._stop.is_set():
                return False
            if to_chip and not self._ready(opt, it.desc):
                return False
            if isinstance(it, FpgaItem) and not it.write:
                expect = "fpga" if it.addr == fpga.Addr.NOC_OUT else "bit"
                r = self.link.request(expect, fr, 0.5, it.desc)
                if r is None:
                    self.ev.log("err", "错误", "{}：没有回包".format(it.desc))
            else:
                self.link.send(fr, it.desc)
            self._sent += 1
            if opt.gap_s:
                time.sleep(opt.gap_s)
        return True

    def _send_prog(self, it: ProgItem, opt: RunOptions) -> bool:
        frames = [f for f, _ in it.frames(opt.route)]
        chunk = max(1, opt.chunk) if opt.fast else 1
        self.ev.log("info", "提示", "{}：{} 条，指令地址 0x{:04X} 起{}".format(
            it.desc, len(frames), it.start, "，每包 {} 帧".format(chunk) if chunk > 1 else ""))
        for j in range(0, len(frames), chunk):
            if self._stop.is_set():
                return False
            if not self._ready(opt, "{} 第 {} 条".format(it.desc, j + 1)):
                return False
            part = frames[j:j + chunk]
            self.link.send(b"".join(part), "", quiet=True)
            self._sent += len(part)
            if chunk > 1 or j % 50 == 0 or j + chunk >= len(frames):
                self.ev.progress(self._sent, self._total)
            if chunk > 1:
                time.sleep(0.002)
        self.ev.log("info", "提示", "{} 完成".format(it.desc))
        return True

    def _chip_read(self, fr: bytes, note: str, timeout: float = 0.6) -> Optional[int]:
        r = self.link.request("chip", fr, timeout, note)
        self._sent += 1
        return None if r is None or len(r) != 8 else Pkg.decode(r).data

    def _verify(self, it: VerifyItem, opt: RunOptions) -> bool:
        if not self._ready(opt, it.desc):
            return False
        got = self._chip_read(it.frames(opt.route)[0][0], it.desc)
        if got is None:
            self.ev.log("info", "提示", "{}：没有收到芯片回包，跳过核对".format(it.desc))
        elif got == it.expect:
            self.ev.log("ok", "核对", "{}：一致 0x{:08X}".format(it.desc, got))
        else:
            self.ev.log("err", "错误", "{}：不一致，期望 0x{:08X}，读到 0x{:08X}".format(it.desc, it.expect, got))
        return True

    def _poll(self, it: PollItem, opt: RunOptions) -> bool:
        end, got = time.time() + it.timeout_s, None
        fr = it.frames(opt.route)[0][0]
        while time.time() < end and not self._stop.is_set():
            if not self._ready(opt, it.desc):
                break
            v = self._chip_read(fr, "读 reg[0]")
            if v is not None:
                got = v
                if got & isa.END_FLAG:
                    break
            self._countdown(0.5, "等待芯片执行完")
        if got is None:
            self.ev.log("info", "提示", "{}：一直没收到芯片回包，无法判断是否执行完".format(it.desc))
            return True
        if got & isa.END_FLAG:
            self.ev.log("ok", "核对", "芯片执行完成，reg[0] = 0x{:08X}".format(got))
            return True
        self.ev.log("err", "错误", "超时，reg[0] = 0x{:08X}，还没有结束标志".format(got))
        return False

    def _countdown(self, seconds: float, text: str) -> None:
        end, last = time.time() + seconds, None
        while time.time() < end and not self._stop.is_set():
            left = int(end - time.time() + 0.999)
            if left != last and seconds >= 2:
                self.ev.status("{}  剩余 {} s".format(text, left))
                last = left
            time.sleep(0.05)
        if seconds >= 2:
            self.ev.status("")


__all__ = ["Runner", "RunEvents", "RunOptions", "hexs"]
