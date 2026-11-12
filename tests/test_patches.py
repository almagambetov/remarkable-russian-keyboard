import json
import struct
import xml.etree.ElementTree as ET

import pytest
import zstandard

from rk_installer import patches as p


def test_known_fingerprints_are_pinned():
    assert p.FIRMWARE == "3.29.1.0"
    with pytest.raises(p.Refused, match="SHA-256"):
        p.patch_folio(b"unknown firmware")
    with pytest.raises(p.Refused, match="SHA-256"):
        p.patch_xochitl(b"unknown firmware")


def test_folio_changes_only_expected_records(synthetic_folio):
    result = p.patch_folio(synthetic_folio)
    assert len(result) == len(synthetic_folio)
    assert result[:p.TABLE_OFFSET] == synthetic_folio[:p.TABLE_OFFSET]
    assert result[p.TABLE_OFFSET+p.TABLE_SIZE:] == b"TAIL"
    before = list(p.RECORD.iter_unpack(synthetic_folio[p.TABLE_OFFSET:p.TABLE_OFFSET+p.TABLE_SIZE]))
    after = list(p.RECORD.iter_unpack(result[p.TABLE_OFFSET:p.TABLE_OFFSET+p.TABLE_SIZE]))
    for old, new in zip(before, after, strict=True):
        if old[0] in p.LETTERS:
            code = old[0]
            assert new[0] == code and new[3:] == old[3:]
            char = p.LETTERS[code][2]
            assert new[1] == ord(char.upper() if old[3] & 1 else char)
            assert new[2] == ord(char.upper())
            if code in (26, 27, 51, 52):
                assert new[3] in (0, 1)
            else:
                assert new[3] in (0x20000, 0x20001)
        else:
            assert old == new


@pytest.mark.parametrize("field,value", [(0, 99), (1, 99), (2, 999), (3, 0), (4, 1)])
def test_folio_refuses_unexpected_records(synthetic_folio, monkeypatch, field, value):
    original = bytearray(synthetic_folio)
    record = list(p.RECORD.unpack_from(original, p.TABLE_OFFSET))
    record[field] = value
    p.RECORD.pack_into(original, p.TABLE_OFFSET, *record)
    original = bytes(original)
    monkeypatch.setitem(p.HASHES, "libepaper.so", p.digest(original))
    with pytest.raises(p.Refused):
        p.patch_folio(original)


def test_keyboard_generator_exact_resource():
    raw = p.russian_keyboard()
    assert len(raw) == 3728
    compressed = zstandard.ZstdCompressor(level=-3).compress(raw)
    assert len(compressed) == 517
    layout = json.loads(zstandard.ZstdDecompressor().decompress(compressed))
    assert layout["inherits"] == "en_US"
    rows = ["".join(k["default"][0] for k in row if "default" in k) for row in layout["alphabetic"]]
    assert rows == ["йцукенгшщзхъ", "фывапролджэ", "ячсмитьбю"]
    assert layout["alphabetic"][0][4] == {"default": ["е", "ё"], "shifted": ["Е", "Ё"]}


def test_xochitl_preserves_boundaries(synthetic_xochitl):
    result = p.patch_xochitl(synthetic_xochitl)
    assert len(result) == len(synthetic_xochitl)
    assert result[:p.RESOURCE_OFFSET] == synthetic_xochitl[:p.RESOURCE_OFFSET]
    assert result[p.RESOURCE_OFFSET+517:p.LABEL_OFFSET] == synthetic_xochitl[p.RESOURCE_OFFSET+517:p.LABEL_OFFSET]
    assert result[p.LABEL_OFFSET:p.LABEL_OFFSET+7] == b"Russian"
    assert result[p.LABEL_OFFSET+7:] == synthetic_xochitl[p.LABEL_OFFSET+7:]
    assert zstandard.ZstdDecompressor().decompress(result[p.RESOURCE_OFFSET:p.RESOURCE_OFFSET+517]) == p.russian_keyboard()


def test_xochitl_bad_label_refused(synthetic_xochitl, monkeypatch):
    broken = synthetic_xochitl[:p.LABEL_OFFSET] + b"Unknown" + synthetic_xochitl[p.LABEL_OFFSET+7:]
    monkeypatch.setitem(p.HASHES, "xochitl", p.digest(broken))
    with pytest.raises(p.Refused, match="Unexpected bytes"):
        p.patch_xochitl(broken)


