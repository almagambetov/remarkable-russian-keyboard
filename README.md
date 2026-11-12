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

## Development installer (unreleased)

The installer in this branch implements issue #1. **Synthetic tests pass; automated installation and recovery have not been validated on a tablet.** Read [the recovery design](docs/recovery.md) and review it before a hardware trial. A successful `--check` verifies originals and generates patches; it does not test installation or rollback on hardware.

### Linux dependencies and offline tests

Use Python 3.11 or newer, OpenSSH client, and Qt **6** `lconvert` and `lrelease`. On Debian/Ubuntu with administrator access:

```sh
sudo apt-get update
sudo apt-get install python3-venv openssh-client qt6-l10n-tools
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
RK_QT_BIN=/usr/lib/qt6/bin .venv/bin/python -m pytest -q
.venv/bin/remarkable-russian-keyboard --help
```

Pytest and python-zstandard are pinned in `pyproject.toml`; Zstandard 0.25.0 produces the documented exact 517-byte replacement here. Different native Zstd/tool versions may change output: size mismatches are a hard refusal. Tests fail if required Qt tools are absent; they do not silently skip translation validation. Set `RK_QT_BIN` to another Qt 6 binary directory for tests and the CLI, or use `--lconvert` and `--lrelease` for the CLI. Avoid `/usr/bin` Qt chooser wrappers that may select Qt 5.

Tests use invented firmware bytes, generated JSON and catalogs, and mocked SSH/systemd. They exercise patch boundaries, unknown firmware/bytes, rollback failures, power-loss states via interrupted renames and boot-ID changes, and repeated host/device operations. They do not emulate the tablet's flash storage, USB, real systemd boot or UI.

### USB SSH and commands

Enable developer/SSH access using the tablet's supported settings. Connect it over USB to your **Linux host attached to the tablet**, normally at `10.11.99.1`. Establish and verify the tablet's SSH host key using a trusted method, and configure public-key login for root. The installer uses `BatchMode=yes` and `StrictHostKeyChecking=yes`; it never accepts a new host key or supplies a password for you. No secrets need to be committed or entered into this project's configuration. Check connectivity first:

```sh
ssh root@10.11.99.1
```

The tablet must be reMarkable 2 on exactly OS 3.29.1.0, with writable target directories, adequate space for three backups and same-directory staged copies, and working `systemctl`, `flock`, `sha256sum`, `stat`, `cp`, `mv`, `sync`, `date`, `awk`, `tar`, and `cmp`. Failure to satisfy a prerequisite must be fixed before a hardware trial; the installer does not remount filesystems automatically.

From the activated virtual environment, with the procedures reviewed:

```sh
remarkable-russian-keyboard --check
remarkable-russian-keyboard --install --backup-dir "$HOME/remarkable-originals-3.29.1.0"
remarkable-russian-keyboard --status
# On the tablet, test both Russian keyboards and both selectors immediately.
# Only after verifying the UI, typing, symbols/modifiers and ё long-press:
remarkable-russian-keyboard --confirm
# To restore originals at any time while current files are still recognized:
remarkable-russian-keyboard --uninstall
```

The default destination is `root@10.11.99.1`; set `--host root@HOST` if needed. Each command requires exactly one operation. `--check` downloads originals to temporary host memory, validates firmware/fingerprints/structures, and exercises all three patch generators without writing to the tablet. Installation first creates and verifies a **new private host backup directory**, then independent original backups on the tablet. Existing backups are never silently overwritten. Keep proprietary originals and extracted catalogs outside the repository. Repeating install against an intact pending/confirmed transaction reuses its backup set; it does not reset the confirmation deadline.

Installation stops and restarts `xochitl`. A persistent systemd timer rolls back an unconfirmed installation after five minutes, or on its first check after reboot. Confirm before the deadline only if the tablet works. Disconnecting SSH does not cancel the timer. Review [interrupted preparation and manual recovery](docs/recovery.md) before relying on it.

A remote cloud machine normally has no physical USB connection to your tablet. Use it for development and synthetic tests; run reviewed hardware operations on the directly connected Linux host. Do not distribute host/device backup directories, patched binaries, or extracted QM/TS files. No release or broader firmware compatibility is claimed.
