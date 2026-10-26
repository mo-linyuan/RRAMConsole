"""Packet expectations from FPGA/PKG fields, not another encoder invocation."""
import unittest
from i1003.ui.templates import BY_NAME, TEMPLATES
from i1003.protocol.pkg import Route


class TemplateAuditTest(unittest.TestCase):
    def test_default_frames_match_protocol_table(self):
        expected = {
            "查询芯片 Ready 0002": "55 D5 00 02 00 00 00 00 00 00 00 00",
            "读回 FPGA 存值 0003": "55 D5 00 03 00 00 00 00 00 00 00 00",
            "接收使能 0001": "55 D5 00 01 00 00 00 00 00 00 00 00",
            "boot_mode 0004": "55 D5 00 04 00 00 00 00 00 00 00 00",
            "写验证脉宽 reg[8]": "55 D5 80 03 04 C0 00 08 00 FF 00 FE",
            "读寄存器": "55 D5 80 03 00 C0 00 08 00 00 00 00",
            "写寄存器": "55 D5 80 03 04 C0 00 04 00 00 00 00",
            "写停止指令": "55 D5 80 03 05 C0 00 01 70 F0 00 00",
            "读指令": "55 D5 80 03 01 C0 00 00 00 00 00 00",
            "启动核": "55 D5 80 03 04 C0 00 00 00 00 00 01",
            "自定义芯片报文": "55 D5 80 03 00 C0 00 00 00 00 00 00",
            "原始 HEX": "55 D5 00 02 00 00 00 00 00 00 00 00",
        }
        for name, literal in expected.items():
            with self.subTest(name=name):
                self.assertEqual(BY_NAME[name].make().frames(Route())[0][0], bytes.fromhex(literal))
        self.assertNotIn("等待", BY_NAME)
        self.assertNotIn("等待执行结束", BY_NAME)

    def test_single_and_batch_writeb_share_one_visible_template(self):
        names = [template.name for template in TEMPLATES]
        self.assertEqual(names.count("写入 WRITEB 指令"), 1)
        for removed in ("写 WRITEB 指令", "批量写入指令", "批量写指令（long_tx）", "FPGA发送寄存器自检", "NI 节点使能（推断）"):
            self.assertNotIn(removed, names)
        template = BY_NAME["写入 WRITEB 指令"]
        single = template.make().frames(Route())
        self.assertEqual(single[0][0], bytes.fromhex("55 D5 80 03 05 C0 00 00 40 10 00 02"))
        self.assertEqual(single[1][0], bytes.fromhex("55 D5 80 03 05 C0 00 01 70 F0 00 00"))
        batch = template.make({"count": "3", "op": "RESET（写0）"}).frames(Route())
        self.assertEqual(len(batch), 4)
        self.assertEqual(batch[2][0], bytes.fromhex("55 D5 80 03 05 C0 00 02 40 00 00 02"))
        self.assertEqual(batch[3][0], bytes.fromhex("55 D5 80 03 05 C0 00 03 70 F0 00 00"))

    def test_invalid_inputs_fail_at_template_construction(self):
        for name, values in [
            ("读指令", {"at": "2000"}), ("写停止指令", {"at": "2000"}),
            ("写入 WRITEB 指令", {"count": "0"}), ("写入 WRITEB 指令", {"count": "8192"}),
            ("写入 WRITEB 指令", {"pe": "8"}), ("写入 WRITEB 指令", {"op": "invalid"}),
            ("写入 WRITEB 指令", {"encoding": "invalid"}), ("boot_mode 0004", {"op": "invalid"}),
            ("写验证脉宽 reg[8]", {"mode": "invalid"}), ("写验证脉宽 reg[8]", {"base": "256"}),
            ("写寄存器", {"val": "100000000"}), ("读指令", {"at": "-1"}),
            ("原始 HEX", {"hex": ""}),
        ]:
            with self.subTest(name=name, values=values), self.assertRaises(ValueError):
                BY_NAME[name].make(values)
