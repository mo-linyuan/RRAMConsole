"""Array edges and legacy addresses must produce exact, non-wrapping commands."""

import tempfile
from pathlib import Path
import unittest

from rram_console.hardware import RRAM_ARRAY
from rram_console.chips import get_family
from i1003.protocol import isa
from i1003.protocol.pkg import PkgType, Route
from i1003.model.items import PkgItem, ProgItem
from i1003.model.sequence_io import load_json, save_json
from i1003.recipes.write_test import WriteTestSpec, SpecError, plan
from i1003.ui.templates import BY_NAME


class ArrayGeometryTest(unittest.TestCase):
    def test_shared_array_dimensions(self):
        self.assertEqual((RRAM_ARRAY.rows, RRAM_ARRAY.columns, RRAM_ARRAY.cells), (128, 128, 16384))
        self.assertIs(get_family("i1003").array_geometry, RRAM_ARRAY)

    def test_last_cell_roundtrips_in_both_encodings(self):
        for encoding, expected in ((isa.CellEncoding.ROW_X128, 0x3FFF), (isa.CellEncoding.ROW_SHIFT8, 0x7F7F)):
            with self.subTest(encoding=encoding):
                self.assertEqual(isa.CellEncoding.encode(encoding, 127, 127), expected)
                self.assertEqual(isa.CellEncoding.decode(encoding, expected), (127, 127))

    def test_outside_rows_columns_and_unknown_encoding_are_rejected(self):
        for row, col in ((128, 0), (0, 128), (-1, 0), (0, -1), (1.5, 2), (True, 0)):
            with self.subTest(row=row, col=col), self.assertRaises(ValueError):
                isa.CellEncoding.encode(isa.CellEncoding.ROW_X128, row, col)
        with self.assertRaises(ValueError):
            isa.CellEncoding.encode("unknown", 0, 0)

    def test_raw_writeb_address_cannot_wrap_or_address_outside_array(self):
        for address in (-1, 0x10000, 0x7F80, 0x8000):
            with self.subTest(address=address), self.assertRaises(ValueError):
                isa.writeb(0, True, 0, address)

    def test_recipe_rejects_outside_array(self):
        for spec in (WriteTestSpec(row_to=128), WriteTestSpec(col_to=128), WriteTestSpec(row_from=-1)):
            with self.assertRaises(SpecError):
                plan(spec)

    def test_templates_use_row_and_column(self):
        for name in ("写 WRITEB 指令", "批量写指令（long_tx）"):
            template = BY_NAME[name]
            for encoding, address in ((isa.CellEncoding.ROW_X128, 0x3FFF), (isa.CellEncoding.ROW_SHIFT8, 0x7F7F)):
                item = template.make({"row": "127", "col": "127", "encoding": encoding})
                word = item.data if isinstance(item, PkgItem) else item.segs[0][0]
                self.assertEqual(word, 0x40100000 | address)
            with self.assertRaises(ValueError):
                template.make({"row": "128", "col": "0"})

    def test_legacy_template_keeps_exact_address(self):
        for name in ("写 WRITEB 指令", "批量写指令（long_tx）"):
            for address in (0x0002, 0x0080, 0x3FFF, 0x7F7F):
                item = BY_NAME[name].make({"dev": "{:04X}".format(address)})
                word = item.data if isinstance(item, PkgItem) else item.segs[0][0]
                self.assertEqual(word & 0xFFFF, address)
                self.assertNotIn("dev", item.meta["vals"])

    def test_import_rejects_invalid_structured_instruction(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "sequence.json")
            for item in (PkgItem(type=PkgType.WRITE_INST, data=0x40107F80), ProgItem(segs=[[0x40107F80, 1]])):
                save_json(path, [item], {"chip_family": "i1003"})
                with self.assertRaises(ValueError):
                    load_json(path)

    def test_valid_edge_instruction_survives_json_roundtrip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "sequence.json")
            item = BY_NAME["写 WRITEB 指令"].make({"row": "127", "col": "127"})
            save_json(path, [item], {"chip_family": "i1003"})
            loaded, _ = load_json(path)
            self.assertEqual(loaded[0].frames(Route()), item.frames(Route()))

    def test_array_capacity_does_not_override_instruction_capacity(self):
        with self.assertRaises(ValueError):
            ProgItem(segs=[[isa.writeb(0, True, 0, 0), RRAM_ARRAY.cells]]).frames(Route())


if __name__ == "__main__":
    unittest.main()
