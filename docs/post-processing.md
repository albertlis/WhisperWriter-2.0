# Post-Processing

Post-processing runs after every transcription and shapes the text before it reaches your active window.

## Text Adjustments

Set in `post_processing` section of `src/config.yaml`.

| Setting | Default | Effect |
|---|---|---|
| `remove_trailing_period` | `false` | Strip a trailing `.` from the transcribed text |
| `add_trailing_space` | `true` | Append a space so the next word lands in the right place |
| `remove_capitalization` | `false` | Lowercase the entire transcription |

## Input Methods

`post_processing.input_method` controls how text reaches the active window.

- **`pynput`** (default, Windows) — sends key events via `pynput.keyboard`. Works in most Windows apps.
- **`ydotool`** — Linux; calls the `ydotool` daemon. Install separately.
- **`dotool`** — Linux; spawns a persistent `dotool` process on startup and pipes characters to it.

`writing_key_press_delay` (default `0.005` s) sets the inter-key delay used by all three methods. Only applies when text is typed character-by-character (below the clipboard threshold).

## Clipboard Paste

`clipboard_threshold` (default `1000` chars) — when the transcription is at or above this length (or when the value is `0`), WhisperWriter pastes via the Win32 clipboard instead of simulating keystrokes. This is more reliable for long text and avoids issues with apps that ignore synthetic key events.

The paste preserves your existing clipboard: all clipboard formats (including images) are saved before writing, then restored after the paste completes. This is handled by `InputSimulator._paste_with_clipboard_preservation()` (`src/input_simulation.py`).

Set `clipboard_threshold` to `0` to always use clipboard paste, or to a large number (e.g. `9999`) to always use keystrokes.

## Find and Replace

Point `post_processing.find_replace_file` at a `.txt` or `.json` file. The file is re-read on every transcription, so edits apply to the next dictation without a restart.

### Text / CSV mode (`.txt`)

One rule per line, comma-separated. Comments start with `#`. Blank lines are ignored.

```
# Correct common dictation artifacts
gonna,going to
soda,Coke
```

Matching is **word by word** and **case-insensitive**. The text is split on whitespace, so a find term containing a space (`ground beef`) never matches; use a JSON regex rule for phrases. Each word is stripped of `.`, `,`, `!`, `?` at both ends before comparing, then reattached on both sides (`!gonna.` → `!going to.`). Partial-word matches are not replaced.

### JSON mode (`.json`)

Array of rule objects. Each object has:

| Field | Required | Description |
|---|---|---|
| `type` | yes | `"regex"` or `"simple"` |
| `find` | yes | Search string or regex pattern |
| `replace` | yes | Replacement string; use `$0`…`$N` for capture groups |
| `transforms` | no | Array of transform objects (see below) |

**Simple rule** — same single-word matching as `.txt` mode:

```json
[
  { "type": "simple", "find": "gonna", "replace": "going to" }
]
```

**Regex rule** — full Python `re` syntax; capture groups referenced as `$1`, `$2`, etc.:

```json
[
  {
    "type": "regex",
    "find": "(\\d+)",
    "replace": "[$1]"
  }
]
```

**Transforms** — apply string operations to a specific capture group before substitution:

```json
[
  {
    "type": "regex",
    "find": "quote,?\\s+(.)(.+?)\\s+end\\s*quote,?",
    "replace": "\"$1$2\"",
    "transforms": [
      { "group": 1, "operations": ["capitalize"] }
    ]
  }
]
```

Available operations (defined in `TextProcessor.TRANSFORM_OPERATIONS`):

| Operation | Effect |
|---|---|
| `capitalize` | First letter uppercase, rest lowercase |
| `upper` | All uppercase |
| `lower` | All lowercase |
| `strip` | Remove surrounding whitespace |
| `title` | Title-case every word |

Rules are applied in order. The regex engine processes the entire result of the previous rule.

See [`examples/regex-find-replace.json`](../examples/regex-find-replace.json) (and [`simple-find-replace.txt`](../examples/simple-find-replace.txt)) in the repo for a fuller example.

## LLM Post-Processing

Three independent LLM modes, each triggered by a separate hotkey. All share the same provider/model settings in `llm_post_processing`.

### Cleanup mode (`llm_cleanup_key`)

Transcription → LLM → typed output. Use to fix grammar, punctuation, or style automatically.

Key setting: `llm_post_processing.system_prompt`

Default: `"You are a helpful assistant that cleans up transcribed text. Fix any grammar, punctuation, or formatting issues while maintaining the original meaning."`

Model used: `llm_post_processing.cleanup_model` (default `gpt-4o-mini`)

You can append a file's contents to the system prompt via a `.txt` path set in **Settings → LLM** next to each prompt. Stored as `llm_post_processing.system_prompt_file_path` (cleanup), `instruction_system_message_file_path` (instruction) and `text_cleanup_system_message_file_path` (text cleanup). The file is re-read on each use.

### Instruction mode (`llm_instruction_key`)

Transcription is treated as an instruction to the LLM, which generates a response. Use to draft emails, lookup answers, or run custom commands by voice.

Key setting: `llm_post_processing.instruction_system_message`

Default: `"You are an AI assistant. Interpret the user's text as instructions and respond appropriately. Be concise and direct in your responses."`

Model used: `llm_post_processing.instruction_model` (default `gpt-4o-mini`)

### Text (clipboard) cleanup (`text_cleanup_key`)

Reads the current clipboard text, sends it to the LLM, then sends Delete + `Ctrl+V` to replace the selection. The app does not copy for you — select and `Ctrl+C` first. Use to clean up text already typed into the active app.

Key setting: `llm_post_processing.text_cleanup_system_message`

Default: `"You are a helpful assistant that cleans up selected text. Fix any spelling, grammar, or formatting issues while preserving the original meaning."`

**Supported providers** (`llm_post_processing.api_type`): `chatgpt`, `claude`, `gemini`, `groq`, `ollama`

API keys are stored in Windows Credential Manager — enter them in Settings, not in `config.yaml`.

## Combination with AutoHotKey

Whisper Writer's hotkeys (e.g. `ctrl+alt+numpad1` through `ctrl+alt+numpad4`) are uncommon enough to avoid conflicts. To trigger them from more ergonomic keys, use [AutoHotKey v2](https://www.autohotkey.com/):

```ahk
#Requires AutoHotkey v2.0-a

; Right Alt → transcription (ctrl+alt+numpad1)
RAlt::
{
    SendEvent "{Ctrl down}{Alt down}{Numpad1 down}"
    KeyWait "RAlt"
    SendEvent "{Numpad1 up}{Alt up}{Ctrl up}"
}

; Shift + Right Alt → LLM cleanup (ctrl+alt+numpad2)
+RAlt::
{
    SendEvent "{Ctrl down}{Alt down}{Numpad2 down}"
    KeyWait "RAlt"
    SendEvent "{Numpad2 up}{Alt up}{Ctrl up}"
}
```

This lets a single key press or chord fire the full modifier combination that WhisperWriter listens for.
