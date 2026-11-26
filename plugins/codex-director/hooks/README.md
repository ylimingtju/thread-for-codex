# 总讨论和执行串的回复末行

在 Codex「设置 → Hooks」或命令行 `/hooks` 中审查并信任 Thread for Codex 的三条规则。它们只读本机派工记录，不保存提问或答复。

- `SessionStart` 在恢复旧串时按聊天 ID 确定它是总讨论还是已登记的执行串。`UserPromptSubmit` 在原串收到新问题时提供同一个链接。总讨论使用「打开项目讨论串」，执行串使用「← 返回总讨论」。派工消息仍附执行串要用的返回链接。
- `Stop` 检查总讨论或已登记执行串本轮答复的末行。正确就结束；漏链或目标错误才请求模型补正一次，保留完整正文和成果链接。Codex 可能同时显示两次答复。宿主没有提供可检查的正文时，跳过本次补正。

升级后若 Codex 将某条规则标为已更改，需要信任该版本才能运行。[执行串规则](../skills/codex-director/references/project-panel.md#worker) · [Codex Hooks](https://learn.chatgpt.com/docs/hooks#stop)
