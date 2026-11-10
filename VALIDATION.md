# v0.4.0 验证记录

本轮新增：原创场景音乐、独立声音设置、边缘闪光/震动/残血反馈、应用图标和显式桌面快捷方式工具。

- 快捷方式工具：在 Windows PowerShell 5.1 下，6 项测试通过，包括真实 `.lnk` 回读与便携目录/源码路径选择。全部测试文件只位于隔离临时目录，验证目标/工作目录/图标回读、普通启动、外来同名避让、更新已有项目链接、检查后文件变化拒绝覆盖。没有通过这些测试创建真实桌面快捷方式。
- 图标：从现有原创幽灵矢量绘制生成 ICO，包含 16/24/32/48/64/128/256 七种尺寸；透明边缘已目视检查，没有桌面截图或私人图标采样。
- PDF：v0.4.0 七页手册完成，中文字体全部嵌入，Poppler 七页渲染并逐页目视验版；`docs/玩法指南.pdf` 与 `output/pdf/玩法指南.pdf` 字节一致。只含原创角色图示，不含桌面采样。证据：`artifacts/manual-v04-validation.json`。
- 源码真实桌面：Windows 10 + 360 DesktopLite，campaign 有界运行 25 秒后正常退出；游戏期间隐藏两个原来源，退出全部恢复，72 个图标几何一致。证据：`artifacts/v04-source-recovery/20261110-165733-source-campaign-normal-296601/result.json`。
- 宿主真实音频设备：低音量播放验证四场景、暂停与静音，`available`、`music_available` 均为 true；本机合成耗时 0.457 秒。证据：`artifacts/audio-preview/host-playback.json`。
- 最终自动回归：`python -m pytest -q`，**311 passed in 21.46s**；结果见 `artifacts/tests-v04.txt`。
- 冻结包只读验证：限制子进程 PATH 为 Windows/System32 与 Windows，诊断及 probe 通过。证据：`artifacts/package-v04-readonly/20261110-170435-1278af/result.json`。
- 冻结包战斗正常退出：有界 18 秒，两个原来源全部恢复，72 个图标几何一致。证据：`artifacts/package-v04-recovery/20261110-170449-package-campaign-normal-85faff/result.json`。
- 冻结包绘画正常退出：有界 12 秒，两个原来源全部恢复，72 个图标几何一致。证据：`artifacts/package-v04-recovery/20261110-170541-package-drawing-normal-f9e7b7/result.json`。
- 冻结包战斗强制结束：只终止验证脚本自行创建的游戏进程，独立守护恢复两个来源，72 个图标几何一致。证据：`artifacts/package-v04-recovery/20261110-170648-package-campaign-crash-ee1d37/result.json`。
- 包日志确认音乐在桌面接管前完成预合成，`music=True`、`effects=True`；本机预合成耗时 0.326 至 0.353 秒。
- 经用户明确授权，在实际当前用户 DesktopDirectory 创建一个“桌面叛乱.lnk”，指向最终 `dist/DesktopKiller/DesktopKiller.exe`。回读确认版本 0.4.0、工作目录为 exe 所在目录、图标为该 exe 的索引 0、参数为空、未设置 RunAs；没有启动游戏或改动其他桌面文件、排列、注册表。证据：`artifacts/shortcut-v04.json`。创建发生在包恢复验收之后，这个新增快捷方式不计入此前 72 项数据。
- 创建快捷方式后再次以冻结包只读 probe 验证，成功读取包含新启动图标的 73 个图标；未隐藏桌面。证据：`artifacts/package-v04-with-shortcut/20261110-171142-713d49/result.json`。
- 包根和 `_internal` 内的 PDF 与最终手册哈希一致，快捷方式辅助文件与源码一致，未夹带测试档案或桌面采样。证据：`artifacts/package-v04-files.json`。
- Windows 11、混合 DPI、长时间压力测试仍待对应环境验收。

以下保留历史验证记录。

# v0.3.0 验证记录

本轮新增：画画模式、换装、永久训练、账号等级、成就、设置、PDF 手册和发行包。

