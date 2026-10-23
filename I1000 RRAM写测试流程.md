# I1000 RRAM写测试流程

## 1. 测试范围

本流程仅用于 RRAM 写 功能测试，覆盖以下两类指令：

●   WRITEB：单 bit 写入

●   WRITED：64 bit 写入

●   CTRL：结束控制指令

## 2. 测试目的

●   验证 WRITEB 单 bit 写入功能是否正常

●   验证 WRITED 64 bit 写入功能是否正常

●   验证写指令启动、执行、结束流程是否正常

●   验证写验证参数 WWV 配置是否生效

●   验证目标 PE、RRAM 阵列、目标地址寻址是否正确

## 3. 相关接口与寄存器

### 3.1 总线接口

●   addr_2core[15:0]

●   data_2core[31:0]

●   op_sc_2core[3:0]

op_sc_2core 定义如下：

●   0：reg write

●   1：reg read

●   2：inst write

●   3：inst read

●   4：data write

●   5：data read

### 3.2 关键寄存器

#### reg[0]

●   Core Status[7:0]

●   启动值：8'b00000001

●   结束值：8'b10000000

如开启中断，使能后可通过中断信号判断执行完成。

#### reg[4]

●   Source Memory Base Address[31:16]

●   Destination Memory Base Address[15:0]

WRITED 使用 Source Memory Base Address 与指令中的 offset 组合得到源地址。

#### reg[8]

●   Wwv Mode[31:24]

○   0：对应 WRITEB

○   1：对应 WRITED

●   Wwv Time Times[23:16]

●   Wwv Timeout Times[15:8]

●   Wwv Times Base[7:0]

写验证脉宽：

Wwv pulse = Wwv Times Base x Wwv Time Times
 

## 4. 指令说明

### 4.1 OP CODE

LOAD  = 0000
 LOADB  = 0001
 STORE  = 0010
 CONFIG = 0011
 WRITEB = 0100
 WRITED = 0101
 READ  = 0110
 CTRL  = 0111
 MUL   = 1000
 MULA  = 1001
 MULI  = 1010
 MULAI  = 1011
 VMULA  = 1101
 VAMUL  = 1110
 VAMULA = 1111
 

### 4.2 CONFIG

汇编格式：

\#CONFIG [R_A][TW][TB][DU][DL]
 CONFIG R_A TW TB DU DL
 

字段说明：

●   R_A：寄存器地址

●   TW：Type Width

●   TB：Type Byte

●   DU：Data Up

●   DL：Data Low

reg[8] 字段分布如下：

●   [31:24]：Wwv Mode

●   [23:16]：Wwv Time Times

●   [15:8]：Wwv Timeout Times

●   [7:0]：Wwv Times Base

### 4.3 WRITEB

汇编格式：

WRITEB P_I T R_I R_RA R_CA
 

说明：

●   P_I：PE 索引

●   T=0：写 0

●   T=1：写 1

●   R_I：RRAM 索引

●   R_RA：RRAM 行地址

●   R_CA：RRAM 列地址

### 4.4 WRITED

汇编格式：

WRITED P_I T R_I R_RA R_CA01 M_SAO
 

说明：

●   P_I：PE 索引

●   T：按设计定义填写

●   R_I：RRAM 索引

●   R_RA：RRAM 行地址

●   R_CA01：半区选择，0 为左半区，1 为右半区

●   M_SAO：源地址 offset

### 4.5 CTRL 结束指令

汇编格式：

CTRL Mk T
 

RRAM 写测试流程中，结束指令使用：

CTRL 00000000 15
 

对应二进制结果：

01110000111100000000000000000000
 

说明：

●   该指令用于标记测试指令序列结束。

●   WRITEB 或 WRITED 指令序列写入完成后，应追加该结束指令。

## 5. 二进制指令输入

测试平台可直接使用 .py 脚本翻译后的 32 位二进制数据写入指令区。

WRITEB 示例：

