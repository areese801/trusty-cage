"""
Tests for docker module.
"""

import subprocess

import pytest

from trusty_cage.docker import (
    DockerError,
    _run,
    container_exists,
    container_is_running,
    is_docker_running,
    volume_exists,
)


class TestRun:
    def test_success(self, mocker):
        mock = mocker.patch("trusty_cage.docker.subprocess.run")
        mock.return_value = subprocess.CompletedProcess(
            args=["docker", "info"], returncode=0, stdout="ok", stderr=""
        )
        result = _run(["info"])
        assert result.stdout == "ok"
        mock.assert_called_once_with(
            ["docker", "info"], check=True, capture_output=True, text=True
        )

    def test_failure_raises_docker_error(self, mocker):
        mocker.patch(
            "trusty_cage.docker.subprocess.run",
            side_effect=subprocess.CalledProcessError(
                1, ["docker", "fail"], output="", stderr="something went wrong"
            ),
        )
        with pytest.raises(DockerError, match="something went wrong"):
            _run(["fail"])


class TestIsDockerRunning:
    def test_running(self, mocker):
        mocker.patch(
            "trusty_cage.docker.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            ),
        )
        assert is_docker_running() is True

    def test_not_running(self, mocker):
        mocker.patch(
            "trusty_cage.docker.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, [], output="", stderr="err"),
        )
        assert is_docker_running() is False

    def test_docker_not_installed(self, mocker):
        mocker.patch(
            "trusty_cage.docker.subprocess.run",
            side_effect=FileNotFoundError(),
        )
        assert is_docker_running() is False


class TestContainerExists:
    def test_exists(self, mocker):
        mocker.patch(
            "trusty_cage.docker.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            ),
        )
        assert container_exists("mycontainer") is True

    def test_not_exists(self, mocker):
        mocker.patch(
            "trusty_cage.docker.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr=""
            ),
        )
        assert container_exists("mycontainer") is False


class TestContainerIsRunning:
    def test_running(self, mocker):
        mocker.patch(
            "trusty_cage.docker.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="true\n", stderr=""
            ),
        )
        assert container_is_running("mycontainer") is True

    def test_stopped(self, mocker):
        mocker.patch(
            "trusty_cage.docker.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="false\n", stderr=""
            ),
        )
        assert container_is_running("mycontainer") is False

    def test_not_exists(self, mocker):
        mocker.patch(
            "trusty_cage.docker.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr=""
            ),
        )
        assert container_is_running("mycontainer") is False


class TestVolumeExists:
    def test_exists(self, mocker):
        mocker.patch(
            "trusty_cage.docker.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            ),
        )
        assert volume_exists("myvol") is True

    def test_not_exists(self, mocker):
        mocker.patch(
            "trusty_cage.docker.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr=""
            ),
        )
        assert volume_exists("myvol") is False
