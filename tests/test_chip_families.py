"""Chip-family dispatch and saved settings must stay isolated across backends."""

import json
from pathlib import Path
import queue
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from rram_console.chips import ChipFamily, families, get_family, register_family
from i1003.ui.settings import Settings


class ChipFamiliesTest(unittest.TestCase):
    def test_only_implemented_families_are_available(self):
        self.assertEqual([family.id for family in families()], ["i1003"])
        with self.assertRaises(ValueError):
            get_family("not-implemented")
        with self.assertRaises(ValueError):
            register_family(ChipFamily("i1003", "duplicate", lambda: None))

    def test_family_owns_receive_decoding(self):
        from i1003.ui.app import App
        # A future backend can accept a completely different packet size/format.
        decoder = SimpleNamespace(describe_receive=lambda kind, data: ("recv", "其他芯片", data.hex()))
        ctx = SimpleNamespace(backend=decoder, q=queue.Queue(), _record_event=lambda *args, **kwargs: None)
        App._on_receive(ctx, "custom", b"\xaa\xbb\xcc")
        self.assertEqual(ctx.q.get_nowait()[:4], ("log", "recv", "其他芯片", "aabbcc"))

    def test_registration_loads_the_selected_backend(self):
        from rram_console.chips import _families
        class AnotherBackend:
            def describe_receive(self, kind, data):
                return "recv", "独立协议", data.hex()

        with patch.dict(_families):
            register_family(ChipFamily("test-family", "测试系列", AnotherBackend))
            backend = get_family("test-family").create_backend()
            self.assertEqual(backend.describe_receive("custom", b"\x12\x34"), ("recv", "独立协议", "1234"))

    def test_selected_i1003_backend_preserves_ready_decoding(self):
        backend = get_family("i1003").create_backend()
        tag, head, text = backend.describe_receive("bit", bytes(7) + b"\x01")
        self.assertEqual((tag, head), ("recv", "接收"))
        self.assertIn("值=1", text)

    def test_sequence_cannot_apply_another_family_header(self):
        from i1003.ui.app import App
        backend = SimpleNamespace(apply_header=lambda *args: self.fail("must reject before changing the route"))
        ctx = SimpleNamespace(family=get_family("i1003"), backend=backend)
        with self.assertRaises(ValueError):
            App.apply_header(ctx, {"chip_family": "another-family", "core": "11"})

    def test_legacy_sequence_header_is_i1003(self):
        from i1003.ui.app import App
        calls = []
        ctx = SimpleNamespace(family=get_family("i1003"),
                              backend=SimpleNamespace(apply_header=lambda header, app: calls.append(header)))
        App.apply_header(ctx, {"core": "11"})
        self.assertEqual(calls, [{"core": "11"}])

    def test_settings_preserve_other_family_values(self):
        class Variable:
            def __init__(self, value): self.value = value
            def get(self): return self.value
            def set(self, value): self.value = value

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text(json.dumps({"quick.repeat": "8", "other.quick.repeat": "12",
                                        "_extra": {"chip_family": "i1003"}}), encoding="utf-8")
            settings = Settings(str(path))
            current = Variable("0")
            settings.register("quick", {"repeat": current})
            settings.load()
            self.assertEqual(current.get(), "8")
            current.set("9")
            settings.save()
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["other.quick.repeat"], "12")
            self.assertEqual(data["quick.repeat"], "9")


if __name__ == "__main__":
    unittest.main()
