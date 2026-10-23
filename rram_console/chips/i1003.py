"""I1003 adapter. Commands, transport, execution and panels belong to this family.

Other families supply their own adapter; they must not reuse I1003 encodings
unless their hardware protocol actually matches.
"""


class I1003Backend:
    # Keep the existing I1003 setting names to preserve installed configurations.
    settings_prefix = ""

    def create_link(self, on_send, on_receive):
        from i1003.transport.udp_link import UdpLink
        return UdpLink(on_send=on_send, on_receive=on_receive)

    def create_runner(self, link, events):
        from i1003.engine.runner import Runner
        return Runner(link, events)

    def create_connection_bar(self, parent, fonts, on_toggle):
        from i1003.ui.panels.toolbar import ConnectionBar
        return ConnectionBar(parent, fonts, on_toggle)

    def open_link(self, link, connection_bar):
        lip, lport, rip, rport = connection_bar.endpoints()
        link.open(lip, lport, rip, rport)
        return "UDP 已打开 {}:{} → {}:{}".format(lip, lport, rip, rport)

    connection_hint = ("常见原因：网络调试助手还开着，占用了本地端口；"
                       "或者本机 IP 不是这台电脑网卡的地址（FPGA 的回包固定发往 192.168.1.9:8080）。")

    def create_route_bar(self, parent, on_changed):
        from i1003.ui.panels.toolbar import RouteBar
        return RouteBar(parent, on_changed)

    def create_quick_panel(self, parent, ctx):
        from i1003.ui.panels.quick_panel import QuickPanel
        return QuickPanel(parent, ctx)

    def create_template_panel(self, parent, ctx):
        from i1003.ui.panels.template_panel import TemplatePanel
        return TemplatePanel(parent, ctx)

    def create_sequence_panel(self, parent, ctx):
        from i1003.ui.panels.sequence_panel import SequencePanel
        return SequencePanel(parent, ctx)

    def frame_count(self, items):
        from i1003.model.items import total_frames
        return total_frames(items)

    def run_metadata(self, items, options):
        from dataclasses import asdict
        return {"options": asdict(options), "sequence": [item.to_dict() for item in items]}

    def start_confirmation(self, items, route):
        if not any(item.is_start() for item in items):
            return None
        return ("要运行的内容里有“启动核”，核 {} 会开始执行指令区，可能真正写器件。\n\n"
                "请确认：指令区末尾有停止指令，电压和 forming 已确认。继续？".format(route.core))

    def describe_receive(self, kind, data):
        from i1003.model.items import hexs
        from i1003.protocol.pkg import Pkg
        if kind == "bit":
            return "recv", "接收", "{}    值={}".format(hexs(data), data[7] & 1)
        if kind == "fpga":
            return "recv", "接收", "{}    FPGA 存值（不是芯片回包）".format(hexs(data))
        if kind == "foreign":
            return "info", "忽略", "{}    来自非目标板卡的 UDP 包，未用于核对".format(hexs(data))
        if kind == "unmatched":
            note = "未匹配当前请求，未用于核对"
            if len(data) == 8 and Pkg.decode(data).type in range(8, 12):
                note += " · " + Pkg.decode(data).describe()
            return "info", "未匹配", "{}    {}".format(hexs(data), note)
        note = "可能来自芯片"
        if len(data) == 8:
            note += "  ·  " + Pkg.decode(data).describe()
        return "chip", "芯片", "{}    {}".format(hexs(data), note)

    def apply_header(self, header, ctx):
        from i1003.protocol.pkg import NODES
        variables = ctx.route_bar.vars
        for key in ("core", "src"):
            if header.get(key) in NODES:
                variables[key].set(header[key])
        if str(header.get("rgn", "")) in ("0", "1", "2", "3"):
            variables["rgn"].set(str(header["rgn"]))
        ctx.on_route_changed()
