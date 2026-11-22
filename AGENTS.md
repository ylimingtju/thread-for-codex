# Repository Guidelines

## Project Structure

- `install.py` installs this checkout through the bundled `director-local` marketplace. Marketplace and plugin metadata live in `.agents/plugins/marketplace.json` and `plugins/codex-director/.codex-plugin/plugin.json`.
- `plugins/codex-director/` contains the panel server (`panel_server.py`), thread registry (`panel_state.py`), token accounting (`panel_usage.py`), and reply hooks (`worker_reply.py`, configured in `hooks/hooks.json`).
- Edit the panel in `assets/threads.html` and agent instructions in `skills/`, both inside the plugin directory. User guides and release notes live in `README.md`, `README.en.md`, `CHANGELOG.md`, and `docs/`.

## Local Development

Use Python 3.9 or later, a signed-in Codex desktop app, and a CLI that supports `codex plugin`. Run `python3 install.py` on macOS or `py -3 .\install.py` in Windows PowerShell from the repository root. Pass `--codex PATH` to select a specific CLI executable. In Codex, start a project chat with “Use this chat as the main discussion for this project.”

## Coding Style

Use four-space Python indentation, `snake_case` for functions and modules, and `UPPER_CASE` for constants. Use the Python standard library and match nearby formatting. Keep panel HTML, CSS, and JavaScript in `assets/threads.html`. Preserve the upstream license and attribution.

## Tests

- `python3 -B -m unittest discover -s tests` runs the registry, token accounting, and reply hook tests. Use `test_*.py` filenames and `test_*` methods for new unit tests.
- `python3 -B plugins/codex-director/tests/test_panel_server.py` runs the panel server’s standalone assertions, including permitted chat navigation.

Use temporary fixture data or a separate `CODEX_HOME` for tests that write local state. Report desktop behavior as verified only when you observed it in the app.

## Commits and Pull Requests

Use short imperative subjects, such as “Clarify the v1.1.1 project panel entry.” In a PR, explain the user-visible change, list checks performed and platforms covered, and link the relevant issue when available. Include a screenshot with fictional data for panel changes. Keep relevant Chinese and English documentation in sync. Publish changes only when explicitly requested.
