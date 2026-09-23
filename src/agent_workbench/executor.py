from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from .models import ProjectContext, WorkbenchError

PINNED_IMAGE_PATTERN = re.compile(
    r"^(?:[^\s@]+@)?sha256:[0-9a-f]{64}$"
)
Runner = Callable[..., subprocess.CompletedProcess[bytes]]
CONTAINER_USER_PATTERN = re.compile(r"^(?P<uid>[1-9][0-9]*):(?P<gid>[0-9]+)$")


def default_container_user() -> str:
    """Use the owning POSIX user for bind mounts while never selecting root."""
    getuid = getattr(os, "getuid", None)
    getgid = getattr(os, "getgid", None)
    if callable(getuid) and callable(getgid):
        uid = getuid()
        gid = getgid()
        if uid > 0:
            return f"{uid}:{gid}"
    return "65532:65532"


class ContainerConfigurationError(WorkbenchError):
    """Raised when container execution is configured without secure defaults."""


class ContainerExecutionError(WorkbenchError):
    """Raised when Docker cannot start or complete an isolated command."""


class ContainerTimeout(ContainerExecutionError):
    """Raised after a timed-out container has been forcefully removed."""


@dataclass(frozen=True)
class ContainerLimits:
    timeout_seconds: float = 30.0
    memory: str = "256m"
    cpus: float = 1.0
    pids: int = 64
    tmpfs_size: str = "64m"
    max_output_bytes: int = 200_000

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ContainerConfigurationError("Container timeout must be positive.")
        if self.cpus <= 0 or self.pids < 1 or self.max_output_bytes < 1:
            raise ContainerConfigurationError("Container resource limits must be positive.")


