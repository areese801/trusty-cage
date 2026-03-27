"""
Thin wrappers around the docker CLI via subprocess.
"""

import os
import subprocess
from typing import Any


class DockerError(Exception):
    """
    Raised when a docker command fails.
    """

    def __init__(self, message: str, returncode: int = 1):
        super().__init__(message)
        self.returncode = returncode


def _run(
    args: list[str],
    check: bool = True,
    capture: bool = True,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """
    Run a docker CLI command.
    """
    cmd = ["docker"] + args
    try:
        return subprocess.run(
            cmd,
            check=check,
            capture_output=capture,
            text=True,
            **kwargs,
        )
    except subprocess.CalledProcessError as e:
        raise DockerError(
            f"docker {' '.join(args)} failed (exit {e.returncode}): {(e.stderr or '').strip()}",
            returncode=e.returncode,
        ) from e


# --- Docker daemon ---


def is_docker_running() -> bool:
    """
    Check if Docker daemon is reachable.
    """
    try:
        _run(["info"], check=True)
        return True
    except (DockerError, FileNotFoundError):
        return False


# --- Containers ---


def container_exists(name: str) -> bool:
    """
    Check if a container with the given name exists (any state).
    """
    result = _run(["container", "inspect", name], check=False)
    return result.returncode == 0


def container_is_running(name: str) -> bool:
    """
    Check if a container is currently running.
    """
    result = _run(
        ["container", "inspect", "-f", "{{.State.Running}}", name],
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def container_start(name: str) -> None:
    """
    Start a stopped container.
    """
    _run(["start", name])


def container_stop(name: str) -> None:
    """
    Stop a running container.
    """
    _run(["stop", name])


def container_remove(name: str, force: bool = False) -> None:
    """
    Remove a container.
    """
    args = ["rm"]
    if force:
        args.append("-f")
    args.append(name)
    _run(args)


def container_create(
    name: str,
    image: str,
    volume_mount: str | None = None,
    hostname: str | None = None,
    cap_add: list[str] | None = None,
) -> None:
    """
    Create (but don't start) a container.
    """
    args = ["create", "--name", name]
    if volume_mount:
        args.extend(["-v", volume_mount])
    if hostname:
        args.extend(["--hostname", hostname])
    if cap_add:
        for cap in cap_add:
            args.extend(["--cap-add", cap])
    args.append(image)
    _run(args)


def container_exec(
    name: str,
    command: list[str],
    user: str | None = None,
    env: dict[str, str] | None = None,
    capture: bool = True,
    interactive: bool = False,
    check: bool = True,
    input: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """
    Execute a command inside a running container.
    """
    args = ["exec"]
    if interactive:
        args.extend(["-it"])
    elif input is not None:
        args.append("-i")
    if user:
        args.extend(["-u", user])
    if env:
        for k, v in env.items():
            args.extend(["-e", f"{k}={v}"])
    args.append(name)
    args.extend(command)
    return _run(args, capture=capture, check=check, input=input)


def exec_replace(
    name: str,
    command: list[str],
    env: dict[str, str] | None = None,
) -> None:
    """
    Replace the current process with docker exec (for terminal handoff).
    Uses os.execvp — does not return.
    """
    args = ["docker", "exec", "-it"]
    if env:
        for k, v in env.items():
            args.extend(["-e", f"{k}={v}"])
    args.append(name)
    args.extend(command)
    os.execvp("docker", args)


# --- Volumes ---


def volume_exists(name: str) -> bool:
    """
    Check if a named volume exists.
    """
    result = _run(["volume", "inspect", name], check=False)
    return result.returncode == 0


def volume_create(name: str) -> None:
    """
    Create a named volume.
    """
    _run(["volume", "create", name])


def volume_remove(name: str) -> None:
    """
    Remove a named volume.
    """
    _run(["volume", "rm", name])


# --- Copy ---


def copy_to_container(src: str, container: str, dest: str) -> None:
    """
    Copy files from host to container via docker cp.
    """
    _run(["cp", src, f"{container}:{dest}"])


def copy_from_container(container: str, src: str, dest: str) -> None:
    """
    Copy files from container to host via docker cp.
    """
    _run(["cp", f"{container}:{src}", dest])


# --- Image ---


def build_image(
    tag: str,
    dockerfile_path: str,
    context_dir: str,
    build_args: dict[str, str] | None = None,
) -> None:
    """
    Build a Docker image.
    """
    args = ["build", "-t", tag, "-f", dockerfile_path]
    if build_args:
        for k, v in build_args.items():
            args.extend(["--build-arg", f"{k}={v}"])
    args.append(context_dir)
    _run(args, capture=False)


def image_exists(tag: str) -> bool:
    """
    Check if a Docker image exists locally.
    """
    result = _run(["image", "inspect", tag], check=False)
    return result.returncode == 0
