# Desktop Killer · 桌面叛乱

**v0.3.0** · Windows 桌面动作与创作游戏。

真实桌面图标原位苏醒：在战斗中击碎、断链、成长；或者按住 Ctrl 画一条线，让它们慢慢排成爱心、星形和自己的图案。包含完整主菜单、四种模式、换装、永久训练、成就、存档、设置与中文 PDF 手册。

## 开始

从 [v0.3.0 发行页](https://github.com/3021244161/desktop-killer/releases/tag/v0.3.0) 下载 Windows x64 完整游戏包；源码也可直接在本仓库浏览和下载。

完整解压发布包，双击 `DesktopKiller.exe`，切回桌面选择模式。源码工程的对应文件是 `dist/DesktopKiller/DesktopKiller.exe`。保留同目录 `_internal`，无需安装 Python；不需要管理员权限，不写启动项。

**完整玩法说明：[中文 PDF 手册](docs/玩法指南.pdf)**。发布包内位于 `docs/玩法指南.pdf`；游戏内按 F1，或从“玩法与 PDF 手册”打开。

## 四种模式

| 模式 | 目标 |
| --- | --- |
| 重启行动 | 三章闯关，每章完成断链目标并击破主控，章节间选择补给。 |
| 极速清理 | 180 秒挑战，图标不断回流，145 秒出现主控，目标完成即可结算。 |
| 无限循环 | 章节与敌人持续成长；可从暂停菜单主动结算。 |
| 画画模式 | Ctrl + 按住鼠标左键自由绘画，松开后图标沿线均匀排队；没有敌人和失败计时。 |

主菜单按 1/2/3/4 选模式，C 换装、H 成长训练。战斗用鼠标或 WASD 移动，自动开火；空格/左键脉冲，Shift/右键冲刺。P/Esc 暂停，M 静音，**F5 还原桌面并退出**。

画画支持多笔（最多 16 笔）、Backspace 撤销、R 清空并走回原位、空格隐藏辅助线，以及爱心/星形/圆预设。不同笔划之间不会被连线。图标保留真实尺寸，小图案可能较拥挤；画大一些，间距更舒展。切出应用会取消未完成的一笔并暂停，返回后需手动继续。

## 成长和换装

- **6 套装扮**：小幽灵、围巾信使、像素猫、小机器人、桌面骑士、光笔巫师，各自有不同轮廓和配饰。购买即装备，成就解锁后可手动装备。外观不改变碰撞范围或战斗属性。
- **6 项永久训练**：伤害、生命、移速、护盾、技能冷却、断链速度；每项 4 级，每级改善 5%，最大 20%。从下一局开始生效。
- **账号成长**：新档案有 80 数据晶片。战斗至少 10 秒且有击杀后，结算获得经验和晶片；不是充值货币。保留原有 12 项局内升级与章节奖励。
- **8 项成就**：战斗、通关和绘画都有一次性奖励，部分直接解锁角色。绘画不持续刷取经验或晶片。
- **可靠存档**：旧版战绩/静音自动迁移，结算按局 ID 去重，保存失败的购买会回滚。账号等级、装扮、训练、成就、设置和战绩均留在本机。

## 桌面与恢复

游戏没有移动、删除、重排桌面文件，也不改壁纸、注册表或其他应用状态。图标资源独立读取自 Shell，背景保持实时透明。正式模式空白区域以 1/255 alpha 接收鼠标，最多暗约 0.39%，防止右键同时传给桌面。

普通 Explorer 桌面接管其图标视图；已适配的 360 DesktopLite 同时接管实际绘制层。**360 右侧分类框、时钟和事项面板在游戏期间暂时一起隐藏，退出恢复**；分类框里的图标不参与游戏。无法完整验证身份、资源或位置时拒绝接管。

独立恢复进程就绪后才隐藏原视图。退出、主进程异常、守护超时、来源变化、显示配置改变时恢复；恢复前核对窗口和进程身份。普通应用保持在游戏上方。游戏在主屏工作区进行，其他屏幕图标保留原位。

数据默认位于 `%LOCALAPPDATA%/DesktopKiller/`，可在设置中打开目录。`profile.json` 为档案，`game.log` 为日志；损坏档案会保留备份。中途 F5 退出不保存局内进度，想记录当前成绩时从暂停菜单选择结算。

异常退出后仍需恢复时运行 `DesktopKiller.exe --recover`；源码用 `python main.py --recover`。它只处理本游戏已经不再运行的显示租约。

## 兼容范围与发行内容

目标平台 Windows 10/11 x64，建议 1280×720 以上。当前实机验证环境为 Windows 10 22H2、1920×1080、125%、360 DesktopLite。**Win11 已做 DPI、窗口和恢复适配，但仍未有 Win11 实机验收。** 多屏混合 DPI、其他桌面整理工具和长时间运行需要单独验证。详见 [兼容矩阵](compatibility.md) 与 [验证记录](VALIDATION.md)。

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
```

`--prototype` 仅保留最初融合演示用于回归，不是默认游戏入口。`--export-frames` 是透明游戏层 PNG，不等于真实屏幕合成截图；`--capture-screen` 需要桌面前台，缺失阶段不能计为通过。

代码分为纯规则 `scene.py`、内容配置 `content.py`、视图 `game_view.py/product_view.py`、账号 `profile.py/progression.py/wardrobe.py`、Shell/分层窗/独立恢复适配。本地验收工件、桌面采样和玩家档案不随公开仓库上传，验证文档保留测试场景与结果概要。