- 截至整合检查，`python -m pytest -q` 已通过 **225 项**，包括 v1→v2 存档迁移、奖励去重、购买失败回滚、结算保存失败反馈与重试、全套角色透明度、绘画多笔弧长均匀采样、唯一图标、无超调、负坐标、小工作区、按下/释放流程（合成输入）、焦点恢复防误提交、天赋实际战斗效果与跨章保持。
- 画画排阵离线耗时：72 图标约 58 ms；128 图标最慢约 295 ms；500 图标约 275 ms。超过 128 图标采用有界近似分配，避免长时间阻塞守护。
- 真桌面画画有界运行：12.106 秒，680 帧，72 图标排成爱心，平均循环工作 10.544 ms、p95 12.195 ms；正常退出。证据：`artifacts/v03-drawing-live/last-run.json`、`runtime/v03-drawing/lease.json`。
- 源码离线整局使用合法操作获得奖励，购买并装备围巾信使、训练一级伤害，保存至隔离测试档案 `runtime/v03-play/profile.json`。玩家默认档案不受影响。
- 上述装扮和训练档案的真实桌面战斗运行 45.090 秒、2,617 帧，约 **58.0 帧/秒**；工作耗时平均 10.832 ms、p95 12.699 ms。退出后两个原来源恢复。证据：`artifacts/v03-play-live/last-run.json`、`runtime/v03-play/lease.json`。不等同于长时间压力验收。
- PDF：`output/pdf/玩法指南.pdf`，6 页，中文字体嵌入，Poppler 全页渲染并逐页检查；仅用原创角色示意，没有用户桌面截图或文件名。证据：`artifacts/manual-validation.json`。
- 新界面静态检查：`artifacts/product-ui/` 包含主菜单、换装、训练、成就、设置、帮助、画画、战斗、暂停、升级、结算。灰色背景仅用于离线查看。

### v0.3.0 便携包

- 冻结 exe 版本资源 0.3.0.0。在仅有 Windows/System32 和 Windows 的 PATH 下，诊断/probe 均 exit 0；frozen=true、72 图标、隐藏测试窗口上传成功。证据：`artifacts/package-v03-readonly/20261110-105642-b5ea1c/result.json`。
- 画画模式正常退出：12 秒，两个原来源恢复，72 个图标全部几何不变。证据：`artifacts/package-v03-recovery/20261110-105744-package-drawing-normal-6a98ce/result.json`。
- 画画模式强制结束：只终止脚本自己创建的游戏，独立冻结守护以 renderer_exit 恢复两个来源，72 个图标几何不变。证据：`artifacts/package-v03-recovery/20261110-105841-package-drawing-crash-866aef/result.json`。
- 战斗模式正常退出：12 秒，所有原来源与图标几何恢复。证据：`artifacts/package-v03-recovery/20261110-105849-package-campaign-normal-ac6e3f/result.json`。
- 包根与 `_internal` 内 PDF 与已验版手册完全一致；15 个原生 DLL 与许可证库存哈希一致；未包含玩家档案、测试截图或桌面采样目录。证据：`artifacts/package-v03-files.json`。

本轮实机模式使用自动演示；手绘键鼠完整链路通过合成输入和原生窗口输入测试，尚未记为真人完整游玩验收。所有本轮桌面租约均已释放。Win11、混合 DPI、长时间压力测试仍待对应环境验收。

以下保留 v0.2.0 历史证据，不代替 v0.3.0 的实机检查。

## v0.2.0 历史验证记录

日期：2026-11-10。宿主：Windows 10 专业版 22H2 / 19045 x64，1920×1080、125% 缩放，360 DesktopLite。

## 已验证

