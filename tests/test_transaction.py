"""Run the real POSIX recovery worker against synthetic files and fake systemd.

Only absolute device paths and privilege checks are adapted to the temporary
sandbox. These tests do not contact SSH, modify /usr, or claim hardware coverage.
"""
import argparse
import io
import os
from pathlib import Path
import subprocess
import tarfile

import pytest

from rk_installer import cli
from rk_installer.patches import Refused, digest


class Device:
    def __init__(self, root):
        self.root = root
        self.base = root / "home/root/.local/share/remarkable-russian-keyboard"
        self.units = root / "etc/systemd/system"
        self.units.mkdir(parents=True)
        self.boot = root / "proc/sys/kernel/random/boot_id"
        self.boot.parent.mkdir(parents=True)
        self.boot.write_text("boot-one\n")
        config = root / "usr/share/remarkable/update.conf"
        config.parent.mkdir(parents=True)
        config.write_text('REMARKABLE_RELEASE_VERSION="3.29.1.0"\n')
        model = root / "sys/firmware/devicetree/base/model"
        model.parent.mkdir(parents=True)
        model.write_bytes(b"reMarkable 2.0\0")
        self.originals = {n: f"synthetic original {n}".encode() for n in cli.TARGETS}
        self.patched = {n: b"patched " + b for n, b in self.originals.items()}
        for n, data in self.originals.items():
            path = self.path(cli.TARGETS[n])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            path.chmod(0o755 if n == "xochitl" else 0o644)
        self.bin = root / "bin"
        self.bin.mkdir()
        self.log = root / "commands.log"
        self.log.write_text("")
        self.env = dict(os.environ, PATH=str(self.bin) + ":" + os.environ["PATH"], RK_TEST=str(root))
        self.executable("systemctl", '''#!/bin/sh
echo "systemctl $*" >> "$RK_TEST/commands.log"
if [ -f "$RK_TEST/fail-systemctl" ] && [ "$(cat "$RK_TEST/fail-systemctl")" = "$*" ]; then exit 1; fi
exit 0
''')
        self.executable("sync", '#!/bin/sh\necho sync >> "$RK_TEST/commands.log"\n')
        self.executable("id", '#!/bin/sh\necho 0\n')
        self.executable("mv", '''#!/bin/sh
echo "mv $*" >> "$RK_TEST/commands.log"
case "$*" in
    *rk-stage*)
        n=0; [ ! -f "$RK_TEST/moves" ] || n=$(cat "$RK_TEST/moves")
        n=$((n + 1)); echo "$n" > "$RK_TEST/moves"
        if [ -f "$RK_TEST/fail-move" ] && [ "$n" = "$(cat "$RK_TEST/fail-move")" ]; then exit 1; fi
        ;;
esac
exec /usr/bin/mv "$@"
''')
        self.worker = cli.WORKER.decode()
        # Map all absolute production filesystem locations into the sandbox.
        for prefix in ("/home/root/", "/etc/systemd/", "/proc/sys/", "/usr/", "/sys/firmware/"):
            self.worker = self.worker.replace(prefix, str(root) + prefix)
        self.worker = self.worker.replace("'700:0'", f"'700:{os.getuid()}'")

    def path(self, absolute):
        return self.root / absolute.lstrip("/")

    def executable(self, name, content):
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o755)

    def run(self, operation, ok=True):
        result = subprocess.run(["sh", "-s", "--", operation], input=self.worker.encode(),
                                env=self.env, capture_output=True)
        if ok:
            assert result.returncode == 0, result.stderr.decode()
        else:
            assert result.returncode != 0, result.stdout.decode()
        return result

    def prepare(self):
        self.run("reserve")
        with tarfile.open(fileobj=io.BytesIO(cli.archive(self.originals, self.patched))) as archive:
            archive.extractall(self.base, filter="data")
        self.run("prepare")

    def state(self):
        return (self.base / "state").read_text().strip()

    def assert_targets(self, data):
        for name, value in data.items():
            target = self.path(cli.TARGETS[name])
            assert target.read_bytes() == value
            assert target.stat().st_mode & 0o777 == (0o755 if name == "xochitl" else 0o644)

    def expire(self):
        (self.base / "deadline").write_text("0\n")


