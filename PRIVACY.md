# 隐私说明 / Privacy

Thread for Codex 在本机保存已登记聊天的标识、标题、进展摘要、配对码、状态，以及旧串首次接到项目任务的时间。右侧面板会读取这些聊天的本地状态、模型名称和 Token 计数。点击标题时，macOS 使用本地 Codex 链接打开对应聊天。这些面板数据在本机处理。

派工和聊天仍由 Codex 执行。用户选择的 GitHub、ChatGPT 或其他外部服务各自处理发给它们的数据。工作流也可能在工作区写入计划、审阅记录或临时文件，是否同步或分享这些文件由用户及其工具决定。

## English

This local edition includes a Python stdio MCP server for the conversation panel. The panel records the registered local chat identifiers, titles, task summaries, pairing keys and status in a SQLite database under the user's Codex directory. It reads local Codex records to identify the registered chats and observe their activity and archive status. A click on a registered thread asks macOS to open its local Codex link. The panel does not send these data to a remote service.

For token usage, the panel stores the first project assignment time for reused chats and reads model names and token counters from registered chats' local session logs. It combines counts on this machine.

When these workflows are followed, Codex or configured tools may create local workspace artifacts such as plans, optional scratch/handoff prompt files, review notes, browser oracle results, logs, or scratch files. These artifacts remain on the user's machine unless the user or their tools choose to sync, publish, commit, upload, or share them.

Some workflows may ask Codex to use tools or services already available in the user's environment, such as local repository tools, browser automation, GitHub, ChatGPT, or other configured connectors. Those tools are optional adapters; their own privacy policies and the user's account settings govern any data they handle.

The workflows instruct agents to avoid printing secrets or private data in chat, to prefer local artifacts for sensitive evidence, and to redact or summarize sensitive payloads before external oracle or browser use.
