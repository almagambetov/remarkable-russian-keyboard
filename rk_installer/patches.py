"""Fail-closed, length-preserving patches for one fingerprinted firmware."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import xml.etree.ElementTree as ET

import zstandard

FIRMWARE = "3.29.1.0"
HASHES = {
    "libepaper.so": "2090c5294015c9decaeefb1a46706d1de08e0fed256de9032f5a6c25928eb59e",
    "xochitl": "4ab39bdf42503fe8d9e10a31a415b28b9aed6f25bd32788226c02ee23879fd13",
}
TABLE_OFFSET, TABLE_SIZE = 0x1F484, 4560
RESOURCE_OFFSET, RESOURCE_SIZE = 0xFB0B56, 517
LABEL_OFFSET = 0x13959D4
RECORD = struct.Struct("<HHIII")


class Refused(ValueError):
    """Input cannot safely be patched."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_original(name: str, data: bytes) -> None:
    if name not in HASHES or digest(data) != HASHES[name]:
        raise Refused(f"Unknown original {name}: SHA-256 mismatch")


def replace(data: bytes, offset: int, expected: bytes, replacement: bytes) -> bytes:
    if len(expected) != len(replacement) or data[offset:offset + len(expected)] != expected:
        raise Refused(f"Unexpected bytes or replacement size at {offset:#x}")
    return data[:offset] + replacement + data[offset + len(expected):]


# evdev positions, Swedish lower/upper, Russian lower. Other records stay intact.
LETTERS = {}
for codes, swedish, russian in (
    (range(16, 26), "qwertyuiop", "йцукенгшщз"),
    (range(30, 39), "asdfghjkl", "фывапролд"),
    (range(44, 51), "zxcvbnm", "ячсмить"),
):
    for code, old, new in zip(codes, swedish, russian, strict=True):
        LETTERS[code] = (old, old.upper(), new)
LETTERS.update({26: ("å", "Å", "х"), 27: ("¨", "^", "ъ"),
                39: ("ö", "Ö", "ж"), 40: ("ä", "Ä", "э"),
                51: (",", ";", "б"), 52: (".", ":", "ю")})


def patch_folio(data: bytes) -> bytes:
    verify_original("libepaper.so", data)
    table = data[TABLE_OFFSET:TABLE_OFFSET + TABLE_SIZE]
    if len(table) != TABLE_SIZE:
        raise Refused("Truncated Type Folio table")
    records = list(RECORD.iter_unpack(table))
    # Identify the modifier word by its documented ordinary-letter values.
    fields = [field for field in (2, 3, 4) if all(
        sum(r[0] == code and r[field] == mod for r in records) == 1
        for code in range(16, 26) for mod in (0x20000, 0x20001))]
    if len(fields) != 1 or fields[0] != 3:
        raise Refused("Unexpected Type Folio modifier/record structure")
    for code, (lower, upper, russian) in LETTERS.items():
        for shifted, expected in enumerate((lower, upper)):
            modifier = shifted if code in (26, 27, 51, 52) else 0x20000 + shifted
            matches = [i for i, r in enumerate(records) if r[0] == code and r[3] == modifier]
            if len(matches) != 1:
                raise Refused(f"Expected unique Type Folio record {code}/{modifier:#x}")
            i = matches[0]
            key, unicode, qtkey, mods, special = records[i]
            if unicode != ord(expected) or qtkey not in (0, ord(expected.upper())) or special != 0:
                raise Refused(f"Unexpected Type Folio bytes for key {code}/{modifier:#x}")
            char = russian.upper() if shifted else russian
            records[i] = (key, ord(char), ord(russian.upper()) if qtkey else 0, mods, special)
    return replace(data, TABLE_OFFSET, table, b"".join(RECORD.pack(*r) for r in records))


def strict_json(data: bytes):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise Refused(f"Duplicate JSON key: {k}")
            out[k] = v
        return out
    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, ValueError) as exc:
        raise Refused("Invalid keyboard JSON") from exc


def decode_keyboard(data: bytes) -> dict:
    verify_original("xochitl", data)
    frame = data[RESOURCE_OFFSET:RESOURCE_OFFSET + RESOURCE_SIZE]
    try:
        decoder = zstandard.ZstdDecompressor().decompressobj()
        raw = decoder.decompress(frame)
        if not decoder.eof or decoder.unused_data or len(raw) != 2192:
            raise Refused("Unexpected Swedish Zstd boundaries or decoded length")
    except zstandard.ZstdError as exc:
        raise Refused("Invalid Swedish Zstd resource") from exc
    layout = strict_json(raw)
    if not isinstance(layout, dict) or set(layout) != {"inherits", "alphabetic"} or layout["inherits"] != "en_US":
        raise Refused("Unexpected Swedish keyboard schema")
    rows = layout["alphabetic"]
    expected = [list("qwertyuiopå"), list("asdfghjklöä"), ["shift", *"zxcvbnm", "backspace"]]
    if not isinstance(rows, list) or len(rows) != 3:
        raise Refused("Expected three Swedish rows")
    for row, primary in zip(rows, expected, strict=True):
        if not isinstance(row, list) or len(row) != len(primary):
            raise Refused("Unexpected Swedish row lengths")
        for key, char in zip(row, primary, strict=True):
            if char in ("shift", "backspace"):
                if key != {"special": char}:
                    raise Refused("Unexpected special keyboard key")
            elif (not isinstance(key, dict) or set(key) != {"default", "shifted"}
                  or any(not isinstance(key[k], list) or not key[k]
                         or any(not isinstance(v, str) or not v for v in key[k])
                         for k in ("default", "shifted"))
                  or key["default"][0] != char or key["shifted"][0] != char.upper()):
                raise Refused("Unexpected Swedish letter/alternatives")
    return layout