WRITEB P[0] 0 R[0] 0 0 -> 01000000000000000000000000000000
 WRITEB P[0] 1 R[0] 0 1 -> 01000000000100000000000000000001
 WRITEB P[0] 0 R[0] 0 2 -> 01000000000000000000000000000010
 WRITEB P[0] 1 R[0] 0 3 -> 01000000000100000000000000000011
 

写入指令区时，可直接使用以下二进制串：

01000000000000000000000000000000
 01000000000100000000000000000001
 01000000000000000000000000000010
 01000000000100000000000000000011
 

结束指令按汇编形式写为：

CTRL 00000000 15
 

如采用二进制方式下发，结束指令使用：

01110000111100000000000000000000
 

## 6. 测试前准备

●   确认总线接口读写正常

●   确认指令写入口可正常接收 inst write

●   确认 reg[0]、reg[4]、reg[8] 可正常访问

●   WRITEB 测试前明确目标 PE、RRAM 索引、行地址、列地址

●   WRITED 测试前完成 SRAM 测试数据写入

●   如通过中断判定结束，先打开中断使能

●   准备写后校验手段
 

○   读回校验

○   电性观测

○   测试平台内部比对

## 7. WWV 配置示例

以下示例用于 RRAM 写 测试前的 reg[8] 配置参考。

### 7.1 WRITEB 配置示例

适用场景：单 bit 写测试

reg[8].Wwv Mode = 0
 reg[8].Wwv Time Times = 1
 reg[8].Wwv Timeout Times = 8
 reg[8].Wwv Times Base = 4
 

对应 CONFIG 示例：

\#CONFIG [R_A][TW][TB][DU][DL]
 CONFIG R[8] 1 3 0 1
 CONFIG R[8] 0 3 8 4
 

### 7.2 WRITED 配置示例

适用场景：64 bit 写测试

reg[8].Wwv Mode = 1
 reg[8].Wwv Time Times = 1
 reg[8].Wwv Timeout Times = 8
 reg[8].Wwv Times Base = 4
 

对应 CONFIG 示例：

\#CONFIG [R_A][TW][TB][DU][DL]
 CONFIG R[8] 1 3 1 1
 CONFIG R[8] 0 3 8 4
 

说明：

●   以上为测试示例值。

●   实际测试时可根据器件状态和测试目标调整 Time Times、Timeout Times、Times Base。

## 8. 通用测试流程

\1.    按测试项配置 reg[8] 的 WWV 参数。

\2.    执行 WRITED 时，配置 reg[4].Source Memory Base Address，并准备源数据。

\3.    通过 op_sc_2core = 2 写入测试指令。

\4.    在测试指令序列末尾追加结束指令 CTRL 00000000 15。

\5.    向 reg[0] 写入启动值 8'b00000001。

\6.    等待执行结束：
 

○   接收中断信号，或

○   轮询 reg[0].Core Status = 8'b10000000

\7.    执行结束后进行结果校验。

## 9. WRITEB 测试流程

### 9.1 配置要求

●   reg[8].Wwv Mode = 0

●   reg[8].Wwv Times Base 按测试条件配置

●   reg[8].Wwv Time Times 按测试条件配置

●   reg[8].Wwv Timeout Times 按测试条件配置

### 9.2 指令输入

汇编输入示例：

WRITEB P[0] 0 R[0] 0 0
 WRITEB P[0] 1 R[0] 0 1
 WRITEB P[0] 0 R[0] 0 2
 WRITEB P[0] 1 R[0] 0 3
 CTRL  00000000 15
 

对应二进制输入示例：

01000000000000000000000000000000
 01000000000100000000000000000001
 01000000000000000000000000000010
 01000000000100000000000000000011
 01110000111100000000000000000000
 

### 9.3 执行步骤

\1.    写入 WRITEB 指令。

\2.    追加结束指令 CTRL 00000000 15。

\3.    启动核心执行。

\4.    监测中断或轮询结束状态。

\5.    记录执行状态。

### 9.4 检查项目

●   T=0 时目标单元写 0 正常

●   T=1 时目标单元写 1 正常

●   连续地址写入正常

●   非目标地址无误写

●   到达超时次数上限后系统仍可正常结束