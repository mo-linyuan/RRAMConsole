"""面板之间的约定。各面板只依赖这个接口，彼此互不引用，由 App 负责把它们连起来。"""

from __future__ import annotations

from typing import List, Optional, Sequence

from ..model.items import Item
from ..protocol.pkg import Route


class AppContext:
    fonts = None
    root = None

    # 运行与状态
    def route(self) -> Route: raise NotImplementedError
    def is_connected(self) -> bool: raise NotImplementedError
    def is_busy(self) -> bool: raise NotImplementedError
    def chip_family_id(self) -> str: raise NotImplementedError

    def run(self, items: Sequence[Item], rows: Optional[Sequence[Optional[int]]] = None,
            confirm: bool = False) -> bool:
        raise NotImplementedError

    def stop(self) -> None: raise NotImplementedError
    def log(self, tag: str, head: str, text: str) -> None: raise NotImplementedError
    def apply_header(self, header: dict) -> None: raise NotImplementedError     # 导入 json 时恢复目标核等

    # 序列
    def sequence_add(self, item: Item) -> None: raise NotImplementedError
    def sequence_replace_selected(self, item: Item) -> bool: raise NotImplementedError
    def sequence_set(self, items: List[Item]) -> None: raise NotImplementedError

    # 编辑：序列里双击某条时，交给模板面板载入
    def edit_item(self, item: Item) -> None: raise NotImplementedError

    # 路由变化时通知需要刷新显示的面板
    def on_route_changed(self) -> None: raise NotImplementedError
