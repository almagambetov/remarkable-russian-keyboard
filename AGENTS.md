# Codex project instructions

Build a safe, redistributable Russian keyboard installer for reMarkable 2, targeting **only firmware 3.29.1.0** initially.

## Requirements

- Implement host-side installation from Linux over USB SSH, with `--check`, `--install`, `--confirm`, `--status`, and `--uninstall`.
- Never include proprietary reMarkable firmware, binaries, or extracted Qt translation catalogs in this repository.
- Read originals from the user's own tablet. Verify exact SHA-256 fingerprints before patching. Refuse unknown firmware, mismatches, or unexpected bytes.
- Patch Swedish Type Folio layout in `libepaper.so` at offset `0x1F484`, 4560 bytes, using 16-byte `<HHIII` records. Ordinary letter modifier values are `0x20000/0x20001`; punctuation-position Cyrillic letters at evdev codes 26,27,51,52 use `0/1`. Keep other mappings intact. The user has manually verified this mapping.
- On-screen keyboard: original `xochitl` contains a Swedish Zstd-compressed JSON resource starting at `0xFB0B56`, length 517 bytes. A Russian JSON using `inherits: en_US` and alphabetic rows ЙЦУКЕН can be compressed to exactly 517 bytes using python-zstandard level -3, preserving resource boundaries. Verify original decoded content and exact replacement length.
- Type Folio language label `Swedish` is a seven-byte ASCII string at `0x13959D4`; replace with `Russian`, keeping `sv_SE` internal locale unchanged.
- The on-screen selector label uses the English Qt `reMarkable_en.qm` catalog. Convert to TS with Qt 6 `lconvert`, change only the translation of source `Swedish` to `Russian` in its original context, and compile with `lrelease`. Validate exact target context and no unrelated translations change.
- Verify expected original SHA-256: `libepaper.so` = `2090c5294015c9decaeefb1a46706d1de08e0fed256de9032f5a6c25928eb59e`; `xochitl` = `4ab39bdf42503fe8d9e10a31a415b28b9aed6f25bd32788226c02ee23879fd13`.
- Preserve executable modes and ownership; stage and verify files before atomic same-filesystem replacement.
- Back up all three original files on the tablet and host. Do not silently overwrite existing backups.
- Implement a systemd rollback with explicit confirmation and durable recovery semantics. Test rollback failure modes. A transient timer is insufficient across reboot; document this.
- Make operations idempotent and avoid damaging an already modified device.
- Unit tests must use synthetic fixtures, never redistribute extracted originals. Mock SSH operations.
- Write README instructions for USB SSH, dependencies, testing, recovery, and warnings.
- Avoid claiming firmware compatibility or end-to-end testing without evidence. Keep a changelog and tests.

## User-tested behavior

The US Type Folio produces standard Russian ЙЦУКЕН when Swedish is selected; the on-screen keyboard also works, with ё via long-press on е. Both language selectors display Russian after the separate label patches. The manual patches worked on one reMarkable 2 with firmware 3.29.1.0.
