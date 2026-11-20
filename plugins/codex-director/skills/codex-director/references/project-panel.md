# 项目讨论串

按原生聊天 ID 配对，总讨论只显示自己派发的执行串。聊天保存交付原文，面板记录归属、派工状态和简要进展。派工与等待的原生工具见[原生讨论串工具](runtime-adapters.md)。

## 命令

从实际加载的 `skills/codex-director` 目录向上两级找到插件根目录。在执行操作的原生聊天内运行，使用宿主给该聊天的 `CODEX_THREAD_ID`。标题和 JSON 通过参数或标准输入原样传入。

macOS 中将 `state` 设为插件根目录下 `panel_state.py` 的完整路径，`title` 为原生聊天名称，`payload` 为对应操作的 JSON 文本。按需要选一条。

```sh
python3 -B "$state" init "$title"
python3 -B "$state" track "$payload"
python3 -B "$state" update "$payload"
python3 -B "$state" show
```

Windows PowerShell 中将 `$pluginRoot` 设为插件根目录，使用安装时为面板配置的 Python。先设置编码和路径。

```powershell
$config = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $pluginRoot '.mcp.json') | ConvertFrom-Json
$python = $config.mcpServers.'director-panel'.command
$state = Join-Path $pluginRoot 'panel_state.py'
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $OutputEncoding
```

按当前操作选一条。`$title` 为原生聊天名称，`$fields` 为对应操作的 PowerShell 哈希表。

```powershell
$title | & $python -B -X utf8 $state init --stdin
($fields | ConvertTo-Json -Compress) | & $python -B -X utf8 $state track --stdin
($fields | ConvertTo-Json -Compress) | & $python -B -X utf8 $state update --stdin
& $python -B -X utf8 $state show
```

## Director

1. **初始化。** 推荐每个项目使用一个总讨论，其余聊天作为执行串。用当前聊天名运行 `init`，用返回的本串 `view_key` 调用 `director-panel.show_panel`。已初始化的总讨论沿用原配对。平时只需在每条面向用户的最终答复末尾单列一次 `[打开项目讨论串](https://thread-for-codex.invalid/panel)`，无需另发卡片。用户明确要求立即打开面板时，可直接调用 `show_panel`。
2. **派工消息。** 新串首派和旧串续派均附当前总讨论的真实链接，约定执行串每次面向用户的答复都以它收尾。旧串续派的第一行写 `【Director 派工】<简短任务标题>`。进度询问、结果回报不带派工标记。首次向某个串派工时提供本文件的实际完整路径，指明 Worker 小节。
3. **登记。** 仅在确认本总讨论的本次本地创建或派工成功且目标 ID 匹配后运行 `track`，传 `title`、`summary` 和回执的正式 `thread_id`。只有 `clientThreadId` 时先传 `pending_id`，取得可信绑定后在同一次 `track` 里传原 `pending_id` 和正式 `thread_id`，使原记录可点击。准备中只能标为 `preparing` 或 `blocked`。登记失败只重试登记，创建或发送结果不明时不自动重发。面板可从本总讨论带标记的成功回执补登记；显式接入早期无标记派工时必须核对原派工的目标及成功回执。用户改名后仍按原 ID 关联。
4. **状态。** 总讨论用 `update` 传已登记的 `thread_id`（准备中用 `pending_id`）、`status` 和 `summary`。已发送可写 `running`，摘要只写已知进展。技术阻碍写 `blocked`，确需用户决定时写 `waiting` 并附具体问题。执行串交付写 `review`；总讨论确认匹配最新派工或追问、符合交付要求后才写 `completed`。返工、已完成后继续追问都在原串进入 `running`。用户明确要求归档时，对指定正式 ID 执行原生归档；成功后可用 `archived` 同步。正常交付、停滞或取消都保留聊天。
5. **查看。** 面板按已登记 ID 读取当前聊天名称和最近状态，自行刷新。仅为显示面板无需调用模型或轮询执行串。打开失败时提供正确标题和该串的可复制原生链接。

## Worker

- 在 Director 新建的执行串内运行 `show`，使用执行串自己的 `view_key` 调用 `director-panel.show_entry`；若启动早于登记，在下一次实际状态更新时再取一次。配对码只传给本串面板工具。普通聊天和串内临时助手不运行 `init` 或自行登记。
- 新建和接入的旧执行串遵循同一约定。每次给用户的答复，包括交付、待答问题、遇到阻碍以及完成后在原串直接追问，都在正文和其他成果链接之后，空一行，以可点击的 `[← 返回总讨论](codex://threads/<真实总讨论ID>)` 收尾。每条答复只放一次，中途进展省略。无需为此另发消息或卡片。 如果 Codex 因末行错误请求补正，在最终答复中保留刚才的完整正文、限制和成果链接，再附正确的末行。无需重新执行任务。
- 使用当前执行串已登记的 `director_id`。已有的 `show` 或 `update` 结果包含该字段；尚未完成配对时可沿用本次总讨论实际派工附带的链接。旧消息使用「↩」时只更新显示文字，保留已确认的目标。两处都无法确认时，先省略链接，避免猜测目标或写入占位符。
- 本串运行 `update` 时只传 `status` 与一句 `summary`，由宿主确定本串 ID。直接追问或返工用 `running`，需用户回答用 `waiting` 并在原串提问，技术阻碍用 `blocked`，交付最终结果用 `review`。总讨论负责验收。汇报原文保存在此；更新面板和主动向另一聊天发消息分别遵从各自授权。
