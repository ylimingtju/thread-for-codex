# 隐私说明 / Privacy

Thread for Codex 在本机保存已登记聊天的标识、标题、进展摘要、配对码、状态，以及旧串首次接到项目任务的时间。右侧面板会读取这些聊天的本地状态、模型名称和 Token 计数。点击标题时，系统使用本地 Codex 链接打开对应聊天。这些面板数据在本机处理。

项目中的执行串分工、已确认决定和关联来源保存在本机。执行串接到提问时，相关分工和决定的摘要会作为上下文提供给同一项目内的 Codex 执行串。

派工和聊天仍由 Codex 执行。用户选择的 GitHub、ChatGPT 或其他外部服务各自处理发给它们的数据。工作流也可能在工作区写入计划、审阅记录或临时文件，是否同步或分享这些文件由用户及其工具决定。

## English

This local edition includes a Python stdio MCP server for the conversation panel. The panel records the registered local chat identifiers, titles, task summaries, pairing keys and status in a SQLite database under the user's Codex directory. It reads local Codex records to identify the registered chats and observe their activity and archive status. A click on a registered thread asks the operating system to open its local Codex link. The panel does not send these data to a remote service.

For token usage, the panel stores the first project assignment time for reused chats and reads model names and token counters from registered chats' local session logs. It combines counts on this machine.

Worker responsibilities, confirmed decisions, and their source references are stored locally. On a worker prompt, the plugin provides a summary of relevant responsibilities and decisions as context to the Codex worker chat in the same project.

When these workflows are followed, Codex or configured tools may create local workspace artifacts such as plans, optional scratch/handoff prompt files, review notes, browser oracle results, logs, or scratch files. These artifacts remain on the user's machine unless the user or their tools choose to sync, publish, commit, upload, or share them.

Some workflows may ask Codex to use tools or services already available in the user's environment, such as local repository tools, browser automation, GitHub, ChatGPT, or other configured connectors. Those tools are optional adapters; their own privacy policies and the user's account settings govern any data they handle.

The workflows instruct agents to avoid printing secrets or private data in chat, to prefer local artifacts for sensitive evidence, and to redact or summarize sensitive payloads before external oracle or browser use.
