# Refactor Workflow

Use to simplify the implementation while preserving specified behavior. Identify any intentional behavior change separately before applying it.

## Scope And Invariants

Trace the public callers, data contracts, and outputs of the target area. Identify behavior existing users rely on, including stored state, retries, and compatibility with older callers when relevant. Read the project's applicable instructions and preserve unrelated edits.

Choose changes that remove concrete duplication, excessive coupling, or branches. Assess each against its callers and the amount of code it affects. Prefer existing abstractions that already express the required behavior.

## Implementation And Delivery

Order changes so each step has a clear owner and a reviewable effect. Parallelize modules only where the output contracts and write ownership are independent. When one step changes a shared interface, pass its actual revision to downstream workers.

Use the existing checks for the affected behavior within the project's approved scope. Compare externally visible results, including meaningful edge cases. Report the simplification, the behaviors covered by the checks, and any unverified invariant. A reviewer independent of the author can examine high-impact invariants when requested.
