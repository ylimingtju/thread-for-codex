# Build Workflow

Use for an authorized implementation with a concrete user-visible result.

## Scope And Implementation

Identify the normal entry point, the behavior the caller expects, and the files the worker owns. Check the applicable repository instructions and existing changes in the target area. Follow the current branch, worktree, and commit authorization.

Trace a representative input from the caller to the result. Locate nearby behavior, existing tests, and any format already used by saved data. Choose the smallest change that supports the full requested path. Preserve unrelated edits and account for relevant failure, retry, or concurrent use.

Split changes only where separate writers can own different outputs. If a public contract changes, tell its consumers which version to use. Seek a decision when the chosen implementation changes the approved scope or carries a new irreversible consequence.

## Delivery

Use the project's existing relevant check within the agreed verification scope. Report what changed, what actually ran and what remains uncertain. Supply the entry point or changed file when the user needs it to use the feature. Independent review belongs to a separate reviewer when requested.
