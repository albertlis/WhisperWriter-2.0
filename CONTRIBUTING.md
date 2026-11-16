# Contributing to WhisperWriter

WhisperWriter is a Windows speech-to-text app (Python, PyQt6). Press a hotkey, speak, and the text is typed at the cursor, optionally cleaned up by an LLM. [CLAUDE.md](CLAUDE.md) holds the architecture map and the rules this repo follows.

## Development setup

Python 3.12 or newer and [uv](https://docs.astral.sh/uv/).

```
uv sync --extra local
uv run --extra local python run.py
```

Always pass `--extra local`. Plain `uv sync` or `uv run` uninstalls `faster-whisper` and `ctranslate2`. The app then falls back to API mode without any error, and `model_path` is ignored.

Run from the project root. `run.py`, `src/config.yaml` and `assets/` use paths relative to it.

`start.bat` runs `.venv\Scripts\python.exe` directly, not `uv run`. After changing dependencies, run `uv sync --extra local` by hand.

Do not install torch in the main venv. `ctranslate2` imports it when present, which adds about 10 s to startup.

`training/` is a separate subproject with its own venv. Set it up with `cd training && uv sync`. Do not mix it with the main venv.

There is no offline test suite and no CI beyond release-please and the PR-title check. Lint with:

```
uvx ruff check .
```

`pyproject.toml` has no `[tool.ruff]` section, so ruff runs with its defaults. Verify behaviour changes by running the app, and say what you ran in the PR.

## Style

- Type hints: `list`, `dict`, `X | None`. Not `List`, `Optional`, `Union`.
- No `# type: ignore` and no `cast(Any)`. Fix the root cause.
- API keys live only in Windows Credential Manager, never in YAML. Schema defaults are in `src/config_schema.yaml`, user overrides in `src/config.yaml`.
- If a change alters behaviour or config keys, update `README.md` and `docs/` in the same PR.
- For UI changes, read [DESIGN.md](DESIGN.md) first.

## Issues

Use GitHub Issues. The repo has no issue templates. Describe what you did, what you expected and what happened. Include your Windows version and whether transcription ran locally or through an API. Remove API keys and personal data from logs and screenshots.

## Pull requests

1. For non-trivial changes, open an issue first.
2. Branch from `main`.
3. Keep the change focused: one feature or one fix per PR.
4. Run `uvx ruff check .` and exercise the change in the app.
5. PR description: what changed and how you verified it.
6. No hand-written changelog entry. release-please generates `CHANGELOG.md` from commit and PR titles, so write a clear PR title.

## Commits and releases

Commits follow [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`. Add `!` after the type for a breaking change (`refactor!: ...`). PRs are squash-merged, so the PR title becomes the commit message and CI checks it. release-please reads those commits on `main` and keeps a release PR open with the version bump and changelog. Merging that release PR creates the `vX.Y.Z` tag and the GitHub release. Do not bump versions by hand.

## License

By contributing, you agree that your contribution is licensed under the GNU General Public License v3.0 ([LICENSE](LICENSE)).
