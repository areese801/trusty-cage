"""
Tests for docker module.
"""

import subprocess

import pytest

from trusty_cage.docker import (
    DockerError,
    _run,
    container_create,
    container_exists,
    container_is_running,
    container_recreate,
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


class TestContainerCreate:
    def test_multiple_volume_mounts(self, mocker):
        mock_run = mocker.patch("trusty_cage.docker._run")
        container_create(
            name="test-container",
            image="trusty-cage:latest",
            volume_mounts=[
                "vol-main:/home/trustycage/project",
                "vol-lib:/home/trustycage/shared-lib",
            ],
            hostname="test",
            cap_add=["NET_ADMIN"],
        )
        args = mock_run.call_args[0][0]
        assert args.count("-v") == 2
        assert "vol-main:/home/trustycage/project" in args
        assert "vol-lib:/home/trustycage/shared-lib" in args

    def test_no_volume_mounts(self, mocker):
        mock_run = mocker.patch("trusty_cage.docker._run")
        container_create(
            name="test-container",
            image="trusty-cage:latest",
        )
        args = mock_run.call_args[0][0]
        assert "-v" not in args


class TestContainerRecreate:
    def test_recreate_stops_removes_creates_starts(self, mocker):
        mock_stop = mocker.patch("trusty_cage.docker.container_stop")
        mock_remove = mocker.patch("trusty_cage.docker.container_remove")
        mock_create = mocker.patch("trusty_cage.docker.container_create")
        mock_start = mocker.patch("trusty_cage.docker.container_start")
        mocker.patch("trusty_cage.docker.container_is_running", return_value=True)

        container_recreate(
            name="isolated-dev-test",
            image="trusty-cage:latest",
            volume_mounts=["vol1:/path1", "vol2:/path2"],
            hostname="test",
            cap_add=["NET_ADMIN"],
        )

        mock_stop.assert_called_once_with("isolated-dev-test")
        mock_remove.assert_called_once_with("isolated-dev-test")
        mock_create.assert_called_once_with(
            name="isolated-dev-test",
            image="trusty-cage:latest",
            volume_mounts=["vol1:/path1", "vol2:/path2"],
            hostname="test",
            cap_add=["NET_ADMIN"],
        )
        mock_start.assert_called_once_with("isolated-dev-test")

    def test_recreate_skips_stop_when_not_running(self, mocker):
        mock_stop = mocker.patch("trusty_cage.docker.container_stop")
        mocker.patch("trusty_cage.docker.container_remove")
        mocker.patch("trusty_cage.docker.container_create")
        mocker.patch("trusty_cage.docker.container_start")
        mocker.patch("trusty_cage.docker.container_is_running", return_value=False)

        container_recreate(
            name="isolated-dev-test",
            image="trusty-cage:latest",
            volume_mounts=["vol1:/path1"],
            hostname="test",
        )

        mock_stop.assert_not_called()


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
