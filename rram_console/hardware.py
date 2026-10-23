"""Shared RRAM array dimensions; instruction encodings remain family-specific."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ArrayGeometry:
    rows: int = 128
    columns: int = 128

    @property
    def cells(self):
        return self.rows * self.columns

    @property
    def label(self):
        return "{}×{}".format(self.rows, self.columns)

    def validate_cell(self, row, column):
        if (type(row) is not int or type(column) is not int
                or not 0 <= row < self.rows or not 0 <= column < self.columns):
            raise ValueError("RRAM 阵列固定为 {}，行号为 0～{}，列号为 0～{}".format(
                self.label, self.rows - 1, self.columns - 1))


RRAM_ARRAY = ArrayGeometry()
