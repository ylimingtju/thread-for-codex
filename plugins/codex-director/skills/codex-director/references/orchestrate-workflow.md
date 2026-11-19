# Orchestrate Workflow

Use when the user wants several contributions coordinated toward one deliverable.

## Decompose And Dispatch

Identify which item produces each required output, its inputs, and its owner. Reuse suitable existing chats, especially a chat the user named. Send independent items together. Give each shared file or other writable output one owner. Schedule dependent work after its input is available.

For an old chat, send the user's request with any changed version, scope or deadline. For a new chat, include the primary source and enough background to understand the requested result. If explicit independent review is due, assign a distinct reviewer the relevant version and criteria.

## Monitor And Reconcile

While the user awaits the outcome, continue authorized independent work and wait in the active turn for pending workers. Use a bounded native wait with the last cursor where supported. Resume the wait after a timeout while work is outstanding. On a user question or approval request, surface the actual issue. An acknowledgement, progress message, or queued worktree is still in progress. Keep the confirmed receipt and update the same assignment when its actual chat becomes available.

Match each final reply to its dispatch. Accept an identifiable, complete answer directly. Inspect the matching part of the worker chat if the result is missing, clipped, contradictory, ambiguous, or if a critical claim needs checking. Resolve conflicts against the named source or assign a focused follow-up to the appropriate worker. Pass verified outputs to dependent owners.

## Final Rollup

Summarize what the contributions establish, any unresolved decision, and where the user can continue. Keep original answers in their chats. Update an agreed plan or report when it is a deliverable. Existing chat and panel records cover routine coordination. Leave finished execution chats available for follow-up.
