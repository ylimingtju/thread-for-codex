# 项目讨论串

面板按原生聊天 ID 显示本总讨论派发或用户选入的执行串。交付正文保存在原串。

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

- 首次设置、选择旧串和参数见[原生工具说明](runtime-adapters.md#首次命名)。`adopt` 接入已选旧串，JSON 传参方式同 `track`。
- 仅对本次已确认成功的本地创建或直发回执运行 `track(title, summary, thread_id)`。临时 `clientThreadId` 传 `pending_id`，获可信绑定后一次传原 `pending_id` 和正式 `thread_id` 补全原记录。准备中仅可为 `preparing` 或 `blocked`。带派工标记的成功回执可自动补登记，无标记旧派工需核对目标与成功回执。改名沿用原 ID。
- `update` 传正式 `thread_id`（准备中用 `pending_id`）、`status`、`summary`。实际派发可记 `running`，受阻记 `blocked`，确需用户决定才记 `waiting` 并附问题。执行串交付记 `review`，总讨论确认本轮交付后记 `completed`。返工或追问后恢复进行中。用户在总讨论面板手动完成或重新打开时，按目标回合核对。重新打开只撤销完成标记。归档须用户明确要求，原生归档成功后可同步 `archived`。
- 本批派工后用本串 `view_key` 调用一次 `director-panel.show_receipt`。回执可见时自行刷新，重新打开按历史恢复，总讨论忙时延后显示新链接。面板打开失败时给出正确标题和可复制的原生链接。

## Worker

- 新建执行串运行 `show`，用本串 `view_key` 调用 `director-panel.show_entry`。登记尚未完成时，下次实际状态更新再取。配对码只传本串面板工具。普通聊天和串内临时助手不自行登记或运行 `init`。
- 新建及接入的旧串，所有面向用户的最终答复（含直接追问、提问和受阻）在正文与成果链接后空一行，末行只写一次 `[← 返回总讨论](codex://threads/<真实总讨论ID>)`。中途进展省略。取本串 `show` 或 `update` 的 `director_id`，未配对可用此次派工附的真实链接，均无法确认则省略。旧标记「↩」沿用原目标。末行补正时保留完整正文、限制和成果链接，无需重做任务。
- 本串 `update` 只传 `status` 和一句 `summary`，由宿主确定本串 ID。实际追问或返工用 `running`，需要用户回答用 `waiting` 并在原串提问，技术阻碍用 `blocked`，交付用 `review`。总讨论负责验收。向其他聊天发消息另按用户授权处理。
