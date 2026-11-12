# Russian keyboard for reMarkable 2

Community project to enable Russian ЙЦУКЕН on the **US Type Folio** and **on-screen keyboard** by repurposing the Swedish layout.

## Compatibility

- Device: reMarkable 2
- Confirmed working manually: reMarkable OS **3.29.1.0**
- Other versions: **not supported** until verified
- Status: **development / not yet safe for unattended installation**

## How it works

The manual proof of concept modifies three files *on the user's own device*:

1. `/usr/lib/plugins/platforms/libepaper.so`: replace the Swedish Type Folio mapping.
2. `/usr/bin/xochitl`: replace a Zstandard-compressed Swedish on-screen keyboard resource and rename the Type Folio language label.
3. `/usr/share/remarkable/xochitl/translations/reMarkable_en.qm`: translate the Swedish label to Russian for the on-screen language selector.

**Do not commit or distribute proprietary reMarkable binaries or extracted translation catalogs.** A future installer must generate patches from the user's own firmware.

## Verified firmware fingerprints

Original `libepaper.so` SHA-256:
`2090c5294015c9decaeefb1a46706d1de08e0fed256de9032f5a6c25928eb59e`

Original `xochitl` SHA-256:
`4ab39bdf42503fe8d9e10a31a415b28b9aed6f25bd32788226c02ee23879fd13`

Offsets are firmware-specific and must never be applied without validating original hashes and byte sequences.

## Development roadmap

See the GitHub issues. Before publishing an installer, implement idempotent checks, backup/restore, atomic file replacement, rollback that survives connection loss, and offline fixture-based tests. Keep the working Type Folio and on-screen layouts independent.

## Disclaimer

Unofficial modification, not affiliated with reMarkable. Modifying the main application may prevent the tablet interface from starting. Maintain working USB SSH access and verified recovery backups. Firmware updates can undo these modifications.
