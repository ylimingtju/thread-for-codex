# Thread for Codex

**受 Claude Projects 启发，Thread for Codex 让你在项目总讨论里分派任务，点开对应讨论串就能继续追问。**  
Inspired by Claude Projects, Thread for Codex lets you delegate tasks from one project chat and follow up in each thread.

中文 · [English](README.en.md)

| 系统 | 可下载版本 | 安装包 |
| --- | --- | --- |
| macOS | **v1.4.0** | [下载 ZIP](https://github.com/ylimingtju/thread-for-codex/releases/download/v1.4.0/thread-for-codex-macos.zip) |
| Windows | **v1.1.0** | [下载 ZIP](https://github.com/ylimingtju/thread-for-codex/releases/download/v1.1.0/thread-for-codex-windows.zip) |

[安装说明](#安装与启动) · [v1.4.0 更新说明](CHANGELOG.md#v140--macos) · [早期版本实测与常见问题](docs/release-v1.1.0.md#zh)

下文的派工、项目决定同步和面板操作说明适用于 macOS v1.4.0。Windows 当前发布版本为 v1.1.0。

![Thread for Codex：主线统筹，分线追问](docs/images/github-cover.jpg)

**项目介绍视频（8 秒）**

https://github.com/user-attachments/assets/1d1d60cf-e0bc-42ef-a01a-5aa561a90f22

Thread for Codex 是适用于 macOS 和 Windows 的 Codex 项目讨论串插件。比如做一份城市步行指南，可以在总讨论里定方向，让一个串规划路线、另一个串核对地图。路线串需要你选河畔还是老城时，问题会直接出现在右侧。点标题即可在原串答复。

总讨论会记录各串的长期分工和已确认决定。新任务按分工派发，续改会参考最近一次派工。执行串首次提问时收到项目摘要，之后随提问同步变更。

## 安装与启动

需要已登录的 Codex 桌面端、支持 `codex plugin` 的 Codex 命令行，以及 Python 3.9 或以上。Python 部分只使用标准库。

1. 从上方下载对应系统的 ZIP 并解压。macOS 也可用 Git 检出标签 `v1.4.0`。Windows ZIP 使用经过 Windows 11 测试的提交 `5bd50f4`。在源码根目录运行对应命令。macOS 用户请选一个准备长期保留的目录。

   | 系统 | 安装命令 |
   | --- | --- |
   | Windows PowerShell | `py -3 .\install.py` |
   | macOS | `python3 install.py` |

   Windows 上也可用 `python .\install.py`，或使用已有 Python 的完整路径，例如 `& 'C:\Python312\python.exe' .\install.py`。安装器优先使用 Microsoft Store 版 Codex 自带的命令行，再查找 PATH 中的 `codex.exe` 和常见的独立安装路径。也可以加 `--codex 'C:\path\to\codex.exe'` 手动指定。

2. 推荐每个项目只设一个总讨论，其余聊天用作执行串。在新项目或旧项目中，进入选定的聊天并发送下面这句话。

   ```text
   将此线程作为该项目的总讨论。
   ```

   也可在输入框选中并发送 Thread for Codex 插件或其主技能。若项目已有总讨论或本串已有归属，会先请你选择。需要默认标题时使用 Codex 的项目显示名，如「城市步行指南 Director」，你也可以直接指定名称。已有自定义标题会保留。首次登记后，可逐项选择要接入的旧串，另行决定是否改名。已接入但还未派工的聊天显示为「待派工」。

3. 接着说具体任务，例如「让路线串列出两个周末方案，让地图串核对沿途站点」。总讨论首次启动时会置顶，并打开右侧的「项目讨论串」。点总讨论新答复末尾的「打开项目讨论串」可重新打开右侧面板，首次点击时 Codex 可能询问用哪个插件打开。点执行串答复末尾的「← 返回总讨论」即可回去。

问「路线串上次推荐了哪条路」，总讨论可以引用已有的明确答复。说「下雨了，请重新选一条路」，总讨论会交回路线串。目标正在执行、已有队列或忙闲不明时，独立任务进入其原生队尾，回执显示「已排队」。前项结束后，Codex 另起一轮处理。派工后你可以继续安排其他事，回执会在总讨论空闲时显示已回复的原串链接。需要等待、汇总或比较时，可以明确提出。

新建总讨论时，如果你没有选择推理强度，插件默认使用 `xhigh`（模型支持时）。已有聊天沿用当前设置。你可以随时调整强度，各档都能正常派工、追问和验收。

升级时，从上方下载本系统的安装包，解压后在源码根目录重新运行安装命令。macOS Git 用户可用 `git fetch --tags` 获取标签，再检出 `v1.4.0`。macOS 安装后，请在 Codex「设置 → Hooks」审查并信任插件的三条规则，然后在当前任务结束后退出并重新打开 Codex。已有执行串可以直接追问。Windows 安装器会在 Codex 数据目录下生成本机插件源，并记录安装所用的 Python 路径。移动或更换 Python 后，用新路径重新运行安装程序。

## 在侧栏里能做什么

| 你想做的事 | 怎么做 |
| --- | --- |
| 查看当前进度 | 右栏分为「等你回复」「进行中」「已回复」「已完成」。待答问题和答复摘要显示在相应条目下，排队等状态标在标题旁。 |
| 查看接入的未派工旧串 | 展开底部的「未派工旧串」。 |
| 标记完成或重新打开 | 在「已回复」或「已完成」的标题旁点「⋯」。重新打开回到「已回复」，保留摘要，原串收到新追问后才开始新一轮。 |
| 继续用旧串 | 在总讨论里点名已用过的串，同名时附聊天链接。派工成功后，它会出现在侧栏，保留原来的上下文。 |
| 追问已完成的任务 | 展开「已完成」，点标题进入原生聊天，用原来的输入框继续问。新一轮追问会让该串回到「进行中」。归档由你决定。 |
| 按模型查看用量 | 点开「Token 用量」看输入、输出和合计。总讨论与已登记执行串计入统计，旧串从首次派工起算。中途换模型会分开累计，记录缺失时会注明。 |

面板按实际派工或用户接入关系列出讨论串。两个总讨论即使共用同一个目录，也各自显示自己的任务。手动给聊天改名后，面板会在刷新时显示新名称。

## 本机数据与版本切换

面板记录保存在 `~/.codex/codex-director/panel.sqlite3`；设置了 `CODEX_HOME` 时使用相应目录。面板从 Codex 本机记录读取任务状态和 Token 用量，刷新时无需调用模型。具体数据范围见 [隐私说明](PRIVACY.md)。

如果装过作者原版，安装器会保留它并启用 Thread for Codex。要切回原版，在安装命令后加 `--restore-original`。若已打开的 Codex 仍显示旧插件入口，保存工作后重新打开应用。

## 来源与许可

Thread for Codex 从 `1.0.0` 起独立编号，保留原来的技能调用名，方便已有项目继续使用。工作流基于 Claire Novotny LLC 的 [Codex Director 0.8.18](https://github.com/novotnyllc/codex-director/tree/f3470cd1b8cdf45ebff110ea22ca5c311674841c)，对话侧栏的接入方式参考了 [Codex Agent Panel](https://github.com/ylimingtju/codex-agent-panel)。

[Claude Projects 讨论串的官方说明](https://code.claude.com/docs/en/claude-projects#how-a-project-is-organized) · [MIT 许可证](LICENSE) · [版本说明](CHANGELOG.md)
