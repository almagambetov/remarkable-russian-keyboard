#!/bin/sh
# Persistent recovery worker. All state is private, on the tablet's data partition.
set -eu
umask 077
S=/home/root/.local/share/remarkable-russian-keyboard
UNIT=/etc/systemd/system/rk-russian-rollback
TIMER=rk-russian-rollback.timer
SERVICE=rk-russian-rollback.service
BOOT=/proc/sys/kernel/random/boot_id
files='libepaper.so xochitl reMarkable_en.qm'

fail() { echo "REFUSED: $*" >&2; exit 1; }
target() {
    case "$1" in
        libepaper.so) echo /usr/lib/plugins/platforms/libepaper.so ;;
        xochitl) echo /usr/bin/xochitl ;;
        reMarkable_en.qm) echo /usr/share/remarkable/xochitl/translations/reMarkable_en.qm ;;
        *) fail 'Unknown target' ;;
    esac
}
state() { cat "$S/state"; }
setstate() { printf '%s\n' "$1" > "$S/state.next"; sync; mv -f "$S/state.next" "$S/state"; sync; }
# No executable manifests: fixed filenames and SHA-256 data only.
expected() { awk -v name="$2" '$2 == name {print $1}' "$S/$1.sha256"; }
check_file() {
    [ -f "$2" ] && [ ! -L "$2" ] || fail "Missing/unsafe file $2"
    actual=$(sha256sum "$2"); actual=${actual%% *}
    [ "$actual" = "$1" ] || fail "SHA-256 mismatch: $2"
}
verify_set() {
    for name in $files; do
        hash=$(expected "$1" "$name")
        [ "${#hash}" -eq 64 ] || fail 'Invalid manifest'
        check_file "$hash" "$S/$2/$name"
    done
}
verify_targets() {
    for name in $files; do check_file "$(expected "$1" "$name")" "$(target "$name")"; done
}
verify_recoverable() {
    verify_set original backups
    for name in $files; do
        dest=$(target "$name")
        [ -f "$dest" ] && [ ! -L "$dest" ] || fail "Unsafe target $dest"
        actual=$(sha256sum "$dest"); actual=${actual%% *}
        [ "$actual" = "$(expected original "$name")" ] ||
            [ "$actual" = "$(expected patched "$name")" ] || fail "Unrecognized current bytes: $dest"
    done
}
metadata() { stat -c '%a:%u:%g' "$1"; }
stage() {
    kind=$1
    folder=$2
    for name in $files; do
        dest=$(target "$name")
        staged="$dest.rk-stage"
        [ ! -e "$staged" ] && [ ! -L "$staged" ] || fail "Existing staging path: $staged"
        # A durable ownership marker permits cleaning a partial copy after
        # power loss without deleting a preexisting, unrelated staging file.
        : > "$S/staging-$name"
        sync
        # cp -p originals preserves mode and uid/gid; write through the staged inode.
        cp -p "$S/backups/$name" "$staged"
        cat "$S/$folder/$name" > "$staged"
        check_file "$(expected "$kind" "$name")" "$staged"
        [ "$(metadata "$staged")" = "$(metadata "$S/backups/$name")" ] || fail 'Staged metadata mismatch'
    done
    sync
}
clear_stages() {
    # Called only while holding the transaction lock. Verify before removing.
    for name in $files; do
        dest=$(target "$name")
        staged="$dest.rk-stage"
        if [ -e "$staged" ] || [ -L "$staged" ]; then
            [ ! -L "$staged" ] && [ -f "$staged" ] || fail 'Unsafe staging path'
            [ -f "$S/staging-$name" ] && [ ! -L "$S/staging-$name" ] || fail 'Unowned staging file'
            # A marked partial copy after power loss is expendable.
            rm -f "$staged"
        fi
        rm -f "$S/staging-$name"
    done
}
replace_stages() {
    kind=$1
    for name in $files; do
        dest=$(target "$name")
        check_file "$(expected "$kind" "$name")" "$dest.rk-stage"
        mv -f "$dest.rk-stage" "$dest"
        sync
    done
    verify_targets "$kind"
}
rollback() {
    # Retry the entire restore after any failure; never record success early.
    verify_recoverable
    setstate recovering
    # If failure happened before the first replacement, restart without needing
    # a writable /usr. This also recovers a failed staging copy on a full disk.
    changed=0
    for name in $files; do
        actual=$(sha256sum "$(target "$name")"); actual=${actual%% *}
        [ "$actual" = "$(expected original "$name")" ] || changed=1
    done
    if [ "$changed" -eq 1 ]; then
        systemctl stop xochitl.service
        clear_stages
        stage original backups
        replace_stages original
    fi
    systemctl start xochitl.service
    setstate rolled-back
    # Leave recovery units enabled: rolled-back is an idempotent no-op at boot.
}
expired() {
    # Missing/corrupted timing data must trigger recovery, never extend a trial.
    recorded_boot=$(cat "$S/boot-id") || return 0
    current_boot=$(cat "$BOOT") || return 0
    [ -n "$recorded_boot" ] && [ "$recorded_boot" = "$current_boot" ] || return 0
    deadline=$(cat "$S/deadline") || return 0
    now=$(date +%s) || return 0
    case "$deadline:$now" in *[!0-9:]*|:*|*:) return 0 ;; esac
    [ "$now" -ge "$deadline" ]
}

