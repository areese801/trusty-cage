"""
Environment metadata management.

Each environment is stored under ~/.trusty-cage/envs/<name>/ with a meta.json
file as the single source of truth.
"""

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from trusty_cage import constants


@dataclass
class AdditionalDir:
    """
    Metadata for an additional directory shipped into a cage.
    """

    name: str
    host_source_path: str
    host_clone_path: str
    volume_name: str
    container_path: str
    added_at: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AdditionalDir":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class MetaJson:
    """
    Source of truth for a single environment.
    """

    name: str
    repo_url: str
    created_at: str
    volume_name: str
    container_name: str
    host_clone_path: str
    auth_mode: str
    api_key_env: str = "ANTHROPIC_API_KEY"
    additional_dirs: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "MetaJson":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def get_additional_dir(self, name: str) -> AdditionalDir | None:
        """
        Look up an additional dir by name. Returns None if not found.
        """
        for d in self.additional_dirs:
            if d.get("name") == name:
                return AdditionalDir.from_dict(d)
        return None


def derive_name(url: str) -> str:
    """
    Derive an environment name from a git repo URL.

    Extracts the repo name from the URL path, stripping .git suffix.
    """
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    name = path.rsplit("/", 1)[-1]
    # Sanitize: lowercase, keep only alphanumeric, hyphens, underscores
    name = re.sub(r"[^a-zA-Z0-9_-]", "-", name)
    return name.lower()


def derive_name_from_path(dir_path: str) -> str:
    """
    Derive an environment name from a local directory path.

    Uses the directory basename, sanitized the same way as derive_name.
    """
    name = Path(dir_path).resolve().name
    name = re.sub(r"[^a-zA-Z0-9_-]", "-", name)
    return name.lower()


def get_env_dir(name: str) -> Path:
    """
    Get the directory for a named environment.
    """
    return constants.ENVS_DIR / name


def env_exists(name: str) -> bool:
    """
    Check if an environment with this name already exists (has meta.json).
    """
    meta_path = get_env_dir(name) / "meta.json"
    return meta_path.is_file()


def create_meta(
    name: str,
    repo_url: str,
    auth_mode: str,
    api_key_env: str = "ANTHROPIC_API_KEY",
) -> MetaJson:
    """
    Create and persist a new MetaJson for an environment.
    """
    env_dir = get_env_dir(name)
    env_dir.mkdir(parents=True, exist_ok=True)

    meta = MetaJson(
        name=name,
        repo_url=repo_url,
        created_at=datetime.now(timezone.utc).isoformat(),
        volume_name=f"{constants.VOLUME_PREFIX}{name}",
        container_name=f"{constants.CONTAINER_PREFIX}{name}",
        host_clone_path=str(env_dir / "repo"),
        auth_mode=auth_mode,
        api_key_env=api_key_env,
    )

    meta_path = env_dir / "meta.json"
    meta_path.write_text(json.dumps(meta.to_dict(), indent=2))
    return meta


def save_meta(meta: MetaJson) -> None:
    """
    Persist an updated MetaJson to disk.
    """
    meta_path = get_env_dir(meta.name) / "meta.json"
    meta_path.write_text(json.dumps(meta.to_dict(), indent=2))


def load_meta(name: str) -> MetaJson:
    """
    Load MetaJson from disk. Raises FileNotFoundError if missing.
    """
    meta_path = get_env_dir(name) / "meta.json"
    data = json.loads(meta_path.read_text())
    return MetaJson.from_dict(data)


def list_envs() -> list[MetaJson]:
    """
    List all environments that have a valid meta.json.
    """
    envs = []
    if not constants.ENVS_DIR.is_dir():
        return envs
    for entry in sorted(constants.ENVS_DIR.iterdir()):
        meta_path = entry / "meta.json"
        if meta_path.is_file():
            try:
                envs.append(MetaJson.from_dict(json.loads(meta_path.read_text())))
            except (json.JSONDecodeError, TypeError):
                continue
    return envs
