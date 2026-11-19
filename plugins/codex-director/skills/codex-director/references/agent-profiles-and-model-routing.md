# Agent Profiles And Model Routing

## Core Policy

Honor the user's or project's requested model and reasoning effort. An existing main chat or worker keeps the user's chosen settings. A new main chat may default to `xhigh` when supported and no preference was set. Every supported effort can coordinate, delegate, review, and accept results.

For new workers, use settings supported by the active host. If a specific model is required and unavailable, surface the limitation before substitution. Omit optional overrides when inheriting the user's selection. A missing model selector or unreadable setting by itself does not prevent ordinary dispatch.

## Agent Profiles

| Work | Suggested setting when none was requested |
| --- | --- |
| Routine lookup, status, bounded source collection | Inherit, or use a fast available model with low or medium effort. |
| Implementation, investigation, or planning | Use the available main model with high effort for substantive decisions. |
| Independent review, contradictory evidence, hard-to-reverse choices | Consider higher effort based on the decision and the available model. Give the reviewer the actual sources. |

These profiles describe work an existing execution chat can own. An independent reviewer must be separate from the author. A read-only scout may help locate sources, and a helper may own a disjoint change when it will save time. A worker can finish ordinary work directly without a helper, activation message, or model-selection report. Keep credentials, private transcripts, and unrelated context out of handoffs.
