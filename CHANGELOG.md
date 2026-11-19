# Thread for Codex · 版本记录 / Release notes

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
