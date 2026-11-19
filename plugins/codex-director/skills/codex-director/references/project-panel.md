# 项目讨论串

面板按总讨论与执行串的真实 ID 关联。登记、更新和显示面板都属于协调工作。运行命令时，用当前加载的 `skills/codex-director` 目录向上两级作为插件根目录，调用其中的 `panel_state.py`。在执行操作的原生聊天内运行，保留宿主提供的 `CODEX_THREAD_ID`。命令中的 JSON 作为一个参数传入，使用安全的参数传递方式，尤其是标题、问题或摘要来自用户时。

下文命令以 macOS 为例。在 Windows 上，从已加载的插件根目录读取 `.mcp.json`，使用其中为面板配置的 Python 完整路径。PowerShell 中，直接传递标题或 JSON 字符串给标准输入，避免原生命令的参数解析改写双引号和非 ASCII 字符。例如，把 `$pluginRoot` 设为插件根目录，再运行：

```powershell
$config = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $pluginRoot '.mcp.json') | ConvertFrom-Json
$python = $config.mcpServers.'director-panel'.command
$state = Join-Path $pluginRoot 'panel_state.py'
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = $OutputEncoding
'总讨论标题' | & $python -B -X utf8 $state init --stdin
```

执行 `track` 或 `update` 时，将字段构造成 PowerShell 哈希表，经 `ConvertTo-Json -Compress` 后通过管道传给对应操作的 `--stdin`。执行 `show` 时直接运行 `& $python -B -X utf8 $state show`。

## Director

1. **初始化。** 首次启动时，按真实 ID 读取当前聊天在 Codex 中的名称并置顶；仅首次新建且未选定名称时设置默认标题，运行 `python3 -B <插件根>/panel_state.py init '总讨论标题'`。用返回的 `view_key` 调用 `director-panel` 的 `show_entry` 展示入口，再调用 `show_panel` 打开右侧面板。若已有本串登记，沿用原配对和执行串。日常对话沿用面板，用户主动关闭后，等用户要求再打开。只发启动句时，就在这里等待；附有任务时直接处理。
2. **选择执行串。** 有具体任务时，优先续用本总讨论中已获用户授权、分工吻合的原串。「将此线程作为该项目的总讨论」沿用按需新建或续用执行串的授权，适用于当前项目后续的具体任务。对于尚未指定或确认过的历史聊天，用原生列表只读查找本项目相关候选，保留原名，只让用户确认相关对象一次；用户已明确点名且能唯一定位的，直接使用。仅凭同目录或标题相似不取得发送权限。对独立任务或需要独立判断的复核，按用户授权另开串。

   **登记派工。** 用户授权新建执行串时，调用 `create_thread`。用户授权向已有的本地聊天派工时，调用 `send_message_to_thread`，消息首行写 `【Director 派工】第三章审核`（将“第三章审核”换成本次任务标题），下一行起写具体任务。此标记仅用于分配任务，询问进度和回报结果时省略。

   创建或发送成功后，在总讨论运行 `python3 -B <插件根>/panel_state.py track '<JSON>'`。传入回执中的正式 `thread_id`、聊天标题 `title` 和简短的任务进展 `summary`。总讨论和执行串均以 Codex 中的当前名称展示。手动改名后，继续用同一 ID 更新原记录，保留现有派工关系。新串如果只返回 `clientThreadId`，先作为 `pending_id` 登记，取得正式 ID 后在同一次 `track` 中传入这两个 ID。

   面板会根据本总讨论成功发送的带标记派工记录自动补登记。旧版本已派发的无标记任务，可用本总讨论的成功发送回执和对应执行串 ID 调用同一条 `track` 补登记。发送失败或结果不明时，报告实际情况，不登记，也不自动重发。发送成功但登记失败时，只重试登记。原生归档状态保持有效。

   **旧串的返回入口。** 在正常派工消息的最后单列 `[↩ 返回总讨论](codex://threads/<本次总讨论真实 ID>)`，并在正文里请执行串把同一个链接放在最终答复末尾。已结束的回合等下次派工时再附链接。不要为导航单独发消息、开文件标签或展示入口卡片。
3. **更新状态。** 在已有的跟进、回报和验收动作中调用 `python3 -B <插件根>/panel_state.py update '<JSON>'`。总讨论传入登记的 `thread_id`（仍在准备中时用 `pending_id`）、`status` 和简短的 `summary`。有具体进展或收到追问用 `running`；有技术阻碍用 `blocked`；只有确实需要用户决定时用 `waiting`，并将要回答的问题写进摘要。执行串交付后用 `review`，待总讨论读取子串最终回复并按任务约定验收后用 `completed`。登记和状态更新重试时沿用原 ID。面板自行刷新；不要为刷新界面发起模型轮询或设置定时任务。
4. **保留和归档。** 完成、取消、停滞或改派时保留原生聊天，并将保留状态记为 `retained`。用户对已完成任务追问时继续用原串，恢复 `running`，回答后重新确认结果。只有用户明确要求归档时，才对指定 ID 执行原生归档；成功后更新面板为 `archived`。用户在 Codex 自行归档的，尊重原生状态。临时 helper 的关闭与工作区文件清理仍按各自规则执行。

如果没有单独创建聊天的权限或当前宿主未返回真实句柄，不展示推测出来的执行串。初始化、配对或更新失败时说明实际情况，保留已经创建的聊天；恢复时使用已有 ID 补登记。

## Worker

只在 Director 明确分派的独立执行串中使用面板。收到带「↩ 返回总讨论」链接的旧串派工时，把该链接单列在最终答复末尾。Director 新建的执行串使用入口卡片：执行 `python3 -B <插件根>/panel_state.py show`，使用当前工作串自己的 `view_key` 调用 `director-panel` 的 `show_entry`。如果新串先于父串登记启动，在下一次状态更新时再次取码并展示入口。工作串不能用父串配对码，也不应调用 `init`。

在自己的执行串内调用 `update` 时省略 `thread_id`，宿主身份会定位到当前执行串。只有明确需要用户回答时记录 `waiting` 和问题原文，再在原生聊天提问；其他阻碍记录 `blocked`。收到用户在原串的追问时记录 `running`；交付最终回答时记录 `review` 和一句结果，由总讨论读取回复后确认完成。任务继续使用原生聊天输入框。普通独立聊天和 worker 内部启动的临时子代理无需登记。