@pytest.fixture
def device(tmp_path):
    return Device(tmp_path)


def test_install_confirm_uninstall_idempotent(device):
    device.run("inventory")
    assert device.run("status").stdout.strip() == b"absent"
    device.prepare()
    device.assert_targets(device.originals)
    device.run("install")
    assert device.state() == "pending"
    device.assert_targets(device.patched)
    backups = {n: (device.base / "backups" / n).read_bytes() for n in cli.TARGETS}
    device.run("install")
    device.run("confirm")
    device.run("confirm")
    device.run("install")
    assert device.state() == "confirmed"
    device.run("tick")
    device.assert_targets(device.patched)
    device.run("uninstall")
    device.run("uninstall")
    assert device.state() == "rolled-back"
    device.assert_targets(device.originals)
    assert backups == device.originals
    assert "OnBootSec=30s" in (device.base / "rollback.timer").read_text()
    log = device.log.read_text()
    assert log.index("systemctl enable --now") < log.index("systemctl stop xochitl") < log.index("rk-stage")
    assert "Restart=on-failure" in (device.base / "rollback.service").read_text()


def test_timeout_and_late_confirmation(device):
    device.prepare()
    device.run("install")
    device.expire()
    device.run("confirm", ok=False)
    device.assert_targets(device.originals)
    assert device.state() == "rolled-back"


def test_tick_timeout(device):
    device.prepare()
    device.run("install")
    device.expire()
    device.run("tick")
    device.run("tick")
    device.assert_targets(device.originals)


def test_reboot_forces_rollback_even_before_deadline(device):
    device.prepare()
    device.run("install")
    device.boot.write_text("boot-two\n")
    device.run("tick")
    device.assert_targets(device.originals)


@pytest.mark.parametrize("move", [1, 2, 3])
def test_interrupted_install_restores_mixed_targets(device, move):
    device.prepare()
    (device.root / "fail-move").write_text(str(move))
    device.run("install", ok=False)
    assert device.state() == "pending"
    device.expire()
    device.run("tick")
    assert device.state() == "rolled-back"
    device.assert_targets(device.originals)


def test_failed_rollback_retries_without_false_success(device):
    device.prepare()
    device.run("install")
    device.expire()
    (device.root / "fail-move").write_text("5")  # second restore rename
    device.run("tick", ok=False)
    assert device.state() == "recovering"
    device.run("tick")
    assert device.state() == "rolled-back"
    device.assert_targets(device.originals)


def test_start_failure_during_restore_is_retried(device):
    device.prepare()
    device.run("install")
    device.expire()
    fail = device.root / "fail-systemctl"
    fail.write_text("start xochitl.service")
    device.run("tick", ok=False)
    assert device.state() == "recovering"
    fail.unlink()
    device.run("tick")
    assert device.state() == "rolled-back"


def test_corrupt_backup_blocks_all_restore_writes(device):
    device.prepare()
    device.run("install")
    (device.base / "backups/xochitl").write_bytes(b"corrupt")
    device.expire()
    device.run("tick", ok=False)
    device.assert_targets(device.patched)
    assert device.state() == "pending"
    device.run("confirm", ok=False)


def test_unrecognized_current_bytes_are_never_overwritten(device):
    device.prepare()
    device.run("install")
    target = device.path(cli.TARGETS["xochitl"])
    target.write_bytes(b"unknown modification")
    device.expire()
    device.run("tick", ok=False)
    assert target.read_bytes() == b"unknown modification"
    device.run("confirm", ok=False)


def test_timer_failure_prevents_modification(device):
    device.prepare()
    (device.root / "fail-systemctl").write_text("is-active --quiet rk-russian-rollback.timer")
    device.run("install", ok=False)
    assert device.state() == "prepared"
    device.assert_targets(device.originals)


def test_no_backup_overwrite_or_conflicting_units(device):
    device.prepare()
    device.run("reserve", ok=False)
    device.run("prepare", ok=False)
    (device.units / "rk-russian-rollback.service").write_text("someone else's unit\n")
    device.run("install", ok=False)
    assert device.state() == "prepared"
    device.assert_targets(device.originals)


