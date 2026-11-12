import subprocess

import pytest

from rk_installer import cli
from rk_installer.patches import Refused
from rk_installer.transport import SSH


@pytest.mark.parametrize("host", ["-oProxyCommand=bad", "root@host;touch /tmp/bad", "user@host", "root@host\nwhoami", "root@$(whoami)"])
def test_ssh_rejects_options_and_shell_injection(host):
    with pytest.raises(Refused):
        SSH(host)


def test_ssh_keeps_host_key_checks_and_quotes_remote_args(monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, b"okay", b"")
    monkeypatch.setattr(subprocess, "run", run)
    assert SSH("root@10.11.99.1").run(["cat", "--", "/path with spaces/$(bad)"]) == b"okay"
    command, kwargs = calls[0]
    assert "-oStrictHostKeyChecking=yes" in command
    assert "-oBatchMode=yes" in command
    assert command[-1] == "cat -- '/path with spaces/$(bad)'"
    assert kwargs.get("shell") is not True


def test_ssh_preserves_remote_failures(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 42, b"", b"hash mismatch"))
    with pytest.raises(Refused, match="42.*hash mismatch"):
        SSH("root@tablet").read("/file")


def test_cli_requires_one_operation():
    with pytest.raises(SystemExit):
        cli.parser().parse_args([])
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["--check", "--install"])


def test_cli_returns_failure_for_unsupported_host(monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    assert cli.main(["--check"]) == 1
    assert "Linux" in capsys.readouterr().err


def test_cli_reports_errors_without_claiming_success(monkeypatch, capsys):
    def fail(*args): raise Refused("unsupported firmware")
    monkeypatch.setattr(cli, "action", fail)
    assert cli.main(["--check"]) == 1
    assert "unsupported firmware" in capsys.readouterr().err