def test_invalid_resource_refused(synthetic_xochitl, monkeypatch):
    broken = bytearray(synthetic_xochitl)
    broken[p.RESOURCE_OFFSET] = 0
    broken = bytes(broken)
    monkeypatch.setitem(p.HASHES, "xochitl", p.digest(broken))
    with pytest.raises(p.Refused, match="Zstd"):
        p.patch_xochitl(broken)


def test_compression_version_mismatch_refused(synthetic_xochitl, monkeypatch):
    class Compressor:
        def __init__(self, **kwargs): pass
        def compress(self, value): return b"a" * 518
    monkeypatch.setattr(p.zstandard, "ZstdCompressor", Compressor)
    with pytest.raises(p.Refused, match="518"):
        p.patch_xochitl(synthetic_xochitl)


def test_catalog_changes_only_unique_extracted_context(synthetic_catalog, qt_tools, tmp_path):
    result, context = p.patch_catalog(synthetic_catalog, *qt_tools)
    assert context == "SyntheticSelector"
    qm, ts = tmp_path / "result.qm", tmp_path / "result.ts"
    qm.write_bytes(result)
    p.run_tool([qt_tools[0], "-i", str(qm), "-o", str(ts)])
    messages = p.catalog_map(ET.parse(ts).getroot())
    assert ET.fromstring(messages[(context, "Swedish", "")]).findtext("translation") == "Russian"
    assert ET.fromstring(messages[(context, "Other", "")]).findtext("translation") == "Unchanged"


@pytest.mark.parametrize("body", [
    '<context><name>A</name><message><source>Other</source><translation/></message></context>',
    '<context><name>A</name><message><source>Swedish</source><translation>Swedish</translation></message></context>',
    '<context><name>A</name><message><source>Swedish</source><translation/></message></context>'
    '<context><name>B</name><message><source>Swedish</source><translation/></message></context>',
])
def test_catalog_refuses_unknown_structure(body, qt_tools, tmp_path):
    ts, qm = tmp_path / "bad.ts", tmp_path / "bad.qm"
    ts.write_text('<TS version="2.1" language="en_US">' + body + '</TS>')
    p.run_tool([qt_tools[1], str(ts), "-qm", str(qm)])
    with pytest.raises(p.Refused):
        p.patch_catalog(qm.read_bytes(), *qt_tools)


def test_duplicate_json_refused():
    with pytest.raises(p.Refused):
        p.strict_json(b'{"inherits":"sv_SE","inherits":"en_US"}')


def test_swedish_schema_mismatch_rejected(synthetic_xochitl, swedish_resource, monkeypatch):
    raw, _ = swedish_resource
    layout = json.loads(raw)
    layout["alphabetic"][0][0]["default"][0] = "x"
    changed = json.dumps(layout, ensure_ascii=False, separators=(",", ":")).encode()
    changed += b" " * (2192 - len(changed))
    # Reuse the real decompressor with a synthetic frame size; this check occurs
    # before any replacement and must reject even with a permitted test hash.
    frame = zstandard.ZstdCompressor(level=-3).compress(changed)
    data = synthetic_xochitl[:p.RESOURCE_OFFSET] + frame + synthetic_xochitl[p.RESOURCE_OFFSET+len(frame):]
    monkeypatch.setattr(p, "RESOURCE_SIZE", len(frame))
    monkeypatch.setitem(p.HASHES, "xochitl", p.digest(data))
    with pytest.raises(p.Refused, match="Swedish letter"):
        p.decode_keyboard(data)


def test_folio_duplicate_target_record_rejected(synthetic_folio, monkeypatch):
    data = bytearray(synthetic_folio)
    data[p.TABLE_OFFSET+p.TABLE_SIZE-16:p.TABLE_OFFSET+p.TABLE_SIZE] = data[p.TABLE_OFFSET:p.TABLE_OFFSET+16]
    data = bytes(data)
    monkeypatch.setitem(p.HASHES, "libepaper.so", p.digest(data))
    with pytest.raises(p.Refused):
        p.patch_folio(data)