def russian_keyboard() -> bytes:
    def key(c):
        return {"default": [c], "shifted": [c.upper()]}
    layout = {"inherits": "en_US", "alphabetic": [
        [key(c) for c in "йцукенгшщзхъ"], [key(c) for c in "фывапролджэ"],
        [{"special": "shift"}] + [key(c) for c in "ячсмитьбю"] + [{"special": "backspace"}]]}
    for row in layout["alphabetic"]:
        for item in row:
            if item.get("default") == ["е"]:
                item["default"].append("ё")
                item["shifted"].append("Ё")
    return (json.dumps(layout, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def patch_xochitl(data: bytes) -> bytes:
    decode_keyboard(data)
    replacement = zstandard.ZstdCompressor(level=-3).compress(russian_keyboard())
    if len(replacement) != RESOURCE_SIZE:
        raise Refused(f"Zstd version produced {len(replacement)} bytes; require exactly 517")
    result = replace(data, RESOURCE_OFFSET, data[RESOURCE_OFFSET:RESOURCE_OFFSET + RESOURCE_SIZE], replacement)
    return replace(result, LABEL_OFFSET, b"Swedish", b"Russian")


def run_tool(args: list[str]) -> None:
    subprocess.run(args, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def catalog_map(root: ET.Element) -> dict:
    if root.tag != "TS" or root.get("language") not in ("en", "en_US", "en_GB"):
        raise Refused("Expected an English TS catalog")
    result = {}
    for context in root:
        if context.tag != "context" or len(context.findall("name")) != 1:
            raise Refused("Unexpected translation context structure")
        if any(child.tag not in {"name", "message"} for child in context):
            raise Refused("Unknown Qt context element")
        name = context.findtext("name")
        if not name:
            raise Refused("Empty translation context")
        for message in context.findall("message"):
            source, translation = message.find("source"), message.find("translation")
            if source is None or translation is None or len(message.findall("source")) != 1 or len(message.findall("translation")) != 1:
                raise Refused("Unexpected translation message structure")
            if (list(source) or any(child.tag not in {"source", "translation", "comment", "location"} for child in message)
                    or len(message.findall("comment")) > 1):
                raise Refused("Unknown Qt message structure")
            identity = (name, source.text or "", message.findtext("comment") or "")
            if identity in result:
                raise Refused("Duplicate Qt message identity")
            result[identity] = ET.tostring(message, encoding="unicode")
    return result


def patch_catalog(data: bytes, lconvert: str, lrelease: str) -> tuple[bytes, str]:
    if Path(lconvert).resolve().parent != Path(lrelease).resolve().parent:
        raise Refused("Use lconvert and lrelease from the same Qt 6 tools directory")
    version = subprocess.run([lrelease, "-version"], check=True, capture_output=True, text=True)
    if "lrelease version 6." not in version.stdout + version.stderr:
        raise Refused("Qt 6 lrelease is required")
    with tempfile.TemporaryDirectory(prefix="rk-qt-") as directory:
        folder = Path(directory)
        qm, ts, patched, output = [folder / name for name in ("original.qm", "original.ts", "patched.qm", "roundtrip.ts")]
        qm.write_bytes(data)
        run_tool([lconvert, "-i", str(qm), "-o", str(ts)])
        tree = ET.parse(ts)
        root = tree.getroot()
        before = catalog_map(root)
        matches = [(c, m) for c in root.findall("context") for m in c.findall("message") if m.findtext("source") == "Swedish"]
        if len(matches) != 1:
            raise Refused("Require exactly one Swedish source in the original QM")
        context, message = matches[0]
        translation = message.find("translation")
        if message.attrib or message.find("comment") is not None or translation is None or list(translation) or translation.attrib or (translation.text or ""):
            raise Refused("Unexpected Swedish translation; require plain empty original")
        original = copy.deepcopy(root)
        translation.text = "Russian"
        expected = catalog_map(root)
        changed = [k for k in before if before[k] != expected[k]]
        if len(changed) != 1:
            raise Refused("Unexpected translation changes")
        tree.write(ts, encoding="utf-8", xml_declaration=True)
        run_tool([lrelease, str(ts), "-qm", str(patched)])
        run_tool([lconvert, "-i", str(patched), "-o", str(output)])
        # Compare the entire Qt-normalized result against an identically compiled baseline,
        # because lrelease may normalize empty/unfinished translations and locations.
        baseline_ts, baseline_qm, baseline_out = [folder / n for n in ("baseline.ts", "baseline.qm", "baseline-out.ts")]
        ET.ElementTree(original).write(baseline_ts, encoding="utf-8", xml_declaration=True)
        run_tool([lrelease, str(baseline_ts), "-qm", str(baseline_qm)])
        run_tool([lconvert, "-i", str(baseline_qm), "-o", str(baseline_out)])
        after = catalog_map(ET.parse(output).getroot())
        baseline = catalog_map(ET.parse(baseline_out).getroot())
        target = changed[0]
        if baseline != before:
            raise Refused("Qt baseline recompilation changed the original catalog")
        if set(after) != set(baseline) or [k for k in baseline if baseline[k] != after[k]] != [target]:
            raise Refused("Qt compilation changed unrelated translations")
        final_message = ET.fromstring(after[target])
        if final_message.findtext("translation") != "Russian":
            raise Refused("Qt translation did not survive compilation")
        return patched.read_bytes(), context.findtext("name")