def test_pending_staging_failure_recovers(device):
    device.prepare()
    device.executable("cp", '#!/bin/sh\ncase "$*" in *rk-stage*) exit 1;; esac\nexec /usr/bin/cp "$@"\n')
    device.run("install", ok=False)
    assert device.state() == "pending"
    (device.bin / "cp").unlink()
    device.expire()
    device.run("tick")
    device.assert_targets(device.originals)


def test_bad_firmware_and_model_refused(device):
    config = device.path("/usr/share/remarkable/update.conf")
    config.write_text('REMARKABLE_RELEASE_VERSION="3.30.0.0"\n')
    device.run("inventory", ok=False)
    config.write_text('REMARKABLE_RELEASE_VERSION="3.29.1.0"\n')
    device.path("/sys/firmware/devicetree/base/model").write_text("reMarkable Paper Pro")
    device.run("inventory", ok=False)


def test_symlink_target_refused(device):
    path = device.path(cli.TARGETS["xochitl"])
    other = device.root / "unrelated"
    other.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(other)
    device.run("inventory", ok=False)


def test_rollback_from_confirmed_arms_recovery_before_writes(device):
    device.prepare()
    device.run("install")
    device.run("confirm")
    (device.root / "fail-move").write_text("4")
    device.run("uninstall", ok=False)
    assert device.state() == "recovering"
    device.run("tick")
    device.assert_targets(device.originals)


class MockSSH:
    """Mock network only; execute the actual device worker and archive handling."""
    def __init__(self, device): self.device = device
    def script(self, worker, operation):
        assert worker == cli.WORKER
        result = self.device.run(operation)
        return result.stdout
    def read(self, path): return self.device.path(path).read_bytes()
    def run(self, args, data):
        assert args == ["tar", "-xf", "-", "-C", cli.STATE]
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            archive.extractall(self.device.base, filter="data")
        return b""


def arguments(**kwargs):
    result = dict(check=False, install=False, confirm=False, status=False, uninstall=False,
                  backup_dir=None, lconvert="unused", lrelease="unused")
    result.update(kwargs)
    return argparse.Namespace(**result)


def test_mocked_ssh_complete_host_lifecycle(device, monkeypatch, tmp_path):
    ssh = MockSSH(device)
    from rk_installer import patches
    for name in patches.HASHES:
        monkeypatch.setitem(patches.HASHES, name, digest(device.originals[name]))
    monkeypatch.setattr(cli, "build", lambda originals, *_: (device.patched, "SyntheticContext"))
    backup = tmp_path / "host-backup"
    assert "Compatible" in cli.action(arguments(check=True), ssh)
    assert not device.base.exists()
    assert "Installed" in cli.action(arguments(install=True, backup_dir=backup), ssh)
    for name, data in device.originals.items():
        assert (backup / name).read_bytes() == data
    assert "pending" in cli.action(arguments(status=True), ssh)
    assert "Awaiting" in cli.action(arguments(install=True), ssh)
    assert "Confirmed" in cli.action(arguments(confirm=True), ssh)
    cli.action(arguments(uninstall=True), ssh)
    device.assert_targets(device.originals)


def test_host_backup_does_not_overwrite_user_files(tmp_path):
    existing = tmp_path / "backup"
    existing.mkdir()
    file = existing / "xochitl"
    file.write_bytes(b"user data")
    with pytest.raises(FileExistsError):
        cli.backup_host(existing, {"xochitl": b"new data"}, "context")
    assert file.read_bytes() == b"user data"


def test_failed_staging_can_restore_ui_without_writable_targets(device):
    device.prepare()
    # cp to /usr fails forever, simulating a read-only/full filesystem.
    device.executable("cp", '#!/bin/sh\ncase "$*" in *rk-stage*) exit 1;; esac\nexec /usr/bin/cp "$@"\n')
    device.run("install", ok=False)
    device.expire()
    device.run("tick")
    assert device.state() == "rolled-back"
    device.assert_targets(device.originals)
    assert device.log.read_text().rstrip().endswith("sync")
    assert "systemctl start xochitl.service" in device.log.read_text()


