"""Linux host entry point. Device changes occur only with --install/confirm/uninstall."""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

from .patches import Refused, digest, verify_original, patch_folio, patch_xochitl, patch_catalog
from .transport import SSH

STATE = "/home/root/.local/share/remarkable-russian-keyboard"
TARGETS = {"libepaper.so": "/usr/lib/plugins/platforms/libepaper.so",
           "xochitl": "/usr/bin/xochitl",
           "reMarkable_en.qm": "/usr/share/remarkable/xochitl/translations/reMarkable_en.qm"}
WORKER = Path(__file__).with_name("device.sh").read_bytes()
SERVICE = f"""[Unit]
Description=Recover unconfirmed Russian keyboard installation
After=local-fs.target
RequiresMountsFor={STATE} /usr

[Service]
Type=oneshot
ExecStart=/bin/sh {STATE}/worker.sh tick
Restart=on-failure
RestartSec=15s
""".encode()
TIMER = b"""[Unit]
Description=Check durable Russian keyboard rollback state

[Timer]
OnBootSec=30s
OnUnitActiveSec=15s
AccuracySec=1s
Unit=rk-russian-rollback.service

[Install]
WantedBy=timers.target
"""


def manifest(blobs: dict[str, bytes]) -> bytes:
    return "".join(f"{digest(data)}  {name}\n" for name, data in blobs.items()).encode()


def download(ssh: SSH) -> dict[str, bytes]:
    ssh.script(WORKER, "inventory")
    originals = {name: ssh.read(path) for name, path in TARGETS.items()}
    for name in ("libepaper.so", "xochitl"):
        verify_original(name, originals[name])
    return originals


def build(originals: dict[str, bytes], lconvert: str, lrelease: str) -> tuple[dict[str, bytes], str]:
    catalog, context = patch_catalog(originals["reMarkable_en.qm"], lconvert, lrelease)
    return {"libepaper.so": patch_folio(originals["libepaper.so"]),
            "xochitl": patch_xochitl(originals["xochitl"]), "reMarkable_en.qm": catalog}, context


def backup_host(directory: Path, originals: dict[str, bytes], context: str) -> None:
    # Refuse all preexisting directories; never merge different tablets/backups.
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() and directory.resolve().is_relative_to(parent):
            raise Refused("Keep proprietary backups outside the repository")
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    os.chmod(directory, 0o700)
    for name, data in originals.items():
        path = directory / name
        with path.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if path.read_bytes() != data:
            raise Refused(f"Host backup verification failed: {path}")
    (directory / "original.sha256").write_bytes(manifest(originals))
    (directory / "metadata.json").write_text(json.dumps({"firmware": "3.29.1.0", "translation_context": context}, indent=2) + "\n")
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def archive(originals: dict[str, bytes], patched: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    entries = {"worker.sh": WORKER, "original.sha256": manifest(originals),
               "patched.sha256": manifest(patched), "rollback.service": SERVICE, "rollback.timer": TIMER}
    entries.update({"payload/" + name: value for name, value in patched.items()})
    with tarfile.open(fileobj=stream, mode="w") as tar:
        for name, value in entries.items():
            member = tarfile.TarInfo(name)
            member.size, member.mode = len(value), 0o600
            tar.addfile(member, io.BytesIO(value))
    return stream.getvalue()


def action(args, ssh: SSH) -> str:
    status = ssh.script(WORKER, "status").decode().strip()
    state = status.splitlines()[0]
    if args.status:
        return status
    if args.confirm or args.uninstall:
        if state == "absent":
            if args.uninstall:
                return "No installation; nothing to restore"
            raise Refused("No pending installation")
        verify_worker(ssh)
        if args.confirm:
            ssh.script(WORKER, "inventory")
        return ssh.script(WORKER, "confirm" if args.confirm else "uninstall").decode().strip()
    if args.install and state != "absent":
        verify_worker(ssh)
        # Reusing a completed transaction preserves its original backups.
        ssh.script(WORKER, "inventory")  # firmware/model remain mandatory after an OS update
        return ssh.script(WORKER, "install").decode().strip()
    if state != "absent":
        raise Refused("Existing transaction: inspect --status; --check requires pristine originals")
    originals = download(ssh)
    patched, context = build(originals, args.lconvert, args.lrelease)
    if args.check:
        return f"Compatible originals; all three patches generated and validated. Qt context: {context}"
    if args.backup_dir is None:
        raise Refused("--install requires a new --backup-dir outside the repository")
    backup_host(args.backup_dir.expanduser().absolute(), originals, context)
    ssh.script(WORKER, "reserve")
    ssh.run(["tar", "-xf", "-", "-C", STATE], archive(originals, patched))
    verify_worker(ssh)
    ssh.script(WORKER, "prepare")
    return ssh.script(WORKER, "install").decode().strip()


def verify_worker(ssh: SSH) -> None:
    if ssh.read(STATE + "/worker.sh") != WORKER:
        raise Refused("Different/missing recovery worker; use the installer version that created this transaction")


def parser():
    result = argparse.ArgumentParser(description="Development installer: reMarkable 2 firmware 3.29.1.0 only")
    operations = result.add_mutually_exclusive_group(required=True)
    for op in ("check", "install", "confirm", "status", "uninstall"):
        operations.add_argument("--" + op, action="store_true")
    result.add_argument("--host", default="root@10.11.99.1")
    result.add_argument("--backup-dir", type=Path)
    qt_bin = Path(os.environ.get("RK_QT_BIN", "/usr/lib/qt6/bin"))
    result.add_argument("--lconvert", default=str(qt_bin / "lconvert"))
    result.add_argument("--lrelease", default=str(qt_bin / "lrelease"))
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if sys.platform != "linux":
            raise Refused("This installer supports Linux hosts only")
        print(action(args, SSH(args.host)))
    except (Refused, OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
