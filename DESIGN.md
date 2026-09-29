# Design

Direction: **live signal**. The app is a microphone — the status pill shows the mic
actually hearing you (level bars + elapsed time). That is the one bold element.
Everything else (settings, review) is quiet graphite, monochrome, dense.

## Tokens

| Name | Hex | Use |
|---|---|---|
| bg | `#18191C` | window background |
| surface | `#202226` | popups, hover, panels |
| input | `#26282D` | fields |
| line | `#33363C` | hairlines, borders |
| text | `#E8E6E1` | primary text, Save button fill |
| muted | `#8C8F96` | descriptions, inactive tabs |
| faint | `#5E6168` | disabled, silent meter bars |
| rec | `#E5484D` | **pill only** — mic open |
| llm | `#E2A336` | **pill only** — LLM busy, remote-API recording |

Type: Segoe UI Variable Text (fallback Segoe UI). Mono: Cascadia Mono — keys only.
Radii: pill = height/2, windows 12, fields/buttons 6.

## Rules

- Colour is reserved for the pill. Settings never use rec/llm.
- No DWM Mica/Acrylic on the pill — it fills the whole HWND rectangle.
- Labels: sentence case, no trailing colon, acronyms upper (`_humanize`).
- One filled button per window (`#primaryButton`).
- Every field has hover, focus and disabled states in `src/ui/styles.qss`.
- Hidden fields hide their description too (`*_desc` object name).
