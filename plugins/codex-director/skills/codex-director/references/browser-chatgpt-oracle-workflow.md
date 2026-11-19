# Browser ChatGPT Pro Oracle Workflow

Use for an explicitly requested external second opinion through a signed-in ChatGPT browser session. Follow the user's chosen service, permitted data, and model. External disclosure needs authorization for the actual submission. A request for independent review alone can be fulfilled by a separate local reviewer.

## Scope And Privacy

Prepare a narrow question with the revision, allowed excerpts, and constraints needed to judge it. Keep credentials, secrets, unrelated conversation, private links and unnecessary personal data out of the submission. Redact unnecessary details. If the necessary disclosure exceeds the granted scope, seek the user's decision before sending. A separate [prompt file](optional-prompt-artifact-notes.md) is optional.

## Submit Through Browser

Use the host's supported browser controls for the selected run. Prefer a fresh chat unless the user specified an existing one. Preserve in-progress user chats. If authentication is required, ask the user to sign in in the browser. Never request credentials in chat.

Check the visible selected model or tier if the request requires Pro or a specific model. When it is unavailable or cannot be identified, report that limitation. Use another model or local review only within the user's allowed alternatives and identify any substitution. Send the approved payload once. If the browser loses state, inspect the conversation for the submitted turn before retrying.

## Wait And Capture

Wait for a finished assistant reply to the submitted question. A populated input box, sent prompt, partial answer, or saved prompt file is insufficient evidence of an answer. Capture the actual answer and visible model where available. If extraction fails or the answer is incomplete, report the observed state. Keep separate files only if requested or previously promised.

## Feed Back Into The Workflow

Compare any proposed correction against primary evidence. Explain which findings affect the plan or result and which remain uncertain. Provide the verdict, material findings, and relevant limitations in the owning chat. Summarize for the project main chat. Leave full discussion in its source chat or the requested report.
