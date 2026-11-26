# Thread for Codex

**Inspired by Claude Projects, Thread for Codex lets you delegate tasks from one project chat and follow up in each thread.**  
受 Claude Projects 启发，Thread for Codex 让你在项目总讨论里分派任务，点开对应讨论串就能继续追问。

[中文](README.md) · English

| Platform | Available version | Installer |
| --- | --- | --- |
| macOS | **v1.2.1** | [Download ZIP](https://github.com/ylimingtju/thread-for-codex/releases/download/v1.2.1/thread-for-codex-macos.zip) |
| Windows | **v1.1.0** | [Download ZIP](https://github.com/ylimingtju/thread-for-codex/releases/download/v1.1.0/thread-for-codex-windows.zip) |

[Installation instructions](#install-and-start) · [v1.2.1 release notes](https://github.com/ylimingtju/thread-for-codex/releases/tag/v1.2.1) · [Earlier benchmarks and FAQ](docs/release-v1.1.0.md#en)

![Thread for Codex — One project chat. Parallel threads.](docs/images/github-cover.jpg)

**Project introduction video (8 seconds)**

https://github.com/user-attachments/assets/1d1d60cf-e0bc-42ef-a01a-5aa561a90f22

Thread for Codex adds a project thread panel to Codex for macOS and Windows. For a city walking guide, you could keep editorial decisions in the main chat, ask one thread to plan the route, and ask another to check the map. When the route planner needs you to choose between the riverfront and the old town, its question appears in the sidebar. Open that thread to answer.

![The light panel shows a question and work in progress. The dark panel shows token counts by model.](docs/images/panel-preview.png)

*The plugin's panel in light and dark mode, rendered with fictional tasks and usage figures. The panel labels are in Chinese.*

## Install and start

You need a signed-in Codex desktop app, a Codex CLI that supports `codex plugin`, and Python 3.9 or later. The plugin uses only the Python standard library.

1. Download the ZIP for your system above and extract it. On macOS, you can also check out the `v1.2.1` tag with Git. The Windows ZIP uses commit `5bd50f4`, tested on Windows 11. On macOS, choose a folder you plan to keep. Run the command for your system from the source folder.

   | System | Install command |
   | --- | --- |
   | Windows PowerShell | `py -3 .\install.py` |
   | macOS | `python3 install.py` |

   On Windows, you can also run `python .\install.py` or use the full path to Python, for example `& 'C:\Python312\python.exe' .\install.py`. The installer looks for `codex.exe` in the Microsoft Store edition of Codex first, then in PATH and the usual standalone CLI location. Use `--codex 'C:\path\to\codex.exe'` to select a specific executable.

2. We recommend one main chat per project. Use the other chats as worker threads. In a new or existing project, open your chosen main chat and send

   ```text
   Use this chat as the main discussion for this project.
   ```

   On macOS v1.2.1, a new main chat with a blank or default title is named “Project Name Director” on first setup. You can specify a title in your setup request, and existing custom titles are kept.

3. Give it a task. For example, “Ask the route planner for two weekend routes and the map thread to check the stops.” On first launch, the plugin pins the main chat and opens the project panel. On macOS v1.2.1, select **打开项目讨论串** (Open project threads) at the end of a new main-chat reply to reopen the panel. Codex may ask which plugin to use the first time. In a worker reply, select **← 返回总讨论** (Back to main chat) to return.

Ask “Which route did the planner recommend?” and the main chat summarizes the existing answer. On macOS v1.2.1, “It's going to rain. Please pick a different route” goes back to the planner. You can give the main chat another task immediately. Once the planner replies and the main chat is idle, the dispatch receipt in the conversation displays a link to the planner. Ask the main chat to wait, summarize, or compare replies when you need it to.

A new main chat defaults to `xhigh` reasoning if the model supports it and you have not selected an effort. An existing chat keeps its current setting. You can change the effort at any time and still assign work, follow up, and accept results.

To update, download the ZIP for your system above, extract it, and rerun the install command. On macOS, Git users can run `git fetch --tags` and check out the macOS version listed above. After installing macOS v1.2.1, review and trust the three plugin hooks under Settings → Hooks, then quit and reopen Codex when your active tasks finish. You can follow up in existing worker chats. The Windows installer prepares a local marketplace in the Codex data directory and records the Python executable used for installation. If you move or replace Python, rerun the installer with its new path.

## Using the sidebar

| What you want to do | Where to go |
| --- | --- |
| Answer a question | **等你回复** lists the questions that need your input. **进行中** includes work delivered by a thread and awaiting review in the main chat. |
| Use an existing thread | Name it in the main chat. Include its chat link if two names match. After a successful assignment, it appears in the panel with its original context. |
| Follow up after completion | Expand **已完成**, open the chat by its title, and type your follow-up. The next turn moves the thread back to **进行中**. You choose when to archive it. |
| See usage by model | Expand **Token 用量** for input, output, and total tokens. Counts include the main chat and registered threads. A reused thread counts from its first project assignment. Model changes are counted separately, and the panel flags gaps in the records. |

Each main chat lists the threads it assigned work to, even if another project chat uses the same folder. Renaming a chat in Codex updates the title on the next panel refresh.

## Local data and switching versions

The panel stores its registry at `~/.codex/codex-director/panel.sqlite3`, or under `CODEX_HOME` if set. It reads task status and token counts from Codex's local records. Refreshing the panel does not call a model. See the [privacy notes](PRIVACY.md).

If the original plugin is installed, the installer keeps it and enables Thread for Codex. To switch back, add `--restore-original` to the install command. If an open Codex window still shows the old plugin entry, save your work and reopen the app.

## Credits and license

Thread for Codex has its own version sequence starting at `1.0.0` and keeps the original skill name for existing projects. The workflow builds on Claire Novotny LLC's [Codex Director 0.8.18](https://github.com/novotnyllc/codex-director/tree/f3470cd1b8cdf45ebff110ea22ca5c311674841c). The sidebar integration follows the approach used by [Codex Agent Panel](https://github.com/ylimingtju/codex-agent-panel).

[How Claude Projects organizes threads](https://code.claude.com/docs/en/claude-projects#how-a-project-is-organized) · [MIT license](LICENSE) · [Release notes](CHANGELOG.md)