- 桌面融合：用户已确认原位苏醒与离位效果符合预期；正式模式继续使用相同的 Shell 独立透明资源和真实位置。主桌面读取 72 个图标，360 右侧面板随整层隐藏并恢复。
- 自动回归：`python -m pytest -q`，**142 项通过**。覆盖纯战斗逻辑、原位/透明度、复活无副本、少量图标完整通关、三种模式条件、升级与暂停冻结、输入模式切换、三选一、每局一次结算、存档、音效降级、DPI、窗口身份与守护恢复。
- 完整流程模拟：合法移动/脉冲/冲刺/升级操作，不修改生命、伤害、经验或计时。主线三章可通关，单图标和小工作区可通关；新版极速在真实 72 图标布局下约 148–159 秒通关；无尽可跨章并主动结算。报告：`artifacts/balance-real-desktop.json`、`balance-one-icon.json`、`balance-blitz-real-desktop.json`、`balance-blitz-one-icon.json`、`balance-endless.json`。
- 正式模式宿主运行：45 秒自动战斗与透明帧导出成功，正常退出后独立租约确认两个来源均恢复。记录：`artifacts/game-live/last-run.json`、`runtime/game-live/lease.json`。
- 原融合基线正常退出：两个来源在游戏时隐藏，退出全部恢复；72 个图标位置、尺寸、标签矩形完全不变。记录：`artifacts/source-recovery/20261110-093210-source-prototype-normal-eec142/result.json`。
- 正式模式崩溃恢复：仅终止验证脚本创建的游戏子进程，独立恢复进程以 `renderer_exit` 归还两个来源；72 个图标几何不变。记录：`artifacts/source-recovery/20261110-093255-source-game-crash-aa206f/result.json`。
- 输入载体：自有测试窗口验证 1/255 alpha 命中、范围外穿透、原游戏帧不被改变、右键消息被自有窗口吞掉、自动显示不抢焦点。记录：`artifacts/input-carrier-verification.json`。
- 渲染优化：资源加载时统一通道格式，上传使用受格式和跨度检查保护的直接 BGRA 复制，输入载体只处理 alpha 通道。1920×1080 实际游戏帧共 8,294,400 个 BGRA 字节与旧路径完全一致，原 RGBA 不变；证据：`artifacts/present-pixel-parity.json`。自有隐藏窗口 present 均值 26.665 → 7.611 ms；这项微基准不能直接当作实际游戏帧率。
- 优化后实际主线运行：45.123 秒共 2,609 帧，约 **57.8 帧/秒**，循环工作耗时平均 10.126 ms、p95 11.460 ms；原轮次约 29 帧/秒。限时退出后两个来源恢复。证据：`artifacts/game-optimized/last-run.json`、`runtime/game-optimized/lease.json`。这是本机 45 秒结果，不是所有硬件或长时间压力测试的保证。
- 站桩对照：真实缓存 72 图标、seed 14，无移动、无技能、优先进攻升级。主线在 40.07 秒、极速在 37.18 秒生命耗尽；没有修改抽牌或角色状态。与正常走位机器人通关形成对照。
- 离线视觉检查：主菜单、战斗 HUD、升级、暂停、结算五种画面；640×360 和负坐标工作区交互有回归。图像：`artifacts/game-ui/`。灰底是离线查看辅助，并不用于游戏背景。

## 证据边界

Windows 11 已加入 PMv2 manifest、DPI 实际状态检查、Shell 层级遍历、遮挡/虚拟桌面处理及打包守护入口。**没有可用 Win11 实机或虚拟机，本次未做 Win11 实测。** 不能以 Win10 通过代替 Win11，待测项目列于 `compatibility.md`。

整局机器人用于发现死锁和不合理时间安排，不证明真人长期可玩性。当前难度偏宽容；尚未开展多名玩家测试、30 分钟压力测试、干净 Win11 分发测试或混合 DPI 双屏测试。

独立透明帧、PrintWindow 位置参考不等于实际屏幕合成截图。此前 `--capture-screen` 等待桌面前台超时，未计为通过；用户对实际效果的确认与自动恢复验证分别记录。

## 便携包验收

构建产物：`dist/DesktopKiller/DesktopKiller.exe`，必须连同 `_internal` 分发。PyInstaller 6.21.0 onedir 构建完成。

- 独立运行：只对被测子进程使用 `PATH=C:\Windows\System32;C:\Windows`，移除 Python/Conda 环境变量。冻结 exe 的 `--diagnose --window-check` 和 `--probe` 均 exit 0，报告 frozen=true，读取 72 图标，PMv2 和隐藏窗口上传成功。报告：`artifacts/package-readonly/20261110-094107-8fc37c/result.json`。这不等同于干净 Windows 11 实机测试。
- 正常退出：正式模式限时 12 秒，两个来源隐藏后均恢复，72 个图标全部几何一致。报告：`artifacts/package-recovery/20261110-094209-package-game-normal-0fd9a2/result.json`。
- 强制结束：只结束脚本自身创建的 exe 子进程，冻结守护入口独立恢复两个来源，72 个图标几何一致。报告：`artifacts/package-recovery/20261110-094249-package-game-crash-63698c/result.json`。

测试结束后所有本轮显示租约均已释放，未留下运行中的游戏。源码和包的测试档案都在隔离的 `runtime/` 子目录，没有写入玩家默认战绩。
