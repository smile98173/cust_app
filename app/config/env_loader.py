from __future__ import annotations

import os
from pathlib import Path


def load_app_environment(base_dir: Path) -> Path:
    """Load the project defaults, then the explicitly selected environment."""
    try:
        from dotenv import dotenv_values, load_dotenv
    except ImportError:
        return base_dir / ".env"

    default_env_path = base_dir / ".env"
    load_dotenv(default_env_path, override=False)

    configured_path = os.getenv("CUST_APP_ENV_FILE", "").strip()
    if not configured_path:
        return default_env_path

    env_path = Path(configured_path)
    if not env_path.is_absolute():
        env_path = base_dir / env_path
    env_path = env_path.resolve()
    if not env_path.is_file():
        raise RuntimeError(f"CUST_APP_ENV_FILE does not exist: {env_path}")

    for key, value in dotenv_values(env_path).items():
        if value is not None:
            os.environ[key] = value

    return env_path