operation=${1:-status}
if [ "$operation" = inventory ]; then
    [ "$(id -u)" -eq 0 ] || fail 'Root SSH user required'
    firmware=$(sed -n 's/^REMARKABLE_RELEASE_VERSION=//p' /usr/share/remarkable/update.conf | tr -d '"')
    [ "$firmware" = 3.29.1.0 ] || fail "Unsupported firmware: $firmware"
    model=$(tr -d '\000' < /sys/firmware/devicetree/base/model)
    case "$model" in *'reMarkable 2'*|*'reMarkable 2.0'*) ;; *) fail "Unsupported model: $model" ;; esac
    for tool in sha256sum stat cp mv sync systemctl flock date awk tar cmp; do command -v "$tool" >/dev/null || fail "Missing tablet tool $tool"; done
    for name in $files; do
        dest=$(target "$name")
        [ -f "$dest" ] && [ ! -L "$dest" ] || fail "Unsafe target $dest"
        sha256sum "$dest"
        stat -c '%a %u %g' "$dest"
    done
    exit 0
fi
if [ "$operation" = reserve ]; then
    [ "$(id -u)" -eq 0 ] || fail 'Root SSH user required'
    # mkdir is exclusive: an existing transaction/backup is never replaced.
    mkdir -p "$(dirname "$S")"
    mkdir -m 700 "$S" || fail 'Existing transaction: use --status or --uninstall'
    printf 'initializing\n' > "$S/state"
    sync
    exit 0
fi
if [ ! -e "$S" ]; then
    [ "$operation" = status ] || fail 'No transaction to operate on'
    echo absent
    exit 0
fi
[ -d "$S" ] && [ ! -L "$S" ] && [ "$(stat -c '%a:%u' "$S")" = '700:0' ] || fail 'Unsafe transaction directory'
exec 9>"$S/lock"
flock -x 9
case "$operation" in
    prepare)
        [ "$(state)" = initializing ] || fail 'Transaction already prepared'
        verify_set patched payload
        # Check live originals before taking immutable backups.
        verify_targets original
        mkdir "$S/backups"
        for name in $files; do cp -p "$(target "$name")" "$S/backups/$name"; done
        verify_set original backups
        sync
        setstate prepared
        ;;
    install)
        case "$(state)" in
            confirmed) verify_targets patched; echo 'Already confirmed'; exit 0 ;;
            pending) verify_targets patched; expired && fail 'Expired: await rollback or run --uninstall'; echo 'Awaiting confirmation'; exit 0 ;;
            prepared|rolled-back) ;;
            *) fail 'Incomplete transaction: use --uninstall for recovery' ;;
        esac
        verify_targets original
        verify_set original backups
        verify_set patched payload
        [ ! -L "$UNIT.service" ] && [ ! -L "$UNIT.timer" ] || fail 'Unexpected systemd unit symlink'
        # Refuse to overwrite units owned by somebody else.
        for ext in service timer; do
            if [ -e "$UNIT.$ext" ]; then cmp -s "$S/rollback.$ext" "$UNIT.$ext" || fail 'Conflicting systemd unit';
            else cp "$S/rollback.$ext" "$UNIT.$ext"; chmod 644 "$UNIT.$ext"; fi
        done
        systemctl daemon-reload
        systemctl enable --now "$TIMER"
        systemctl is-enabled --quiet "$TIMER"
        systemctl is-active --quiet "$TIMER"
        # Arm durable state before stopping xochitl or staging any replacement.
        now=$(date +%s)
        case "$now" in ''|*[!0-9]*) fail 'Invalid tablet clock' ;; esac
        printf '%s\n' "$((now + 300))" > "$S/deadline"
        cat "$BOOT" > "$S/boot-id"
        [ -s "$S/boot-id" ] || fail 'Missing boot ID' 
        sync
        setstate pending
        systemctl stop xochitl.service
        clear_stages
        stage patched payload
        # Recheck live files immediately before first replacement.
        verify_targets original
        replace_stages patched
        systemctl start xochitl.service
        echo 'Installed; confirm within 300 seconds after checking both keyboards and selectors'
        ;;
    tick)
        case "$(state)" in
            pending) if expired; then rollback; fi ;;
            recovering) rollback ;;
            *) : ;;
        esac
        ;;
    confirm)
        [ "$(state)" = confirmed ] && { verify_targets patched; echo 'Already confirmed'; exit 0; }
        [ "$(state)" = pending ] || fail 'No pending installation'
        if expired; then rollback; fail 'Confirmation deadline expired; rolled back'; fi
        verify_set original backups
        verify_targets patched
        systemctl is-active --quiet xochitl.service || fail 'xochitl is not running'
        setstate confirmed
        echo 'Confirmed; backups retained'
        ;;
    uninstall)
        case "$(state)" in
            rolled-back) verify_targets original; echo 'Already restored' ;;
            prepared|pending|confirmed|recovering)
                systemctl enable --now "$TIMER"
                systemctl is-enabled --quiet "$TIMER"
                systemctl is-active --quiet "$TIMER"
                rollback ;;
            *) fail 'Unprepared transaction; originals were not changed. Preserve and inspect the state directory.' ;;
        esac
        ;;
    status)
        state
        case "$(state)" in
            prepared|rolled-back) verify_set original backups; verify_targets original ;;
            confirmed) verify_set original backups; verify_targets patched ;;
            pending|recovering) verify_recoverable ;;
            initializing) echo 'Preparation incomplete; originals were not changed' ;;
            *) fail 'Unknown transaction state' ;;
        esac
        for name in $files; do sha256sum "$(target "$name")"; done
        ;;
    *) fail 'Unknown operation' ;;
esac
