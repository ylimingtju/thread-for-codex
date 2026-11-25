# Thread for Codex · 版本记录 / Release notes

## 1.2.1 · macOS

[macOS v1.2.1（ZIP）](https://github.com/ylimingtju/thread-for-codex/releases/download/v1.2.1/thread-for-codex-macos.zip) · [Windows v1.0.4（ZIP）](https://github.com/ylimingtju/thread-for-codex/releases/download/v1.0.4/thread-for-codex.zip)

### 中文

- **首次设置总讨论时自动命名。** 新聊天的标题为空、是默认占位名或仅复述启动语时，用「项目名 Director」。无法确认项目名时用「项目总讨论」。用户指定的标题优先，已有自定义标题保留，重复启用沿用现名。
- 中英文首页分别标明 macOS 和 Windows 可下载的版本，并在封面下方加入项目介绍视频。

### English

- **Name a main chat on first setup.** If the new chat has no title, has a default title, or just repeats the setup request, the plugin uses “Project Name Director.” If it cannot identify the project, it uses “项目总讨论” (Project main chat). A title you specify takes priority. Existing custom titles are kept, and repeated setup keeps the current title.
- Both READMEs list one downloadable version per platform and show the project introduction video beneath the cover.

## 1.2.0 · macOS

[下载 macOS v1.2.0 / Download for macOS](https://github.com/ylimingtju/thread-for-codex/releases/download/v1.2.0/thread-for-codex-macos.zip) · [Windows 正式版 / Stable v1.0.4](https://github.com/ylimingtju/thread-for-codex/releases/download/v1.0.4/thread-for-codex.zip) · [Windows 试装版 / Preview v1.1.0](https://github.com/ylimingtju/thread-for-codex/archive/5bd50f46f4fbaa7a3074705416137a978a477939.zip)

### 中文

- **派工后可以接着安排工作。** 总讨论发出任务并登记后默认结束本轮，明确要求等待时才持续跟进。执行串答完后，原串链接显示在聊天中的派工回执里。总讨论正忙时，回执等当前轮结束后更新。总讨论可直接引用已有答案，调查、新判断和文件修改交给执行串。
- **在原串查看答复。** 总讨论把问题交给执行串后，收到本轮答复时默认只提供执行串名称和链接。明确要求汇总或比较时，总讨论再整理答复。
- **右侧面板采用透明玻璃分组。** 浅色与深色跟随 Codex 主题。「等你回复」「进行中」「已完成」分别用黄、蓝、绿区分。底部的 Token 用量默认收起，展开可查看各模型的用量和占比。累计范围提示已移除，数字以大写 K 或 M 缩写，最多保留一位小数。
- **减少重复处理。** 派工记录的读取及来源、目标核对使用同一套逻辑。任务列表不变时沿用原分组，用量可以独立更新。任务组与用量区复用折叠样式。

升级时解压 macOS 安装包并运行 `python3 install.py`。在 Codex「设置 → Hooks」审查并信任插件的三条规则，当前任务结束后重启 Codex。v1.2.0 尚无 Windows 真机验证，Windows 正式版和试装版入口见上方。

### English

- **Keep working after assigning a task.** Once the main chat sends and registers an assignment, it ends the turn by default. Ask it to wait when you need the result before continuing. The assignment receipt shows the worker chat link when the reply is ready and the main chat is idle. The main chat can answer from existing results and delegates investigation, new judgments, and file changes.
- **Read answers in the original chat.** After delegating a question and receiving the reply, the main chat provides the worker chat’s name and link by default. Ask the main chat to summarize or compare replies when needed.
- **Transparent task groups in the side panel.** The panel follows the Codex light or dark theme. Yellow, blue, and green distinguish threads waiting for you, in progress, and complete. The token usage row at the bottom starts collapsed. Expand it to see counts and shares by model. The time-range note has been removed, and counts use uppercase K or M with up to one decimal place.
- **Less repeated work.** The dispatch code shares the logic for reading records and checking their source and target. The panel keeps the current groups when the task list stays the same and updates usage independently. Task groups and the usage row share the same disclosure styles.

To update, extract the macOS ZIP and run `python3 install.py`. Review and trust the plugin's three hooks under Settings → Hooks, then restart Codex after your active tasks finish. Windows testing for v1.2.0 is pending. Use the Windows stable or preview links above.

![浅色和深色面板，使用示例数据 · Light and dark panel with fictional data](docs/images/panel-preview.png)

## 1.1.1 · macOS

[下载 macOS v1.1.1 / Download for macOS](https://github.com/ylimingtju/thread-for-codex/releases/download/v1.1.1/thread-for-codex-macos.zip) · [Windows 正式版 / Stable v1.0.4](https://github.com/ylimingtju/thread-for-codex/releases/download/v1.0.4/thread-for-codex.zip) · [Windows 试装版 / Preview v1.1.0](https://github.com/ylimingtju/thread-for-codex/archive/5bd50f46f4fbaa7a3074705416137a978a477939.zip)

### 中文

- **从新答复打开面板。** 总讨论每条新答复末尾都有「打开项目讨论串」。在支持插件链接的 Codex 桌面端，点击即可查看当前总讨论的任务。首次点击时，Codex 可能询问用哪个插件打开。
- 此前仅在本机试用的旧版文件查看器方案已撤回。如果右侧出现两个同名标签，可以关闭多余的标签，保留正在使用的一个。
- **直接在旧执行串追问。** 已登记的执行串在恢复时按聊天 ID 找回所属总讨论，新答复末尾附「← 返回总讨论」。无需重新派工。**强烈建议每个项目只设一个总讨论**，其余聊天用作执行串。
- **补正时保留完整答复。** 正确的末行链接只在本机检查。缺失或指向错误时，插件最多请求模型补正一次，要求保留完整正文和成果链接。如果总讨论只读到补充的链接，会回原串取完整交付再汇总。

升级后，在「设置 → Hooks」审查并信任本插件的 `SessionStart`、`UserPromptSubmit` 和 `Stop`。当前任务结束后，退出并重新打开 Codex，让已有聊天载入更新。[Codex Hooks 说明](https://learn.chatgpt.com/docs/hooks#stop)

momo-land 已在 Windows 11 上验证 v1.1.0 试装版的安装、升级、面板资源和执行串返回链接。Windows 正式版为 v1.0.4，v1.1.0 尚待登录桌面的人工点按验收。[测试记录](https://github.com/ylimingtju/thread-for-codex/pull/3) · [验收进度](https://github.com/ylimingtju/thread-for-codex/issues/2)

### English

- **Open the panel from a new reply.** Each new main-chat reply ends with **打开项目讨论串** (Open project threads). Select it to see that chat’s tasks on the right in a Codex desktop version that supports plugin links. Codex may ask which plugin to use on first click.
- The older file-viewer approach was tried only locally and has been withdrawn. If two tabs with the same name appear on the right, you can close the extra tab and keep the one you’re using.
- **Follow up in an existing worker chat.** When a registered worker resumes, the plugin looks up its main chat by ID and adds **← 返回总讨论** (Back to main chat) to new replies. You can continue in the same chat without a new assignment. **We strongly recommend one main chat per project.**
- **Keep the full answer when correcting a link.** A correct final link needs only a local check. For a missing or incorrect link, the plugin asks for at most one correction, with the full answer and its deliverable links. If the main chat receives only a link, it reads the worker’s full reply before summarizing.

After upgrading, review and trust the plugin’s `SessionStart`, `UserPromptSubmit`, and `Stop` hooks under Settings → Hooks. When your active tasks finish, quit and reopen Codex to load the update in existing chats. [Codex hook reference](https://learn.chatgpt.com/docs/hooks#stop)

momo-land tested the v1.1.0 preview on Windows 11, including installation, upgrade, panel resource access, and worker return links. Windows v1.0.4 remains the stable release pending a signed-in desktop check. [Test results](https://github.com/ylimingtju/thread-for-codex/pull/3) · [Verification status](https://github.com/ylimingtju/thread-for-codex/issues/2)

## 1.1.0 · macOS

[下载 macOS v1.1.0 / Download for macOS](https://github.com/ylimingtju/thread-for-codex/releases/download/v1.1.0/thread-for-codex-macos.zip) · [下载 Windows v1.0.4 / Download for Windows](https://github.com/ylimingtju/thread-for-codex/releases/download/v1.0.4/thread-for-codex.zip)

Windows 当前发行版为 v1.0.4。momo-land 完成真机确认后再发布 Windows v1.1.0。 [更新说明、macOS 实测与使用指南](docs/release-v1.1.0.md#zh)

Windows stays on v1.0.4 until momo-land confirms v1.1.0 on a Windows machine. [Release notes, macOS benchmarks and user guide](docs/release-v1.1.0.md#en)

总讨论直接回答有明确出处的已有结论，把需要新判断或修改的工作分派给执行串。续派时沿用原串上下文，回报时概括本轮结果并保留原串入口。九个专项技能仍可按需调用，普通派工省去流程声明和重复记录。新旧执行串在每条面向用户的答复末尾提供「← 返回总讨论」链接。

The main chat answers questions about established results and delegates work that calls for a new judgment or a change. Follow-ups reuse the original thread. The main chat summarizes the current assignment and links to the source when helpful. All nine specialist skills remain available. Routine assignments can proceed without extra workflow messages or duplicate records. Each reply to the user in a new or existing worker chat ends with a link back to its main discussion.

## 1.0.4

支持 Windows 版 Codex 桌面端。安装器可使用桌面端自带的命令行，并将面板绑定到安装时使用的 Python。面板支持中文任务数据和通过 Windows 打开原生聊天。

Added support for Codex desktop on Windows. The installer can use the bundled Codex CLI and configures the panel to use the Python executable that ran the installer. The panel handles Unicode task data and opens native chats through Windows.

## 1.0.3

- 在新项目或已有项目的聊天中发送「将此线程作为该项目的总讨论」即可启动。也可以在同一条消息里附上第一个任务。原来的技能命令仍然可用。
- 修复聊天中「项目讨论串」入口下方的大片留白。单行入口的初始高度为 49 像素，内容增多时可随之展开。

- In a new or existing project, say “Use this chat as the main discussion for this project.” You can include the first task in the same message. The original skill command still works.
- Fixed excess space below the project threads card in chat. The card starts at 49 pixels and grows with its content.

## 1.0.2

插件图标换为「换乘线」。深蓝底上的三条线路与白色换乘环呼应项目总讨论与执行串。

The new plugin icon uses three transit lines and a white interchange ring on a navy background to represent a project chat and its threads.

## 1.0.1

总讨论在所有受支持的推理强度下都可以派工、追问和验收。新建总讨论时仍默认使用 `xhigh`（模型支持时）。在 Codex 中手动调整强度后，继续对话或收到执行串回报时都会沿用当前选择。

The main chat can assign tasks, follow up, and accept results at any supported reasoning effort. New main chats still default to `xhigh` where supported. Continuing a chat or receiving a worker callback preserves the effort you selected in Codex.

## 1.0.0

### 中文

首个独立编号版本，适用于 macOS 版 Codex。总讨论可向新串或已有聊天派工。右侧面板按「等你回复」「进行中」「已完成」分组，点开标题可回原串继续问。面板跟随聊天改名，并按模型累计项目的输入和输出 Token。

下载源码包并解压，在根目录运行 `python3 install.py`。[中文安装说明](README.md#安装与启动)

### English

The first independently numbered release for Codex on macOS. A main project chat can assign tasks to new or existing threads. The sidebar groups them by waiting for a reply, in progress, or complete. Open a thread to follow up, even after completion. Thread names follow Codex, and the panel tracks project input and output tokens by model.

Extract the source ZIP and run `python3 install.py` from its root. [English installation guide](README.en.md#install-and-start)
