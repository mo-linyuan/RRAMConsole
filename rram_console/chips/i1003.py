"""I1003 adapter. Commands, transport, execution and panels belong to this family.

Other families supply their own adapter; they must not reuse I1003 encodings
unless their hardware protocol actually matches.
"""


class I1003Backend:
    # Keep the existing I1003 setting names to preserve installed configurations.
    settings_prefix = ""

    def migrate_settings(self, settings, quick):
        # Reset former mandatory-readback defaults once, including saved installs.
        marker = (self.settings_prefix or "i1003.") + "send_only_defaults_v1"
        settings.set_extra(marker, True)  # Removed readback/wait controls are no longer loaded.
        single_marker = (self.settings_prefix or "i1003.") + "single_device_default_v1"
        if not settings.get_extra(single_marker, False):
            # Retire the former automatic 4095-repeat default once. Other
            # custom counts survive; future explicit 4095 choices also survive.
            if str(quick.vars["repeat"].get()).strip() == "4095":
                quick.vars["repeat"].set("1")
                quick.scene.set("单器件只打一次")
            settings.set_extra(single_marker, True)
        settings.save()

    def create_link(self, on_send, on_receive):
        from i1003.transport.simulator import SimulatableUdpLink
        return SimulatableUdpLink(on_send=on_send, on_receive=on_receive)

    def create_runner(self, link, events):
        from i1003.engine.runner import Runner
        return Runner(link, events)

    def create_connection_bar(self, parent, fonts, on_toggle):
        from i1003.ui.panels.toolbar import ConnectionBar
        return ConnectionBar(parent, fonts, on_toggle)

    def open_link(self, link, connection_bar):
        if connection_bar.is_simulation():
            from i1003.transport.simulator import PROFILES
            label = connection_bar.profile.get()
            link.open_simulation(PROFILES[label])
            lip, lport, rip, rport = link.endpoints
            return ("[离线模拟] {} · {}:{} → {}:{}；仅验证软件协议和流程，不代表芯片执行或导通".format(
                label, lip, lport, rip, rport))
        lip, lport, rip, rport = connection_bar.endpoints()
        link.open(lip, lport, rip, rport)
        return "UDP 已打开 {}:{} → {}:{}".format(lip, lport, rip, rport)

    def probe_link(self, link):
        """One Ready query right after open: a local UDP bind proves nothing about the wire."""
        from i1003.protocol import fpga
        value = link.read_bit(fpga.Addr.CHIP_READY, "连接探测", timeout=.5)
        if value is None:
            return False, "Ready 无回包 · 检查网线、板卡供电或本机 IP；socket 保持打开，重新连接可再次探测"
        if value == 1:
            return True, ""
        return True, "Ready=0 · 链路已通，芯片未就绪"

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

    def describe_receive(self, kind, data):
        from i1003.model.items import hexs
        from i1003.protocol.pkg import Pkg
        preview = hexs(data[:120])
        if len(data) > 120:
            preview += " …（共 {} 字节，仅显示预览）".format(len(data))
        if kind == "bit":
            return "recv", "接收", "{}    值={}".format(preview, data[7] & 1)
        if kind == "fpga":
            return "recv", "接收", preview
        if kind == "foreign":
            return "info", "忽略", "{}    来自非目标板卡的 UDP 包，未用于核对".format(preview)
        if kind == "unmatched":
            note = "未匹配当前请求，未用于核对"
            if len(data) == 8 and Pkg.decode(data).type in range(8, 12):
                note += " · " + Pkg.decode(data).describe()
            return "info", "未匹配", "{}    {}".format(preview, note)
        note = "可能来自芯片"
        if len(data) == 8:
            note += "  ·  " + Pkg.decode(data).describe()
        return "chip", "芯片", "{}    {}".format(preview, note)

    def apply_header(self, header, ctx):
        from i1003.protocol.pkg import NODES
        variables = ctx.route_bar.vars
        for key in ("core", "src"):
            if header.get(key) in NODES:
                variables[key].set(header[key])
        if str(header.get("rgn", "")) in ("0", "1", "2", "3"):
            variables["rgn"].set(str(header["rgn"]))
        ctx.on_route_changed()
