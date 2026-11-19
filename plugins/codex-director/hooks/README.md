# 执行串的返回链接

启用 `UserPromptSubmit` 后，Codex 每轮按当前聊天 ID 查询本机的派工记录。已登记的执行串会收到本轮回复末尾应使用的总讨论链接，同目录的普通聊天不会收到提示。该操作只读，不保存提问内容。

在 Codex 的「设置 → Hooks」中可查看并信任此插件的 `UserPromptSubmit`。派工消息也携带返回链接，供尚在登记的新串使用。具体约定见[执行串规则](../skills/codex-director/references/project-panel.md#worker)。
