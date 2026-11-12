# Installation and recovery design — requires review

This development installer changes the UI executable, platform library and an English translation catalog. The automated installer and its systemd recovery have **not been exercised on a tablet**. The earlier manual patch proof of concept is not evidence that this transaction code is safe on hardware. Review this document and the implementation before a hardware trial or release.

## Invariants and limits

- Read originals over authenticated USB SSH; verify the exact reMarkable 2 model, OS 3.29.1.0, and both fingerprints in `AGENTS.md`. The QM has no published fingerprint: require exactly one plain, empty `Swedish` translation in an English catalog, discover its context, and compare the complete catalog before/after a Qt 6 compile round trip.
- Type Folio accepts only unique `<HHIII` records whose original Unicode, Qt key, modifier word and special word match the supported Swedish interpretation. The current interpretation uses modifier word index 3 and special word index 4. The proprietary original table is unavailable in CI; if the real table differs, **stop and review it rather than relaxing guards on the device**. Unknown/dead-key encodings fail closed. The grave/accent key, modifiers, symbols and all nontarget records stay intact.
- Verify the on-screen original's single Zstd frame, exact 517-byte boundary, 2192 decoded bytes, schema, Swedish primary letters, uppercase keys and special keys. The verified Russian generator is version-sensitive: require exactly 517 compressed bytes, never pad/truncate a frame. Patch only the seven-byte label and resource range.
- Preserve tablet originals with `cp -p` and immutable backup filenames. Preserve permissions/ownership when staging replacements beside each live target. Validate hashes and metadata, then use same-filesystem `mv`. The three replacements form a recoverable transaction, **not one atomic operation across three files**.
- No automatic filesystem remount, firmware download, host-key bypass, SSH password storage or firmware redistribution. Rootfs write access, free disk space, working systemd, `flock` and the documented tablet tools are prerequisites. No proprietary files should ever be added to Git.
- `sync` orders durable state before replacement and after each rename. Actual flash/filesystem durability, hardware failure, and systemd unit compatibility require tablet validation. A root attacker or corrupted storage is outside the recovery guarantees.

## State and interruption handling

The tablet directory `/home/root/.local/share/remarkable-russian-keyboard` is mode 0700. Operations take a shared transaction lock via `flock`. It contains:

- `backups/`: the three original files, copied directly on the tablet with metadata;
- `payload/`: validated replacement files;
- `original.sha256`, `patched.sha256`, and `worker.sh`;
- the saved systemd unit definitions, `state`, and, once armed, `deadline` and `boot-id`.

| State | Meaning and next action |
| --- | --- |
| absent | No recorded installation. `--check` is read-only; `--install` can begin. |
| initializing | Transfer/backup preparation incomplete. No live file was changed. `--status` diagnoses this; preserve and inspect the directory before trying a new transaction. |
| prepared | Backups and payload verified. No live file changed. Installation may be retried. |
| pending | Recovery armed before stopping the UI/staging. Live files can be all original, all patched or a known mixture. Confirm only an intact, working installation. |
| recovering | Restore in progress or failed; the enabled service/timer retries it. |
| confirmed | Explicit user confirmation; keep backups and recovery units for uninstall. |
| rolled-back | All originals restored and UI start succeeded. Uninstall is a no-op; reinstall can reuse the verified original backup set. |

After interrupted preparation, do not delete the only backup copy or overwrite a partially uploaded state directory. Verify all three live files are still original against the host `original.sha256` manifest (the two binary hashes must also match `AGENTS.md`). Preserve the entire state directory outside its active path before a fresh `--install` with a **new host backup directory**. This manual cleanup is limited to `initializing`; for pending/recovering/confirmed states use recovery instead.

## Durable timed recovery

This uses regular unit files under `/etc/systemd/system`, **not `systemd-run` transient units**. Enabling `rk-russian-rollback.timer` creates persistent boot startup registration. Its oneshot service runs the saved worker with `tick`, begins at 30 seconds after boot, and repeats 15 seconds after each activation. Failures also request systemd retries every 15 seconds.

Before the first live-file change, save a five-minute absolute deadline, the current Linux boot ID, and state `pending`. An enabled timer check restores originals when the deadline expires **or the boot ID changes**. A reboot therefore triggers recovery on the first timer activation, even with an incorrect wall clock. On the same boot the deadline depends on the system clock; a backward clock change can delay recovery. The timer's boot delay is intentional: recovery is not guaranteed to run before the UI first attempts startup after reboot. Live processes are not assumed to survive reboot.

Both the host and recovery worker serialize on the same lock. Confirmation rejects an expired/rebooted transaction, wrong installed hashes, missing/corrupt backups, or an inactive UI service. Confirmation can only record the user's report; service activity cannot prove that either keyboard works.

Restore verifies **all** backups and all current files before replacing any. It allows only original or known patched hashes; unknown modifications, symlinks or corrupted backups cause failure and leave the recovery state for diagnosis/retry. Never silently overwrite unknown files. If all current files are already original, restart the UI without staging (important for a full/read-only root filesystem). Otherwise stop the UI, stage all original copies beside their targets, verify, rename individually, and restart the UI before recording success. An interrupted restore stays recoverable; retries accept original/patched mixtures.

## Manual recovery over USB SSH

Keep working SSH access and the verified host backup directory. Prefer:

```sh
remarkable-russian-keyboard --status
remarkable-russian-keyboard --uninstall
```

If the host installer is unavailable but the saved worker exists, on the tablet:

```sh
sh /home/root/.local/share/remarkable-russian-keyboard/worker.sh status
sh /home/root/.local/share/remarkable-russian-keyboard/worker.sh uninstall
systemctl status rk-russian-rollback.timer rk-russian-rollback.service
journalctl -u rk-russian-rollback.service
```

A failed rollback is not success. Inspect logs, state, filesystem capacity/mounts and hashes. Do not run `--confirm` to silence a broken restore, remove backup files, disable the timer during pending/recovering state, or force-write over unrecognized firmware. Repair the underlying storage/service prerequisite and run `uninstall` again. Restore refuses files changed by an OS upgrade; review the new firmware separately.

If tablet backups are damaged, verified host copies may be needed. Reestablish a trusted original backup set and its metadata under expert review, then retry the saved recovery worker. Do not overwrite unknown device files or blindly upload a binary to a live path. If SSH itself is unavailable, this installer cannot recover the device; use the manufacturer's supported recovery process.

## Review and hardware validation before release

Review the Type Folio record interpretation against originals on an authorized device, Qt catalog round-trip rules, original fingerprints, filesystem capacity and metadata behavior, unit installation/enablement and boot dependencies. On a recoverable test tablet, verify both keyboard types and selectors, ё long-press, unmodified symbols/modifiers, timeout recovery, disconnect/power loss at each replacement, reboot before confirmation, failed restore retry, expiry/confirmation races, repeated operations and uninstall. Confirm that OS upgrades do not overwrite unknown files. Do not publish a release until the procedures and these results have been reviewed.
