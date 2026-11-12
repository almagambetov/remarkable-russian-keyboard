"""Synthetic data only: nothing extracted from proprietary firmware."""
import json
import os
from pathlib import Path
import random
import struct

import pytest
import zstandard

from rk_installer import patches


@pytest.fixture
def qt_tools():
    folder = Path(os.environ.get("RK_QT_BIN", "/usr/lib/qt6/bin"))
    # Required dependency: missing Qt must fail, never silently skip coverage.
    assert (folder / "lconvert").is_file(), f"Install Qt 6 tools; not found at {folder}"
    assert (folder / "lrelease").is_file()
    return str(folder / "lconvert"), str(folder / "lrelease")


@pytest.fixture
def synthetic_folio(monkeypatch):
    records = []
    for code, (lower, upper, _) in patches.LETTERS.items():
        for shifted, old in enumerate((lower, upper)):
            modifier = shifted if code in (26, 27, 51, 52) else 0x20000 + shifted
            records.append((code, ord(old), ord(old.upper()), modifier, 0))
    records += [(99, 0, 0, 0, 0)] * (patches.TABLE_SIZE // 16 - len(records))
    data = b"A" * patches.TABLE_OFFSET + b"".join(struct.pack("<HHIII", *r) for r in records) + b"TAIL"
    monkeypatch.setitem(patches.HASHES, "libepaper.so", patches.digest(data))
    return data


@pytest.fixture(scope="session")
def swedish_resource():
    # Deterministic synthetic alternatives. Search for exactly the documented
    # frame and decoded lengths; none of these alternatives come from firmware.
    randomizer = random.Random(7)
    rows = [[{"default": [c], "shifted": [c.upper()]} for c in row]
            for row in ("qwertyuiopå", "asdfghjklöä", "zxcvbnm")]
    rows[2] = [{"special": "shift"}] + rows[2] + [{"special": "backspace"}]
    base = {"inherits": "en_US", "alphabetic": rows}
    for count in range(1, 400):
        letters = "".join(randomizer.choice("abcdefghijklmnopqrstuvwxyzåöä") for _ in range(count))
        rows[0][0]["default"] = ["q", letters]
        raw = json.dumps(base, ensure_ascii=False, separators=(",", ":")).encode()
        if len(raw) > 2192:
            break
        raw += b" " * (2192 - len(raw))
        for level in (-3, 1, 3, 9):
            compressed = zstandard.ZstdCompressor(level=level).compress(raw)
            if len(compressed) == 517:
                return raw, compressed
    raise AssertionError("Synthetic Zstd fixture construction failed")


@pytest.fixture
def synthetic_xochitl(monkeypatch, swedish_resource):
    _, compressed = swedish_resource
    data = bytearray(b"X" * (patches.LABEL_OFFSET + 20))
    data[patches.RESOURCE_OFFSET:patches.RESOURCE_OFFSET + 517] = compressed
    data[patches.LABEL_OFFSET:patches.LABEL_OFFSET + 7] = b"Swedish"
    data = bytes(data)
    monkeypatch.setitem(patches.HASHES, "xochitl", patches.digest(data))
    return data


@pytest.fixture
def synthetic_catalog(tmp_path, qt_tools):
    # Empty translation with no unfinished attribute, as documented in the issue.
    text = '''<?xml version="1.0" encoding="utf-8"?>
<TS version="2.1" language="en_US">
<context><name>SyntheticSelector</name>
<message><source>Swedish</source><translation></translation></message>
<message><source>Other</source><translation>Unchanged</translation></message>
</context>
<context><name>AnotherContext</name>
<message><source>Hello</source><translation>Hello there</translation></message>
</context></TS>'''
    ts, qm = tmp_path / "synthetic.ts", tmp_path / "synthetic.qm"
    ts.write_text(text)
    patches.run_tool([qt_tools[1], str(ts), "-qm", str(qm)])
    return qm.read_bytes()
