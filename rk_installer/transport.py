"""OpenSSH transport; host keys and normal SSH authentication stay enabled."""
from __future__ import annotations

import re
import shlex
import subprocess

from .patches import Refused


class SSH:
    def __init__(self, host: str):
        if not re.fullmatch(r"root@[A-Za-z0-9][A-Za-z0-9_.-]*", host):
            raise Refused("Use a root@hostname or root@IPv4 SSH destination")
        self.command = ["ssh", "-oBatchMode=yes", "-oStrictHostKeyChecking=yes",
                        "-oConnectTimeout=10", "--", host]

    def run(self, args: list[str], data: bytes | None = None) -> bytes:
        result = subprocess.run(self.command + [shlex.join(args)], input=data,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise Refused(f"SSH command failed ({result.returncode}): {detail}")
        return result.stdout

    def script(self, script: bytes, operation: str) -> bytes:
        return self.run(["sh", "-s", "--", operation], script)

    def read(self, path: str) -> bytes:
        return self.run(["cat", "--", path])
