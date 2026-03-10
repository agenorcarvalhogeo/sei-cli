from __future__ import annotations

import json
import os
from pathlib import Path

from sei_cli.models import Credentials

CREDENTIALS_PATH = Path("~/.config/sei/credentials.json").expanduser()
SESSION_PATH = Path("~/.config/sei-cli/session.json").expanduser()

ORGAO_MAP: dict[str, str] = {
    "CBM": "28",
}


class ConfigError(RuntimeError):
    pass


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_credentials(path: Path = CREDENTIALS_PATH) -> Credentials:
    env_usuario = os.getenv("SEI_USUARIO")
    env_senha = os.getenv("SEI_SENHA")
    env_orgao = os.getenv("SEI_ORGAO")
    env_login_url = os.getenv("SEI_LOGIN_URL")

    if env_usuario and env_senha and env_orgao and env_login_url:
        return Credentials(
            usuario=env_usuario,
            senha=env_senha,
            orgao=env_orgao,
            login_url=env_login_url,
        )

    if not path.exists():
        raise ConfigError(
            f"Credenciais não encontradas em {path}. Configure o arquivo ou variáveis de ambiente SEI_*"
        )

    data = json.loads(path.read_text(encoding="utf-8"))
    try:
        return Credentials(
            usuario=str(data["usuario"]),
            senha=str(data["senha"]),
            orgao=str(data["orgao"]),
            login_url=str(data["login_url"]),
        )
    except KeyError as exc:
        raise ConfigError(f"Campo obrigatório ausente no arquivo de credenciais: {exc}") from exc


def orgao_to_value(orgao: str) -> str:
    return ORGAO_MAP.get(orgao.upper(), orgao)


def save_session(
    cookie: str,
    unit_id: str | None = None,
    path: Path = SESSION_PATH,
) -> None:
    """Persist PHPSESSID + optional unit to disk (chmod 600)."""
    _ensure_parent(path)
    import time

    payload = {"phpsessid": cookie, "unit_id": unit_id, "saved_at": time.time()}
    path.write_text(json.dumps(payload), encoding="utf-8")
    path.chmod(0o600)


def load_session(path: Path = SESSION_PATH) -> dict | None:
    """Load saved session. Returns {"phpsessid": str, "unit_id": str|None, "saved_at": float} or None."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if "phpsessid" not in data:
            return None
        return data
    except (json.JSONDecodeError, OSError):
        return None


def clear_session(path: Path = SESSION_PATH) -> None:
    if path.exists():
        path.unlink()
