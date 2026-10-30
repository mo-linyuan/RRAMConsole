"""Sequence execution with explicit outcomes and fail-fast readback checks."""
from __future__ import annotations
import copy
import math
import threading
import time
from dataclasses import dataclass
from typing import Optional, Sequence
from ..model.items import FpgaProbeItem, Item, PollItem, ProgItem, RawItem, VerifyItem, WaitItem, hexs, total_frames
from ..protocol import fpga, isa
from ..protocol.pkg import Pkg, Route
from ..transport.udp_link import UdpLink


class RunEvents:
    def log(self, tag, head, text): ...
    def progress(self, done, total): ...
    def status(self, text): ...
    def notify(self, text): ...
    def item_state(self, row, state): ...
    def result(self, result): ...
    def finished(self, ok): ...


@dataclass
class RunOptions:
    route: Route
    check_ready: bool = True
    gap_s: float = 0.02
    fast: bool = False
    chunk: int = fpga.MAX_FRAMES_PER_PACKET
    ready_wait_s: float = 1.0
    download_gap_s: float = 0.0


@dataclass(frozen=True)
class RunResult:
    outcome: str
    sent: int
    planned: int
    elapsed_s: float
    summary: str
    download_s: float = 0.0


class Runner:
    def __init__(self, link: UdpLink, events: RunEvents):
        self.link, self.ev = link, events
        self._stop = threading.Event()
        self._thread = None
        self.last_result = None

    @property
    def busy(self):
        return self._thread is not None and self._thread.is_alive()

    def stop(self):
        self._stop.set()
        self.link.cancel_pending()

    def start(self, items: Sequence[Item], opt: RunOptions, rows=None):
        if self.busy:
            return False
        self._stop.clear()
        items, opt = copy.deepcopy(list(items)), copy.deepcopy(opt)
        rows = list(rows) if rows is not None else [None] * len(items)
        self._thread = threading.Thread(target=self.run, args=(items, opt, rows), name="runner", daemon=True)
        self._thread.start()
        return True

    def run(self, items, opt, rows):
        self._sent = self._total = 0
        self._download_s = 0.0
        self._verified = self._execution_confirmed = False
        self._fpga_checked = False
        self._estimated_wait_done = False
        t0, all_ok = time.monotonic(), True
        current = None
        self.ev.progress(0, 1)
        try:
            if not items or len(items) != len(rows):
                raise ValueError("任务为空或序列行号不完整")
            if not math.isfinite(opt.gap_s) or opt.gap_s < 0:
                raise ValueError("发送间隔必须为非负有限数")
            if not math.isfinite(opt.download_gap_s) or opt.download_gap_s < 0:
                raise ValueError("写入间隔必须为非负有限数")
            if not math.isfinite(opt.ready_wait_s) or opt.ready_wait_s <= 0:
                raise ValueError("Ready 查询超时必须为正有限数")
            # Validate every item before the first hardware write.
            for it in items:
                it.validate()
                it.frames(opt.route, limit=1)
            self._total = total_frames(items)
            for it, row in zip(items, rows):
                if self._stop.is_set():
                    all_ok = False
                    break
                current = row
                if it.is_start():
                    self._execution_confirmed = False
                self.ev.item_state(row, "运行中")
                ok = self._run_item(it, opt)
                state = ("FPGA已核对" if isinstance(it, FpgaProbeItem) else "已核对" if isinstance(it, VerifyItem) else "已确认" if isinstance(it, PollItem)
                         else ("预计等待结束" if it.meta.get("estimated_execution") else "已等待") if isinstance(it, WaitItem) else "已发送")
                self.ev.item_state(row, state if ok and not self._stop.is_set()
                                   else "已停止" if self._stop.is_set() else "失败")
                self.ev.progress(self._sent, self._total)
                if not ok or self._stop.is_set():
                    all_ok = False
                    break
        except Exception as exc:
            self.ev.log("err", "错误", str(exc))
            self.ev.item_state(current, "失败")
            all_ok = False
        finally:
            if self._stop.is_set():
                all_ok, outcome, summary = False, "cancelled", "已停止发送；芯片已启动的操作不会由此自动终止"
            elif not all_ok:
                outcome, summary = "failed", "任务失败，已中止后续步骤"
            elif self._execution_confirmed:
                outcome, summary = "completed", "任务完成，已读到芯片结束标志"
            elif self._verified:
                outcome, summary = "checked", "步骤完成，指定数据核对通过；未确认芯片执行结束"
            elif self._estimated_wait_done:
                outcome, summary = "sent", "已发送，预计等待结束；未读取芯片执行状态"
            elif self._fpga_checked:
                outcome, summary = "fpga_checked", "FPGA 命令暂存读回一致；芯片接收与器件选通尚未验证"
            else:
                outcome, summary = "sent", "报文已发送"
            self.last_result = RunResult(outcome, self._sent, self._total, time.monotonic() - t0, summary, self._download_s)
            self.ev.log("info" if all_ok else "err", "结果", "{} · 发出 {} 条，软件总耗时 {:.3f} s，指令写入 {:.3f} s".format(
                summary, self._sent, self.last_result.elapsed_s, self._download_s))
            callback = getattr(self.ev, "result", None)
            if callback:
                callback(self.last_result)
            self.ev.status("")
            self.ev.finished(all_ok)
        return all_ok

    def _run_item(self, it, opt):
        if isinstance(it, FpgaProbeItem):
            return self._probe_fpga(it, opt)
        if isinstance(it, WaitItem):
            if it.notify:
                self.ev.log("info", "提示", it.notify)
                self.ev.notify(it.notify)
            self._countdown(it.ms / 1000.0, it.desc or "等待")
            if it.meta.get("estimated_execution") and not self._stop.is_set():
                self._estimated_wait_done = True
            return not self._stop.is_set()
        if isinstance(it, ProgItem):
            return self._send_prog(it, opt)
        if isinstance(it, VerifyItem):
            return self._verify(it, opt)
        if isinstance(it, PollItem):
            return self._poll(it, opt)
        return self._send_simple(it, opt)

    def _probe_fpga(self, it, opt):
        if not self._ready(opt, it.desc):
            return False
        transmit, readback = it.frames(opt.route)
        self.link.send(transmit[0], "读 reg[8] 请求（不写 RRAM）")
        self._sent += 1
        if self._pause(opt.gap_s):
            return False
        reply = self.link.request("fpga", readback[0], .6, "回读 0003 暂存", cancel_event=self._stop,
                                  reply_filter=lambda data: Pkg.decode(data).type not in range(8, 12))
        self._sent += 1
        if reply is None:
            self.ev.log("err", "FPGA自检", "地址 0003 未回包，FPGA 命令暂存尚未验证")
            return False
        expected = transmit[0][4:]
        if reply != expected:
            self.ev.log("err", "FPGA自检", "暂存不一致：期望 {}，读到 {}".format(hexs(expected), hexs(reply)))
            return False
        self._fpga_checked = True
        self.ev.log("ok", "FPGA自检", "地址 0003 暂存一致；仅确认 FPGA 保存了 PKG，未确认芯片接收或器件选通")
        return True

    def _ready(self, opt, what):
        if self._stop.is_set():
            return False
        if not opt.check_ready:
            return True
        ready = self.link.wait_chip_ready(opt.ready_wait_s, cancel_event=self._stop)
        if ready:
            return True
        if not self._stop.is_set():
            self.ev.log("err", "错误", "{}：{}".format(what, "0002 查询没有回包" if ready is None else "芯片 Ready 一直为 0"))
        return False

    def _send_simple(self, it, opt):
        for frame, to_chip in it.frames(opt.route):
            if self._stop.is_set() or (to_chip and not self._ready(opt, it.desc)):
                return False
            expect = None
            try:
                write, addr, payload = fpga.parse_frame(frame)
                if not write:
                    expect = "bit" if addr in (1, 2, 4) else "fpga"
                elif addr == fpga.Addr.NOC_OUT and Pkg.decode(payload).type < 4:
                    expect = "chip"
            except ValueError:
                pass
            if expect:
                reply = self.link.request(expect, frame, 0.6, it.desc, cancel_event=self._stop)
                self._sent += 1
                if reply is None:
                    if self._stop.is_set():
                        return False
                    if isinstance(it, RawItem):
                        # Raw frames are the manual probe channel: a silent chip is
                        # a finding to observe, not a task failure. The wait stays,
                        # so a late reply can never be mis-paired with the next read.
                        self.ev.log("info", "提示", "{}：未等到匹配回包（原始报文不判失败，继续后续步骤）；"
                                    "如需失败即停的核对，请改用读类模板".format(it.desc))
                    else:
                        self.ev.log("err", "错误", "{}：没有匹配的回包，停止后续步骤".format(it.desc))
                        return False
            else:
                self.link.send(frame, it.desc)
                self._sent += 1
            self._pause(opt.gap_s)
        return not self._stop.is_set()

    def _send_prog(self, it, opt):
        frames = [frame for frame, _ in it.frames(opt.route)]
        chunk = min(fpga.MAX_FRAMES_PER_PACKET, max(1, opt.chunk)) if opt.fast else 1
        pause = max(.002, opt.download_gap_s) if chunk > 1 else opt.download_gap_s
        batches = math.ceil(len(frames) / chunk)
        self.ev.log("info", "写入指令", "{}：{} 条，指令地址 0x{:04X} 起；{} 个 UDP 包，包后等待 {:.3f} ms，"
                    "写入间隔预算 {:.3f} s（另加 Ready 查询、通信和系统调度耗时）".format(
                        it.desc, len(frames), it.start, batches, pause * 1000, batches * pause))
        self.ev.log("info", "写入指令", "写入与芯片选通时间独立；界面显示首末报文，日志需手动保存")
        started, sent, complete = time.monotonic(), 0, False
        try:
            for j in range(0, len(frames), chunk):
                if not self._ready(opt, "{} 第 {} 条".format(it.desc, j + 1)):
                    return False
                part = frames[j:j + chunk]
                edge = j == 0 or j + chunk >= len(frames)
                self.link.send(b"".join(part), "写入首包" if j == 0 else "写入末包" if edge else "", quiet=not edge)
                self._sent += len(part)
                sent += len(part)
                if chunk > 1 or j % 50 == 0 or j + chunk >= len(frames):
                    self.ev.progress(self._sent, self._total)
                if self._pause(pause):
                    return False
            complete = not self._stop.is_set()
            return complete
        finally:
            elapsed = time.monotonic() - started
            self._download_s += elapsed
            self.ev.log("info" if complete else "err", "写入指令", "指令写入{}：{} / {} 条，实际指令写入耗时 {:.3f} s".format(
                "完成" if complete else "中断", sent, len(frames), elapsed))

    def _pause(self, seconds):
        """Avoid Windows Event.wait's coarse timer; bound stop latency to 10ms.

        Modern Python uses a high-resolution timer for sleep on Windows.
        No busy-spin or process/global timer-resolution changes are needed.
        """
        deadline = time.monotonic() + seconds
        while not self._stop.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(remaining, .01))
        return True

    def _chip_read(self, frame, note, timeout=0.6):
        reply = self.link.request("chip", frame, timeout, note, cancel_event=self._stop)
        self._sent += 1
        return None if reply is None else Pkg.decode(reply).data

    def _verify(self, it, opt):
        if not self._ready(opt, it.desc):
            return False
        got = self._chip_read(it.frames(opt.route)[0][0], it.desc)
        if got is None:
            if not self._stop.is_set():
                self.ev.log("err", "错误", "{}：没有收到匹配的芯片回包，核对失败".format(it.desc))
            return False
        if got != it.expect:
            self.ev.log("err", "错误", "{}：不一致，期望 0x{:08X}，读到 0x{:08X}".format(it.desc, it.expect, got))
            return False
        self.ev.log("ok", "核对", "{}：一致 0x{:08X}".format(it.desc, got))
        self._verified = True
        return True

    def _poll(self, it, opt):
        end, got = time.monotonic() + it.timeout_s, None
        frame = it.frames(opt.route)[0][0]
        while time.monotonic() < end and not self._stop.is_set():
            if not self._ready(opt, it.desc):
                return False
            left = end - time.monotonic()
            if left <= 0:
                break
            got = self._chip_read(frame, "读 reg[0]", min(0.6, left))
            if got is not None and got & isa.END_FLAG:
                self.ev.log("ok", "核对", "芯片执行完成，reg[0] = 0x{:08X}".format(got))
                self._execution_confirmed = True
                return True
            self._countdown(min(0.5, max(0, end - time.monotonic())), "等待芯片执行完")
        if not self._stop.is_set():
            self.ev.log("err", "错误", "未确认芯片执行结束：{}".format(
                "未收到匹配的回包" if got is None else "reg[0] = 0x{:08X}，没有结束标志".format(got)))
        return False

    def _countdown(self, seconds, text):
        end, last = time.monotonic() + seconds, None
        while time.monotonic() < end and not self._stop.is_set():
            left = int(end - time.monotonic() + 0.999)
            if left != last and seconds >= 2:
                self.ev.status("{}  剩余 {} s".format(text, left))
                last = left
            self._stop.wait(min(0.05, max(0, end - time.monotonic())))
        if seconds >= 2:
            self.ev.status("")


__all__ = ["Runner", "RunEvents", "RunOptions", "RunResult", "hexs"]
