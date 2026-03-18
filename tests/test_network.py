"""
Tests for network module.
"""

from trusty_cage.network import NETWORK_SCRIPT_CONTAINER_PATH, apply_network_policy


class TestApplyNetworkPolicy:
    def test_copies_script_and_executes(self, mocker):
        mock_cp = mocker.patch("trusty_cage.network.copy_to_container")
        mock_exec = mocker.patch("trusty_cage.network.container_exec")
        mocker.patch(
            "trusty_cage.network.get_asset_path",
            return_value="/fake/init-network.sh",
        )

        apply_network_policy("test-container")

        mock_cp.assert_called_once_with(
            "/fake/init-network.sh",
            "test-container",
            NETWORK_SCRIPT_CONTAINER_PATH,
        )
        mock_exec.assert_called_once_with(
            "test-container",
            ["bash", NETWORK_SCRIPT_CONTAINER_PATH],
            user="root",
        )

    def test_executes_as_root(self, mocker):
        mocker.patch("trusty_cage.network.copy_to_container")
        mock_exec = mocker.patch("trusty_cage.network.container_exec")
        mocker.patch(
            "trusty_cage.network.get_asset_path",
            return_value="/fake/init-network.sh",
        )

        apply_network_policy("my-container")

        assert mock_exec.call_args[1]["user"] == "root"
