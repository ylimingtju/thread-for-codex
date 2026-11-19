# Codex Goals Integration

A native Codex Goal tracks a persistent objective in its owning chat. Create one only when the user explicitly asks for a Goal and the host supports it. A project's size or number of turns does not initiate one.

## Goal Fit Test

Identify the intended end state, what will demonstrate completion, and the bounds the user set. Where the user explicitly requests a Goal but leaves its outcome materially ambiguous, clarify that point. Set a token budget only if the user specified one.

## Operations

- When resuming an existing Goal, inspect its actual status and confirm that its scope matches the work. Preserve an unrelated Goal. Use the current host's permitted operations.
- Keep changes within the Goal's agreed scope. Mark it complete only when its actual outcome has been reached and the stated constraints hold. Handle a paused or blocked Goal according to the user's instruction and the host's status rules.
- When several execution chats contribute, keep a single owner for the Goal. The owner can use their actual final replies or agreed output to determine what is still open. A finished Goal and a finished chat are separate states. Archive only at the user's request.

## Research Goals

Use explicit questions, acceptable sources, and a stopping condition for research. State what evidence is missing if the target cannot be answered. Keep original findings in their chats. Deliver a separate report if one was agreed.
