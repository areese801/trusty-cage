"""
Network policy enforcement for trusty-cage containers.

Copies init-network.sh into the container and executes it as root
to apply iptables rules blocking SSH and Docker Hub.
"""

from rich import print as rprint

from trusty_cage.docker import container_exec, copy_to_container
from trusty_cage.image import get_asset_path


NETWORK_SCRIPT_CONTAINER_PATH = "/tmp/init-network.sh"


def apply_network_policy(container_name: str) -> None:
    """
    Apply network policy by copying and executing init-network.sh as root.
    Idempotent — safe to call on every attach.
    """
    script_path = get_asset_path("init-network.sh")

    # Copy script into container
    copy_to_container(script_path, container_name, NETWORK_SCRIPT_CONTAINER_PATH)

    # Execute as root
    rprint("[dim]Applying network policy...[/dim]")
    container_exec(
        container_name,
        ["bash", NETWORK_SCRIPT_CONTAINER_PATH],
        user="root",
    )