@dataclass(frozen=True)
class ContainerResult:
    exit_code: int
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class ContainerExecutor:
    """Runs an allowlisted argv in a locked-down, project-scoped Docker container."""

    def __init__(
        self,
        image: str,
        allowed_executables: Sequence[str],
        *,
        docker_binary: str = "docker",
        container_user: str | None = None,
        limits: ContainerLimits | None = None,
        runner: Runner = subprocess.run,
    ) -> None:
        if not PINNED_IMAGE_PATTERN.fullmatch(image):
            raise ContainerConfigurationError(
                "Container image must be a local sha256 image ID or pinned as "
                "name@sha256:<64 lowercase hex characters>."
            )
        normalized = tuple(dict.fromkeys(item.strip() for item in allowed_executables))
        if not normalized or any(
            not item or "/" in item or "\\" in item or any(char.isspace() for char in item)
            for item in normalized
        ):
            raise ContainerConfigurationError(
                "Container executable allowlist must contain plain executable names."
            )
        if not docker_binary.strip():
            raise ContainerConfigurationError("Docker binary is required.")
        selected_user = container_user or default_container_user()
        if not CONTAINER_USER_PATTERN.fullmatch(selected_user):
            raise ContainerConfigurationError(
                "Container user must be a non-root numeric UID:GID pair."
            )
        self.image = image
        self.allowed_executables = frozenset(normalized)
        self.docker_binary = docker_binary
        self.container_user = selected_user
        self.limits = limits or ContainerLimits()
        self._runner = runner

    def execute(self, context: ProjectContext, argv: object) -> ContainerResult:
        if not isinstance(argv, list) or not argv:
            raise ContainerExecutionError("argv must be a non-empty JSON array of strings.")
        if any(not isinstance(item, str) or not item or "\x00" in item for item in argv):
            raise ContainerExecutionError("Every argv item must be a non-empty string.")
        if argv[0] not in self.allowed_executables:
            raise ContainerExecutionError(f"Executable is not allowlisted: {argv[0]}")

        container_name = f"agent-workbench-{uuid.uuid4().hex}"
        command = self._docker_command(context, container_name, argv)
        try:
            completed = self._runner(
                command,
                capture_output=True,
                text=False,
                timeout=self.limits.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            self._cleanup(container_name)
            raise ContainerTimeout(
                f"Container exceeded the {self.limits.timeout_seconds:g}-second timeout."
            ) from error
        except OSError as error:
            raise ContainerExecutionError(
                f"Docker invocation failed with {type(error).__name__}."
            ) from error

        stdout, stdout_truncated = self._bounded_text(completed.stdout or b"")
        stderr, stderr_truncated = self._bounded_text(completed.stderr or b"")
        return ContainerResult(
            exit_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )

    def _docker_command(
        self, context: ProjectContext, container_name: str, argv: list[str]
    ) -> list[str]:
        project_root = context.root.resolve()
        mounts = (
            (project_root / "inputs", "/workspace/inputs", True),
            (project_root / "work", "/workspace/work", False),
            (project_root / "outputs", "/workspace/outputs", False),
        )
        command = [
            self.docker_binary,
            "run",
            "--rm",
            "--name",
            container_name,
            "--pull",
            "never",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            str(self.limits.pids),
            "--memory",
            self.limits.memory,
            "--cpus",
            str(self.limits.cpus),
            "--user",
            self.container_user,
            "--workdir",
            "/workspace/work",
            "--tmpfs",
            f"/tmp:rw,noexec,nosuid,nodev,size={self.limits.tmpfs_size}",
        ]
        for host_path, target, read_only in mounts:
            host_path.mkdir(parents=True, exist_ok=True)
            resolved_host_path = host_path.resolve()
            try:
                resolved_host_path.relative_to(project_root)
            except ValueError as error:
                raise ContainerExecutionError(
                    f"Container mount escapes the project workspace: {host_path.name}"
                ) from error
            source = str(resolved_host_path)
            if "," in source:
                raise ContainerExecutionError("Project paths containing commas are unsupported.")
            mount = f"type=bind,source={source},target={target}"
            if read_only:
                mount += ",readonly"
            command.extend(("--mount", mount))
        command.extend((self.image, *argv))
        return command

    def _cleanup(self, container_name: str) -> None:
        try:
            self._runner(
                [self.docker_binary, "rm", "-f", container_name],
                capture_output=True,
                text=False,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            pass

    def _bounded_text(self, value: bytes) -> tuple[str, bool]:
        truncated = len(value) > self.limits.max_output_bytes
        bounded = value[: self.limits.max_output_bytes]
        return bounded.decode("utf-8", errors="replace"), truncated


def container_doctor(
    *,
    enabled: bool,
    image: str | None,
    allowed_executables: Sequence[str],
    docker_binary: str = "docker",
    runner: Runner = subprocess.run,
) -> dict[str, bool | str | None]:
    """Return configuration and local Docker readiness without changing host state."""

    docker_path = shutil.which(docker_binary)
    digest_pinned = bool(image and PINNED_IMAGE_PATTERN.fullmatch(image))
    daemon_reachable = False
    image_available = False
    if docker_path is not None:
        try:
            daemon = runner(
                [docker_binary, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=False,
                timeout=10,
                check=False,
            )
            daemon_reachable = daemon.returncode == 0
            if daemon_reachable and digest_pinned:
                inspected = runner(
                    [docker_binary, "image", "inspect", image],
                    capture_output=True,
                    text=False,
                    timeout=10,
                    check=False,
                )
                image_available = inspected.returncode == 0
        except (OSError, subprocess.SubprocessError):
            pass

    configured = enabled and digest_pinned and bool(allowed_executables)
    return {
        "dockerCliPresent": docker_path is not None,
        "daemonReachable": daemon_reachable,
        "imageConfigured": bool(image),
        "imageDigestPinned": digest_pinned,
        "imageAvailableLocally": image_available,
        "allowlistConfigured": bool(allowed_executables),
        "executorEnabled": configured,
        "ready": configured and daemon_reachable and image_available,
        "image": image,
    }
