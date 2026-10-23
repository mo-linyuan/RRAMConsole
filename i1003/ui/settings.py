"""把界面上的设置存成 json，下次启动恢复。各面板通过 register() 登记自己的变量。"""

from __future__ import annotations

import json
import os
import tkinter as tk
from typing import Dict


class Settings:
    def __init__(self, path: str):
        self.path = path
        self._vars: Dict[str, tk.Variable] = {}
        self._extra: Dict = {}
        self._stored: Dict = {}

    def register(self, prefix: str, variables: Dict[str, tk.Variable]) -> None:
        for k, v in variables.items():
            self._vars["{}.{}".format(prefix, k)] = v

    def get_extra(self, key: str, default=None):
        return self._extra.get(key, default)

    def set_extra(self, key: str, value) -> None:
        self._extra[key] = value

    def load(self) -> None:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        self._extra = data.get("_extra", {})
        self._stored = data
        for k, v in self._vars.items():
            if k in data:
                try:
                    v.set(data[k])
                except tk.TclError:
                    pass

    def save(self) -> None:
        data = dict(self._stored)
        data.update({k: v.get() for k, v in self._vars.items()})
        data["_extra"] = self._extra
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            self._stored = data
        except OSError:
            pass
