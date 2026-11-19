# Dynamic Workflow Integration

Use this guide when a structured handoff, reusable recipe, or specific workflow files are part of the asked-for result, or when continuing a run that already promised them. Ordinary multi-chat work uses the project panel and native chat history.

## Setup

Define the outcome and the outputs each participant needs. Group tasks by input dependencies and assign one writer to each shared output. Choose a durable file only if someone needs to consume it separately or the user asked for it. Identify any approval the user reserved. Distribute independent assignments in parallel within current authority.

## Packet Shape

A packet is a saved assignment under `.workflow/<slug>/packets/`. When packet files are wanted, give each the objective, source version, intended output, write scope, owner and dependencies. Include acceptance criteria if they add information about the deliverable. A worker with the right history can receive a link and the changed request.

## Integration

Wait for the actual result before releasing a dependent item. Reconcile competing changes against the owning version. When the observed reply answers the correct assignment in full, use it directly. Retrieve the relevant chat turn or artifact when identity, completeness, or material evidence is unclear. Summarize decisions in the main chat, and retain original replies in their chats.

## Resume An Existing Run

Read the existing plan or latest handoff to identify outstanding commitments. For legacy runs the files may include `.workflow/<slug>/plan.md`, `orchestration.md`, `packets/`, `results/`, or `final-report.md`. Keep existing assignments, accepted outputs, project-specific approval points, and promised deliverables. Resume from the first unsatisfied dependency. Use the original owner when available. Write only the files or remaining results the run committed to producing.

## Reusable Recipes

When the user wants a reusable workflow, record its inputs, dependency order, ownership, stop conditions, and an example of the expected output. Store it at the agreed location and leave out private prompts, credentials, and transcripts.
