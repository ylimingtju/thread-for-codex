# 原生讨论串工具

按当前动作查对应小节。面板命令见[项目讨论串](project-panel.md#命令)。

## 首次命名

1. `show` 未配对时，用本串 ID 从 `list_threads` 取 `hostId`、`projectId`、`title`，按同宿主、同项目 ID 匹配 `list_projects` 返回的 `label`。补取标题用 `read_thread(threadId, includeTurns: false)`。
2. 改名前运行 `setup`。`pending_owner` 非空先处理归属，`project_changed` 为真时重新定位。已有总讨论给出原串链接，让用户选择沿用或另设。未定位的总讨论按原生活跃聊天分页核对，仍不明交由用户决定。仅明确另设才用 `init --alongside`。当前执行串不改名或升格。
3. 本轮指定名优先。新串为空、默认占位名或仅复述插件调用或启动语时，取「项目显示名 Director」，独立后缀忽略大小写只保留一个。项目名无法确认用「项目总讨论」，不从目录或相似项目猜测。自定义名保留，来源不明时沿用并说明。
4. 只对当前聊天调用 `set_thread_title`。按成功回执中的实际标题 `init`。失败或回执无标题时读取现名继续登记，仍为空的「项目总讨论」仅作面板显示名。首次需置顶时用 `move_thread_to_sidebar_section(threadId, sectionId: "pinned")`，再用本串 `view_key` 打开 `director-panel.show_panel`。

## 首次选择旧串

- 首次登记成功且本机项目可确认时，分页读 `list_threads(mode: "history", source: "codex", hostId: "local", archived: false, limit: 50)` 到末页，只取宿主、项目、ID 和原名。运行 `candidates` 筛选同项目未归档、未配对的旧串，核对 `project_id`。`complete: false` 时可缩小分页补读，仍不全时说明范围。重复启用跳过。
- 有候选才询问。列可点击的原名，重名附 ID。允许跳过，接入默认留原名。接入及改名分别按用户选定的串办理，改名还需指定目标名；只有明确指向整个已展示清单时才按全清单办理。
- 用户选择后，本轮重取本串和目标的项目、宿主、ID、状态及原名，再用 `candidates` 核对归属。移动、归档、归属或名称变化、目标不唯一时先说明并确认。接入用 `adopt(thread_id, project_id, title)`，无任务记“待派工”。授权改名用 `set_thread_title`，分别报告两项结果。实际派工才按成功回执登记。

## 启动与派工

- 开串须有授权。`list_projects` 确认真实项目 ID，多仓库按指定路径匹配。`create_thread` 选本地环境，工作树须用户要求且项目支持。新串沿用指定模型及强度，旧串默认省略 `model`、`thinking`。
- 发送前按目标取即时快照，核对 `thread.status.type == idle`、无尚未开始的已送达任务、`show` 中目标的 `queued_count == 0` 后才直接 `send_message_to_thread`。快照与发送之间状态仍可能变化。
- 忙、已有队列或忙闲未明时，对已授权且已配对的本地串调用 `director-panel.enqueue_task(threadId, prompt)`。保留派工首行、完整本轮交接和返回链接。以 `queuedSubmissionId` 确认入队，不再 `track`。结果不明先查原串队列，工具不可用或拒绝时如实说明。
- 新建和直发逐串核对成功回执、目标项目或聊天及实际 ID。只有 `clientThreadId` 时先登记准备中，补全正式 ID 后再打开、读取、等待或续派。[登记字段](project-panel.md#director)
- 按用户要求停止时向获授权目标发停止指令，以其确认或原生终止状态为准，保留原串产物。仅用户明确要求时对指定聊天调用 `set_thread_archived`。

## 等待、核对与回报

- 明确要求等结果时，在当前回合用 `wait_threads` 跟进 1–8 个已登记目标。各传实际 `hostId` 和 `threadId`，续等用该目标上次的 `afterCursor`。超时仍在执行就继续，新用户消息可打断。只处理有变化的目标，单串报错不影响其余串。
- 已有完整的本轮答复及所需依据即可确认。旧回合、截断、范围不符或有新追问时，只用 `read_thread` 核对目标串相关回合。其 `cursor` 用于向前翻页。若最新消息只补导航，取同次请求补正前的完整正文。仍无法对应则保留待确认，返工在原串按新回合验收。
- 原生等待限当前回合。平时由回执自行刷新，无需心跳、定时任务或模型轮询。执行串主动反向发消息须有人类对该目标的明确授权。用户可在原串继续追问。
