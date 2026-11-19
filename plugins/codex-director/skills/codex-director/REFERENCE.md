# 总讨论按需参考

总讨论日常使用[主规则](SKILL.md)。首次配对、派工回执与状态字段见[项目面板](references/project-panel.md)。选择讨论串、等待和读取历史结果见[桌面端工具](references/runtime-adapters.md)。

## 交接示例

- 同串续办：「按刚改过的第三章，再看第 382 行。」若该串手里只有上一稿，补上修改稿的位置或修订号。原串已经知道的研究背景和交付格式沿用即可。
- 换串接手：把上游已交付的具体版本交给下游，指出需要处理的部分、允许的操作及用户要看到的结果。上游仍在编辑时先明确哪一份是可用版本。
- 独立复核：可让审核串先根据对应版本自行判断；遇到与实现串不同的结论再对照双方依据。向用户概括实质分歧及其影响。
- 旧串已有交接文档、独立审查要求或用户指定交付格式时，接着完成已有约定。新任务按本轮需要交代上下文。已登记的同一聊天可以有多轮派工，认领结果以最新一次对应的请求为准。

## 专项入口

用户点名、旧简报明确约定，或当前工作确实需要时，执行串可使用下列原调用名。普通派工可直接在原有聊天中进行。需要时只读取相应入口。

| 入口 | 适用工作 |
|---|---|
| [director-investigate](../director-investigate/SKILL.md) | 调查事实、追踪原因与证据 |
| [director-deep-plan](../director-deep-plan/SKILL.md) | 对多约束任务制定实施方案 |
| [director-build](../director-build/SKILL.md) | 实现指定功能并交付 |
| [director-review](../director-review/SKILL.md) | 对指定版本作独立审查 |
| [director-refactor](../director-refactor/SKILL.md) | 在指定边界内调整代码结构 |
| [director-optimize](../director-optimize/SKILL.md) | 度量并改善性能 |
| [director-orchestrate](../director-orchestrate/SKILL.md) | 协调多项存在依赖的交付 |
| [director-dynamic-workflow](../director-dynamic-workflow/SKILL.md) | 根据中间结果调整后续分工 |
| [director-browser-oracle](../director-browser-oracle/SKILL.md) | 在外部分享已获授权时通过浏览器取得第二意见 |

专项技能可用 `$codex-director:director-review` 这样的完整名称调用。具体模型和权限沿用用户及项目设置，涉及外部发送时按目标、内容和授权范围执行。