def test_corrupt_payload_is_rejected_before_stopping_ui(device):
    device.prepare()
    (device.base / "payload/xochitl").write_bytes(b"corrupt")
    device.run("install", ok=False)
    device.assert_targets(device.originals)
    assert "stop xochitl" not in device.log.read_text()


def test_confirmation_requires_running_ui_and_valid_backup(device):
    device.prepare()
    device.run("install")
    fail = device.root / "fail-systemctl"
    fail.write_text("is-active --quiet xochitl.service")
    device.run("confirm", ok=False)
    assert device.state() == "pending"
    fail.unlink()
    (device.base / "backups/libepaper.so").write_bytes(b"bad backup")
    device.run("confirm", ok=False)
    assert device.state() == "pending"


def test_interrupted_preparation_is_diagnosable_and_never_overwritten(device):
    device.run("reserve")
    result = device.run("status")
    assert result.stdout.startswith(b"initializing\n")
    device.run("reserve", ok=False)
    device.run("uninstall", ok=False)
    device.assert_targets(device.originals)


def test_staging_symlink_is_never_followed(device):
    device.prepare()
    unrelated = device.root / "unrelated"
    unrelated.write_bytes(b"user data")
    staged = device.path(cli.TARGETS["xochitl"] + ".rk-stage")
    staged.symlink_to(unrelated)
    device.run("install", ok=False)
    assert unrelated.read_bytes() == b"user data"
    device.assert_targets(device.originals)


def test_rolled_back_install_reuses_backups(device):
    device.prepare()
    device.run("install")
    device.expire()
    device.run("tick")
    backups = {n: (device.base / "backups" / n).read_bytes() for n in cli.TARGETS}
    device.run("install")
    device.run("confirm")
    device.assert_targets(device.patched)
    assert {n: (device.base / "backups" / n).read_bytes() for n in cli.TARGETS} == backups


def test_mocked_ssh_real_patches_and_device_lifecycle(device, synthetic_folio, synthetic_xochitl, synthetic_catalog, qt_tools, tmp_path):
    device.originals = {"libepaper.so": synthetic_folio, "xochitl": synthetic_xochitl, "reMarkable_en.qm": synthetic_catalog}
    for name, data in device.originals.items():
        device.path(cli.TARGETS[name]).write_bytes(data)
    ssh = MockSSH(device)
    flags = dict(lconvert=qt_tools[0], lrelease=qt_tools[1])
    assert "Compatible originals" in cli.action(arguments(check=True, **flags), ssh)
    assert "Installed" in cli.action(arguments(install=True, backup_dir=tmp_path / "backups", **flags), ssh)
    for name, original in device.originals.items():
        installed = device.path(cli.TARGETS[name]).read_bytes()
        assert installed != original
        assert (tmp_path / "backups" / name).read_bytes() == original
    cli.action(arguments(confirm=True), ssh)
    cli.action(arguments(uninstall=True), ssh)
    device.assert_targets(device.originals)


def test_host_rejects_repository_backup_directory():
    with pytest.raises(Refused, match="outside the repository"):
        cli.backup_host(Path(cli.__file__).parent / "must-not-write", {"xochitl": b"secret firmware"}, "context")


def test_unrelated_regular_staging_file_is_preserved(device):
    device.prepare()
    staged = device.path(cli.TARGETS["xochitl"] + ".rk-stage")
    staged.write_bytes(b"existing user file")
    device.run("install", ok=False)
    assert staged.read_bytes() == b"existing user file"
    device.assert_targets(device.originals)


@pytest.mark.parametrize("timing_file,content", [("deadline", ""), ("deadline", "broken"), ("boot-id", "")])
def test_invalid_durable_timing_forces_recovery(device, timing_file, content):
    device.prepare()
    device.run("install")
    (device.base / timing_file).write_text(content)
    device.run("tick")
    assert device.state() == "rolled-back"
    device.assert_targets(device.originals)
