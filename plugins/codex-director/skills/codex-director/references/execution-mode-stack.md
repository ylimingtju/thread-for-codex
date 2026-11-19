# Execution Mode Stack

The main chat coordinates the project. Keep the thread rules in [the Director skill](../SKILL.md) in force when using a specialist guide.

## Selection Order

1. Honor the user's named chat. Otherwise reuse the registered worker that owns the subject. Start another chat only within the user's authorization when distinct ownership, independent judgment, or lasting context warrants it.
2. The main chat can give a status, point to an existing result, or summarize an already confirmed answer. New investigation, editing, testing, or substantive analysis belongs in an execution chat. Assign an uncertain case instead of starting an investigation in the main chat.
3. Send the actual request to the chosen chat. For an existing worker add only changed inputs or missing constraints. For a new worker include the necessary source, version, scope, and expected outcome.
4. Dispatch independent items together. Sequence an item that consumes another worker's output after the producer has delivered the relevant version. Keep one writer per shared output.

## How Workflow Playbooks Fit

Choose the matching guide when a user asks for its specialty or the task calls for its method. An execution chat can handle the full assignment. Add a helper for a distinct contribution when supported, and keep independent review separate from authorship. Ordinary collaboration uses the registered chats and the project panel.

Use [dynamic workflow](dynamic-workflow-integration.md) for an explicitly requested structured handoff or to resume an existing one. Use [Goals](goals-integration.md) when the user explicitly requests a native Goal. External review follows its own disclosure scope.

## Completion Rule

Match the actual worker reply to this assignment. A complete identified final reply is sufficient for ordinary work. Resolve a missing, clipped, contradictory, or older reply using the narrowest relevant source. Summarize findings, decisions, and material gaps in the main chat. Keep the original reply in the worker chat and retain it for follow-up. Archive only on the user's instruction.
