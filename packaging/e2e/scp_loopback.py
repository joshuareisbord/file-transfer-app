"""Exercise the real SCP backend against an isolated loopback OpenSSH server."""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from work_transfer_app.transfer import (
    ConnectionConfig,
    ScpTransferBackend,
    TransferJob,
    TransferState,
)

LOOPBACK_HOST = "127.0.0.1"
STARTUP_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class LoopbackEnvironment:
    """Paths and connection details for one isolated transfer run."""

    root: Path
    port: int
    client_key: Path
    known_hosts: Path
    sshd_config: Path
    source_file: Path
    remote_directory: Path
    remote_reference: str
    injection_marker: Path


def _require_command(command: str) -> str:
    """Resolve a required Ubuntu command or fail with an actionable message."""

    resolved = shutil.which(command)
    if resolved is None:
        raise RuntimeError(f"Required command is not installed: {command}")
    return resolved


def _generate_key(destination: Path) -> None:
    """Generate one passwordless Ed25519 key pair for the isolated test."""

    subprocess.run(
        [
            _require_command("ssh-keygen"),
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-f",
            str(destination),
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def _reserve_loopback_port() -> int:
    """Ask the kernel for an unused high port for the temporary SSH server."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind((LOOPBACK_HOST, 0))
        return int(listener.getsockname()[1])


def _write_known_hosts(host_key: Path, known_hosts: Path, port: int) -> None:
    """Trust only the generated host key at this run's loopback endpoint."""

    public_key_fields = host_key.with_suffix(".pub").read_text().split()
    if len(public_key_fields) < 2:
        raise RuntimeError("Generated SSH host public key is invalid")
    key_type, key_data = public_key_fields[:2]
    known_hosts.write_text(
        f"[{LOOPBACK_HOST}]:{port} {key_type} {key_data}\n",
        encoding="utf-8",
    )


def _write_sshd_config(
    destination: Path,
    host_key: Path,
    authorized_keys: Path,
    port: int,
) -> None:
    """Configure a loopback-only server with public-key authentication and SFTP."""

    destination.write_text(
        "\n".join(
            (
                f"Port {port}",
                f"ListenAddress {LOOPBACK_HOST}",
                f"HostKey {host_key}",
                f"PidFile {destination.parent / 'sshd.pid'}",
                f"AuthorizedKeysFile {authorized_keys}",
                "AuthenticationMethods publickey",
                "PubkeyAuthentication yes",
                "PasswordAuthentication no",
                "KbdInteractiveAuthentication no",
                "PermitEmptyPasswords no",
                "PermitRootLogin prohibit-password",
                "StrictModes no",
                "UsePAM no",
                "UseDNS no",
                "PrintMotd no",
                "LogLevel ERROR",
                "Subsystem sftp internal-sftp",
                "",
            )
        ),
        encoding="utf-8",
    )


def _prepare_environment(root: Path) -> LoopbackEnvironment:
    """Create temporary keys, server configuration, and transfer files."""

    client_key = root / "client_key"
    host_key = root / "host_key"
    known_hosts = root / "known_hosts"
    authorized_keys = root / "authorized_keys"
    sshd_config = root / "sshd_config"
    remote_directory = Path.home() / f".work transfer; literal {root.name}"
    remote_reference = f"~/{remote_directory.name}"
    injection_marker = Path.home() / "WORK_TRANSFER_INJECTED"
    source_file = root / "payload;touch${IFS}WORK_TRANSFER_INJECTED;#.bin"
    port = _reserve_loopback_port()

    injection_marker.unlink(missing_ok=True)
    remote_directory.mkdir()
    source_file.write_bytes((b"work-transfer-loopback\x00\xff" * 131_072)[:2_097_152])
    _generate_key(client_key)
    _generate_key(host_key)
    authorized_keys.write_bytes(client_key.with_suffix(".pub").read_bytes())
    _write_known_hosts(host_key, known_hosts, port)
    _write_sshd_config(sshd_config, host_key, authorized_keys, port)

    return LoopbackEnvironment(
        root=root,
        port=port,
        client_key=client_key,
        known_hosts=known_hosts,
        sshd_config=sshd_config,
        source_file=source_file,
        remote_directory=remote_directory,
        remote_reference=remote_reference,
        injection_marker=injection_marker,
    )


def _wait_for_sshd(process: subprocess.Popen[str], port: int) -> None:
    """Wait for the SSH listener or surface its startup diagnostics."""

    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            diagnostics = process.stderr.read().strip() if process.stderr else ""
            raise RuntimeError(f"sshd exited during startup: {diagnostics}")
        try:
            with socket.create_connection((LOOPBACK_HOST, port), timeout=0.25):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError(f"sshd did not listen within {STARTUP_TIMEOUT_SECONDS:g}s")


def _start_sshd(environment: LoopbackEnvironment) -> subprocess.Popen[str]:
    """Validate and start the isolated OpenSSH daemon."""

    sshd = _require_command("sshd")
    Path("/run/sshd").mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [sshd, "-t", "-f", str(environment.sshd_config)],
        check=True,
        capture_output=True,
        text=True,
    )
    process = subprocess.Popen(
        [sshd, "-D", "-e", "-f", str(environment.sshd_config)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_sshd(process, environment.port)
    except Exception:
        _stop_sshd(process)
        raise
    return process


def _stop_sshd(process: subprocess.Popen[str]) -> None:
    """Stop the temporary SSH daemon, escalating only after a timeout."""

    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


async def _transfer_and_verify(environment: LoopbackEnvironment) -> str:
    """Transfer a real file and verify its bytes, checksum, and atomic cleanup."""

    config = ConnectionConfig(
        host=LOOPBACK_HOST,
        username="root",
        port=environment.port,
        identity_file=environment.client_key,
        known_hosts=environment.known_hosts,
    )
    backend = ScpTransferBackend()
    connection_result = await backend.test_connection(config)
    if not connection_result.is_success:
        raise AssertionError(
            f"Loopback SSH connection failed: {connection_result.message}"
        )

    job = TransferJob.create(
        environment.source_file,
        environment.remote_reference,
        config,
    )
    result = await backend.transfer(job, lambda _progress: None)
    if result.state is not TransferState.COMPLETED:
        raise AssertionError(f"SCP transfer failed: {result.message or result.state}")

    expected = environment.source_file.read_bytes()
    destination = environment.remote_directory / environment.source_file.name
    actual = destination.read_bytes()
    if actual != expected:
        raise AssertionError("Transferred file bytes do not match the source")

    expected_checksum = hashlib.sha256(expected).hexdigest()
    actual_checksum = hashlib.sha256(actual).hexdigest()
    if actual_checksum != expected_checksum:
        raise AssertionError("Transferred file checksum does not match the source")
    if list(environment.remote_directory.glob(".*.part")):
        raise AssertionError("Transfer left a staging .part file behind")
    if environment.injection_marker.exists():
        raise AssertionError("Remote path escaped the intended SCP command")
    return actual_checksum


def main() -> None:
    """Run the isolated Ubuntu/OpenSSH loopback E2E verification."""

    with tempfile.TemporaryDirectory(prefix="work-transfer-e2e-") as directory:
        environment = _prepare_environment(Path(directory))
        sshd_process = _start_sshd(environment)
        try:
            checksum = asyncio.run(_transfer_and_verify(environment))
        finally:
            _stop_sshd(sshd_process)
            shutil.rmtree(environment.remote_directory, ignore_errors=True)
            environment.injection_marker.unlink(missing_ok=True)
    print(f"SCP loopback E2E passed (sha256={checksum})")


if __name__ == "__main__":
    main()
