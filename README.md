# I1003 调试台

PC 通过 UDP 控制板卡 FPGA，再由 FPGA 把 64 位 PKG 送进 I1003 芯片的 NoC。用来完成 I1000 实验台那一套 RRAM 写测试（配 reg[8]、批量写指令、停止、启动、查结束），并尽量少手敲报文。

## 运行

只用 Python 标准库，Python 3.8 以上即可。

```
python run.py                       # 启动调试台
python -m tools.fake_board          # 另开一个窗口：模拟板卡，离线调界面用
python -m unittest discover -s tests -t .   # 跑测试
```

运行前关掉网络调试助手，两个程序不能同时占用本机 8080 端口。电脑有线网卡要设为 192.168.1.9，FPGA 的回包固定发往 192.168.1.9:8080。

用模拟板卡时，调试台里把本机设成 `127.0.0.1:9081`，板卡设成 `127.0.0.1:9080`。加 `--no-chip-reply` 可以模拟现在真实板卡"芯片不回包"的情况。

界面设置自动保存在 `~/.i1003_console/settings.json`。

## 目录结构

```
i1003/
  protocol/       协议层：纯函数，不依赖任何其他模块
    fpga.py         FPGA 帧格式和地址定义（依据 common_reg.sv、decode.v）
    pkg.py          NoC 64 位 PKG 编解码、路由 Route
    isa.py          指令编码（WRITEB、停止指令）、reg[8] 写验证配置、10 MHz 时序换算
  transport/
    udp_link.py     UDP 收发、请求与回包配对、查芯片 Ready
  model/
    items.py        序列条目：每种条目知道怎么展开成帧、怎么序列化
    sequence_io.py  导入导出：本项目 .json、网络调试助手 .ini、纯文本
  engine/
    runner.py       按序列执行，事件通过 RunEvents 回调报告，不碰界面
  recipes/
    write_test.py   RRAM 写测试配方：WriteTestSpec → 序列条目 + 摘要
  ui/             界面层
    theme.py        颜色、字体、样式
    context.py      面板之间的接口（AppContext）
    templates.py    报文模板的数据定义
    settings.py     设置保存
    app.py          主窗口：组装各部分，实现 AppContext
    panels/         各面板，只依赖 AppContext，互不引用
tests/            单元测试 + 界面冒烟测试
tools/fake_board.py   模拟板卡
run.py
```

依赖方向是单向的：`protocol ← transport ← engine`，`protocol ← model ← recipes`，`ui` 在最上层。除 `ui` 外都不 import tkinter，所以协议、配方、执行器都能脱离界面单独测试和复用，比如以后写批量测试脚本时直接用 `recipes` + `engine`。

### 常见改动应该改哪里

| 想做的事 | 改哪里 |
|---|---|
| FPGA 加了新地址（比如复位寄存器） | `protocol/fpga.py` 的 `Addr`，再在 `ui/templates.py` 加一个模板 |
| 确认了行列在器件地址里的排法 | `protocol/isa.py` 的 `CellEncoding` |
| 确认了源节点坐标或 RGN | `ui/panels/toolbar.py` 里 `RouteBar` 的默认值，或 `protocol/pkg.py` 的 `Route` |
| 芯片时钟不是 10 MHz | `protocol/isa.py` 的 `CHIP_CLK_HZ` |
| 新增一种测试流程 | 在 `recipes/` 下新建配方，返回 `List[Item]`，界面只需加按钮调用 |
| 新增一种条目（比如等外部触发） | `model/items.py` 加类，`engine/runner.py` 加执行分支 |

## 关于"持续选通"

板上 BL、SL、WL 的电压接 4200 的 SMU，芯片只负责在脉冲期间把选中的器件接进回路。所以和 I1000 一样，要把同一条 WRITEB 重复很多遍，让器件在 4200 施压、测量的这段时间里一直被选通。一键测试里填"选通 s"，程序会按脉宽自动算重复次数；指令区最多 8191 条，1 ms 脉宽下每个器件最长约 8.2 s，要更久就加大脉宽（最大约 6.5 ms，约 53 s）。

## 从 FPGA 工程确认的事实（I1003_NOC_1012）

| 报文 | 作用 |
|---|---|
| `00 01` / `80 01` | 读 / 写 `noc_in_ready`（FPGA 是否接收芯片输出），复位为 1。同事给的"初始使能"其实是读 |
| `00 02` | 读芯片 `pad_Noc_i_3_Ready` |
| `80 03` / `00 03` | 发 PKG 给芯片 / 读回 FPGA 最后发出的 PKG |
| `00 04` / `80 04` | 读 / 写芯片 `boot_mode` 引脚，复位为 1 |
| `80 00` | **禁止**：bit63 会打开以太网测速模式 |

- 给芯片的时钟都是 10 MHz（RTC 为 6.52 MHz）。
- 芯片输出：FPGA 检测 `noc_in_valid` 上升沿，把 64 位包以 8 字节 UDP 包发给电脑。
- 一个 UDP 包里可以有多帧，decode 逐帧处理（"批量快速发送"依赖这一点）。

## 待确认 / 待修改

- `por_rst_n`、`sys_rst_n` 在 FPGA 里接成常数 1，芯片从未被复位。这是芯片不回包的头号嫌疑，建议 PLL 锁定后再释放，并加一个可由电脑触发的复位地址。
- `noc_out_valid` 固定拉高 10 个周期、不等握手，同一个包可能被芯片接收多次。
- 源节点 30、RGN=0 是推断；回包要回到片外口，需要哪种 RGN/HEADER 手册没写。
- 器件地址里行、列的排法未确认（界面里两种都可选，只测第 0 行时没有区别）。
- 写验证"验证次数"大于 0 时芯片的实际行为未确认，I1000 实验台用的是 0。
