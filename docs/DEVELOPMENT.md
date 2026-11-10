# 开发与兼容说明

面向构建、调试和兼容性验证。玩家入口在[项目首页](../README.md)。

## 桌面与恢复

游戏没有移动、删除、重排桌面文件，也不改壁纸、注册表或其他应用状态。图标资源独立读取自 Shell，背景保持实时透明。正式模式空白区域以 1/255 alpha 接收鼠标，最多暗约 0.39%，防止右键同时传给桌面。

普通 Explorer 桌面接管其图标视图；已适配的 360 DesktopLite 同时接管实际绘制层。**360 右侧分类框、时钟和事项面板在游戏期间暂时一起隐藏，退出恢复**；分类框里的图标不参与游戏。无法完整验证身份、资源或位置时拒绝接管。

独立恢复进程就绪后才隐藏原视图。退出、主进程异常、守护超时、来源变化、显示配置改变时恢复；恢复前核对窗口和进程身份。普通应用保持在游戏上方。游戏在主屏工作区进行，其他屏幕图标保留原位。

数据默认位于 `%LOCALAPPDATA%/DesktopKiller/`，可在设置中打开目录。`profile.json` 为档案，`game.log` 为日志；损坏档案会保留备份。中途 F5 退出不保存局内进度，想记录当前成绩时从暂停菜单选择结算。

异常退出后仍需恢复时运行 `DesktopKiller.exe --recover`；源码用 `python main.py --recover`。它只处理本游戏已经不再运行的显示租约。

桌面快捷方式是单独的显式工具，不在游戏启动时自动创建。仅在用户要求后运行 `scripts/create_shortcut.ps1`：它通过当前用户 `DesktopDirectory` 获取真实路径，只创建一个“桌面叛乱.lnk”；目标精确属于本项目时可更新，其他同名链接会保留并另选名称。没有 Public Desktop、开机启动、管理员启动或注册表写入。图标由原有幽灵矢量角色生成，源码为 `scripts/build_icon.py`。

## 兼容范围与发行内容

目标平台 Windows 10/11 x64，建议 1280×720 以上。当前实机验证环境为 Windows 10 22H2、1920×1080、125%、360 DesktopLite。**Win11 已做 DPI、窗口和恢复适配，但仍未有 Win11 实机验收。** 多屏混合 DPI、其他桌面整理工具和长时间运行需要单独验证。详见 [兼容矩阵](../compatibility.md) 与 [验证记录](../VALIDATION.md)。

发布包包含 exe、`_internal` 运行依赖、`docs/玩法指南.pdf`、`licenses/` 原许可证和来源清单、版本说明及验证文档。包不含本机桌面采样、私人文件名、玩家档案或测试截图。分发整个文件夹或版本 zip，不单独分发 exe。原生依赖中无法独立证明的少量 revision 已在许可证清单中说明。

## 源码开发与复验

个人 Windows 项目，宿主 PowerShell，64 位 Python 3.10+：

```powershell
python -m pip install -r requirements.txt
python main.py
python -m pytest -q

# 只读环境诊断和资源提取，不隐藏原图标
python main.py --diagnose --desktop --window-check --output artifacts/diagnostics.json
python main.py --probe --no-dialog

# 有时限的战斗或画画验收，结束自动恢复
python main.py --mode campaign --demo --duration 45 --no-dialog
python main.py --mode drawing --demo --duration 12 --export-frames --no-dialog

# 正常/崩溃恢复，只终止验证脚本自行启动的子进程
python scripts/verify_desktop.py --game
python scripts/verify_desktop.py --game --crash

# 构建与发行归档
.\scripts\build.ps1
.\scripts\release.ps1

# 快捷方式先只读确认；最终构建通过且用户要求后再创建
.\scripts\create_shortcut.ps1 -InspectOnly
.\scripts\create_shortcut.ps1
```

`--prototype` 仅保留最初融合演示用于回归，不是默认游戏入口。`--export-frames` 是透明游戏层 PNG，不等于真实屏幕合成截图；`--capture-screen` 需要桌面前台，缺失阶段不能计为通过。

代码分为纯规则 `scene.py`、内容配置 `content.py`、视图 `game_view.py/product_view.py`、账号 `profile.py/progression.py/wardrobe.py`、Shell/分层窗/独立恢复适配。本地验收工件、桌面采样和玩家档案不随公开仓库上传，验证文档保留测试场景与结果概要。
