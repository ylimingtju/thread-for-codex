# Thread for Codex · 版本记录 / Release notes

## Unreleased

支持 Windows 版 Codex 桌面端。安装器可使用桌面端自带的命令行，并将面板绑定到安装时使用的 Python。面板支持中文任务数据和通过 Windows 打开原生聊天。

Added support for Codex desktop on Windows. The installer can use the bundled Codex CLI and configures the panel to use the Python executable that ran the installer. The panel handles Unicode task data and opens native chats through Windows.

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
