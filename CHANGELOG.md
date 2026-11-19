# Thread for Codex · 版本记录 / Release notes

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
