# Windows 兼容与分发验证

本文件记录系统适配的证据和复验步骤，不把 API 可用性当作整款游戏已经在某个系统实测通过。

v0.3.0 已在本机完成独立便携包诊断、战斗正常退出、画画正常退出和画画主进程异常结束恢复；均确认两个来源恢复及 72 图标几何不变。Ctrl/逻辑鼠标持续状态、新菜单与存档成长功能已纳入回归。最新证据见 `VALIDATION.md`；下面的 Win11 待测状态不因 Win10 通过而改变。

| 环境 | 当前状态 |
| --- | --- |
| Windows 10 专业版 22H2，build 19045，x64，1920×1080，125% | 本机环境；已有真实桌面融合与正常/异常恢复证据；本次额外验证 DPI、隐藏测试窗口和计时器 |
| Windows 11 x64 | 目标平台，尚未实机/虚拟机验收；下面列出明确复验步骤 |
| Windows 10 1809+ 其他版本 | 使用的基础 API 可用；未逐版本实测 |
| Windows ARM64、远程桌面、Server、非 Explorer 替代 Shell | 未验证，不宣称支持 |
| 360 DesktopLite | 本机已识别实际绘制层与 DTF 布局；全部主桌面图标必须通过实时位置验证；分类框/时钟等随整层暂时隐藏，退出恢复 |
| 其他第三方桌面整理/替代绘制程序 | 未适配，不应把底层 Explorer 布局当作可见桌面的通过证据 |

2026-11-10 只读环境检查：Hyper-V 中有 **0 台虚拟机**；WSL 为 Ubuntu 和 docker-desktop，没有可用 Windows 11 来宾；未发现 VMware/VirtualBox 安装目录。没有下载安装系统镜像或修改宿主设置。

本机诊断文件为 `artifacts/windows-diagnostics-2026-11-10.json`。其中 PMv2 已确认；自有、不可见的 16×16 分层窗口成功接收 BGRA 图像，随后释放；30 帧计时探针唤醒偏差中位数 0.447 ms、最大 0.991 ms。这个数字是计时探针结果，**不是战斗帧率指标**。

## 已做的系统适配

