# Verified keyboard resource details (firmware 3.29.1.0)

These are nonbinary details recovered from a manually successful reMarkable 2 installation. **Do not reconstruct the byte-for-byte original from this summary.** Read the originals from the user's tablet and fail closed if validation fails.

## Swedish on-screen resource

- Original xochitl SHA-256: `4ab39bdf42503fe8d9e10a31a415b28b9aed6f25bd32788226c02ee23879fd13`
- Zstd frame at file offset `0xFB0B56`, size 517 bytes; decoded UTF-8 JSON 2192 bytes.
- Original extracted local filename: `keyboard_00fb0b56.json`.
- Top-level JSON keys: `inherits` (`en_US`) and `alphabetic` (three arrays).
- Keys: `{"default":["letter", "...optional long-press characters"],"shifted":["LETTER", "...optional alternatives"]}`; special keys: `{"special":"shift"}`, `{"special":"backspace"}`.
- Original primary rows:
  - `q w e r t y u i o p å`
  - `a s d f g h j k l ö ä`
  - `shift z x c v b n m backspace`
- The original contains additional accented long-press alternatives. Always verify the decoded original resource against expected structural features.

## Manually verified Russian replacement JSON generator

```python
import json
rows = ["йцукенгшщзхъ", "фывапролджэ", "ячсмитьбю"]
def make_key(c):
    return {"default": [c], "shifted": [c.upper()]}
layout = {
    "inherits": "en_US",
    "alphabetic": [
        [make_key(c) for c in rows[0]],
        [make_key(c) for c in rows[1]],
        [{"special": "shift"}] + [make_key(c) for c in rows[2]] + [{"special": "backspace"}]
    ]
}
for row in layout["alphabetic"]:
    for key in row:
        if key.get("default") == ["е"]:
            key["default"].append("ё")
            key["shifted"].append("Ё")
replacement = (json.dumps(layout, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
```

The resulting replacement was 3728 UTF-8 bytes, and compressed to exactly 517 bytes using `zstandard.ZstdCompressor(level=-3)` on the user's Debian ThinkPad. Different Zstd versions may produce different sizes: **refuse to patch if not exactly 517 bytes**. This replacement was manually verified working on the tablet.

## On-screen selector translation

- Source catalog: `/usr/share/remarkable/xochitl/translations/reMarkable_en.qm`.
- After `lconvert`, the relevant TS message had `<source>Swedish</source><translation></translation>`.
- Setting its translation to `Russian` and recompiling with `lrelease` successfully renamed the on-screen selector.
- **Exact Qt context name was not captured.** Extract it from the original QM, check the Swedish source occurs uniquely, and reject unknown structures. Do not guess.
- Do not commit original QM/TS or proprietary xochitl binaries.