- 打包 manifest 声明 `PerMonitorV2`。源码入口在导入 pygame 前设置 DPI，并检查实际线程 context；API 返回 FALSE 不会被当作成功。进程默认模式已由 launcher/manifest 固定时，验证或设置尚未创建 GUI 的当前线程；仍失败则停止。微软建议 manifest 声明，且明确 API 失败返回 FALSE。[DPI 声明](https://learn.microsoft.com/en-us/windows/win32/hidpi/setting-the-default-dpi-awareness-for-a-process)、[API 返回规则](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setprocessdpiawarenesscontext)
- 位置及资源仍通过 Shell COM 获取；图标矩形使用真实 ListView 查询。覆盖层定位会遍历 Progman/WorkerW 下的实际 Shell 视图，不依赖 DefView 恰好是直接子窗口。Windows 私有窗口层级不能视作稳定公开契约；若找不到实际图标视图，必须在隐藏前报错。[IFolderView](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nn-shobjidl_core-ifolderview)
- 使用真正的逐像素 alpha 和预乘 BGRA，覆盖层保持非激活、非置顶程序窗口；不改 Explorer 父子关系，不设置黑色色键。[UpdateLayeredWindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-updatelayeredwindow)
- 按键和鼠标仅在桌面前台轮询；普通应用前台时不会查询其按键状态。点击还需命中桌面/游戏层，防止把其他应用和任务栏当作技能目标。使用最高位持续状态，自行检测边沿；恢复桌面焦点时先建立基线，避免重放在其他应用中已经按住的点击。支持系统左右鼠标键交换。[GetAsyncKeyState](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getasynckeystate)
- 正式关卡可通过 `input_bounds` 启用仅覆盖主屏工作区的输入载体：空白像素 alpha 为 **1/255**，数学上并非完全透明，最多使下面真实实时壁纸暗约 0.39%。这是避免透明空白右键穿透后弹出原生桌面菜单所需的命中载体；不使用截图、不用色键或全局钩子。`--prototype` 保留真正 alpha=0。用户明确点击输入面时才激活自有游戏窗并重设桌面层顺序；自动展示仍不抢焦点。已用自有 32×32 窗口验证输入命中、范围外穿透、焦点不变和右键消息吞掉，结果见 `artifacts/input-carrier-verification.json`。[分层窗口透明像素命中规则](https://learn.microsoft.com/en-us/windows/win32/winmsg/window-features)
- 优先使用进程自有的高精度 waitable timer，失败时保留成对 begin/end 的计时器回退，不忙等待、不更改电源策略。微软明确 Windows 11 中完全被遮挡的程序不能依赖 `timeBeginPeriod` 持续提供较高分辨率；高精度 waitable timer 标志从 Windows 10 1803 可用。[timeBeginPeriod](https://learn.microsoft.com/en-us/windows/win32/api/timeapi/nf-timeapi-timebeginperiod)、[高精度定时器](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-createwaitabletimerexw)
- DWM 将游戏窗口 cloak 时，停止桌面输入并请求归还显示租约，避免切换虚拟桌面后旧覆盖层不可见但桌面图标仍被隐藏。真实 Win11 虚拟桌面切换仍须按下表验收。[DWM 属性](https://learn.microsoft.com/en-us/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute)、[虚拟桌面行为](https://learn.microsoft.com/en-us/windows/win32/api/shobjidl_core/nn-shobjidl_core-ivirtualdesktopmanager)
- 打包后的恢复进程通过 `DesktopKiller.exe --guardian --watch ...` 专用入口运行；不会把 `.py` 文件路径作为游戏参数递归启动。原始 HWND、进程身份、每层可见状态和独立心跳恢复机制保持不变。

## Windows 11 可复验步骤

在真实 Win11 电脑或已准备好的 Win11 x64 虚拟机执行。首次先用普通 Explorer 桌面；第三方桌面整理程序单列一轮，不能混为同一种环境。记录完整 OS build、显卡/远程会话情况和缩放比例。

源码环境：

```powershell
python scripts/diagnose.py --desktop --window-check --output artifacts/win11-diagnostics.json
python main.py --probe --output artifacts/win11-probe
python -m pytest -q
```

便携包环境（不需要安装 Python）：

```powershell
.\DesktopKiller.exe --diagnose --desktop --window-check --output .\win11-diagnostics.json
.\DesktopKiller.exe --probe --output .\win11-probe
```

诊断和 probe 都不隐藏真实桌面。先检查结果成功，再进行有时限的实际运行；验收时桌面置前，保存 before/idle/departed/restored 图像。

| 编号 | 场景 | 通过标准 |
| --- | --- | --- |
| W11-01 | 100% 与 125% 缩放启动 | 实际图标数量/来源正确，原位大小与标签接续，无两套图标；离位后原处无复制体 |
| W11-02 | 150%/200%、4K、双屏混合 DPI、负坐标副屏 | 图标和鼠标均为物理坐标；不能验证的配置在接管前明确拒绝；不以变换后的错位位置冒充通过 |
| W11-03 | 桌面按住 WASD/方向键/Shift，按 1/2/3、Space、P、M；左右键点击工作区空白 | 持续键和边沿行为正确；每次点击最多触发一次；正式模式右键不弹原生桌面菜单，prototype仍保持原透明命中行为 |
| W11-04 | 切换到记事本/浏览器，输入相同按键、点击窗口/任务栏，再返回桌面 | 普通应用操作不触发游戏输入；返回时不补发旧按键/点击 |
| W11-05 | Win+D、Alt+Tab、虚拟桌面切换、锁屏/解锁 | 不盖住普通应用；适当暂停或结束并恢复；绝不留下被隐藏的桌面源层 |
| W11-06 | 游戏中改变分辨率、缩放、任务栏工作区、连接/断开副屏 | 结束当前接管并恢复原图标，再启动重新读取布局 |
| W11-07 | 正常退出/F5、限时退出、强制结束游戏进程 | 覆盖层消失；所有原始绘制层恢复各自状态；无残留守护进程抢占下一次启动 |
| W11-08 | 在专用测试 VM 内重启 Explorer | 不操作失效/复用 HWND；释放租约，新的 Explorer 可正常显示图标 |
| W11-09 | 无 Python 的干净 Win11 运行便携包、路径含空格和中文 | 双击能开；守护独立就绪；存档和日志在可写用户路径；退出/异常恢复正常 |
| W11-10 | 30 分钟实际关卡，含大量敌人、升级界面、切出应用 | 记录真实帧时间、CPU、内存和 GDI 句柄趋势；计时探针通过不能替代这一项 |

当前 W11-01～W11-10 均为 **待实机验证**。不要根据 Win10 单测或本机 360 桌面通过将它们改为已通过。

## 本地打包

已有 PyInstaller 6.21.0。构建脚本只使用当前解释器及已安装依赖，不自动下载：

```powershell
.\scripts\build.ps1
```

输出是 `dist/DesktopKiller/DesktopKiller.exe` 和同目录的 `_internal`。分发时复制/压缩整个 `DesktopKiller` 目录。保持现有 `Start Desktop Killer.cmd` 作为源码启动方式；便携包直接双击 exe。

2026-11-10 本机便携包已完成构建。隔离 Python/Conda 环境与 PATH 后，exe 的只读 `--diagnose --window-check`、`--probe` 均成功；正式游戏限时正常退出和强制结束恢复也通过，两个图标来源全部恢复、72 个图标几何不变。完整报告路径见 `VALIDATION.md`。这些结果来自上述 Windows 10 宿主，Win11 表格仍保持待验证。

下面的只读检查仅对子进程缩减 PATH 至 Windows/System32 和 Windows，并移除 PYTHON*/CONDA* 环境变量；宿主环境不变。它能发现依赖本机 Python 命令或环境变量的错误，不能代替无 Python 的干净 Win11 实测：

```powershell
python scripts/verify_package_readonly.py --exe dist/DesktopKiller/DesktopKiller.exe
```

源码工程保留以下显式、有限时的真实桌面验证工具；无 `--game` 时回归原融合样机：

```powershell
python scripts/verify_desktop.py --exe dist/DesktopKiller/DesktopKiller.exe --game --duration 12 --output artifacts/package-verification
python scripts/verify_desktop.py --exe dist/DesktopKiller/DesktopKiller.exe --game --duration 12 --crash --output artifacts/package-verification
```

验证包使用 `runtime/verify-package`，源码验证使用 `runtime/verify-source`，不会写入玩家的默认存档目录。每次证据创建独立时间戳子目录，包含 `result.json`；异常分支只结束脚本自己启动的子进程，并核对 PID 和创建时间后才恢复该次租约。
