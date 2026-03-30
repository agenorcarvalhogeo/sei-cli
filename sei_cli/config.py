from __future__ import annotations

import json
import os
from pathlib import Path

from sei_cli.models import Credentials

CREDENTIALS_PATH = Path("~/.config/sei/credentials.json").expanduser()
SESSION_PATH = Path("~/.config/sei-cli/session.json").expanduser()
CREATED_PROCESSES_PATH = Path("~/.config/sei-cli/created_processes.json").expanduser()
CREATED_DOCUMENTS_PATH = Path("~/.config/sei-cli/created_documents.json").expanduser()

ORGAO_MAP: dict[str, str] = {
    "CBM": "28",
}


class ConfigError(RuntimeError):
    pass


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


_BW_ITEM_NAME = "SEI SISBOM RN CBMRN"
_DEFAULT_ORGAO = "CBM"
_DEFAULT_LOGIN_URL = "https://sei.rn.gov.br/sip/login.php?sigla_orgao_sistema=SEAD&sigla_sistema=SEI"


def _load_from_bitwarden() -> Credentials | None:
    """Try to read SEI credentials from Bitwarden vault.

    Requires BW_SESSION to be set (either as env var or in ~/.openclaw/.bw_session).
    Returns None if Bitwarden is unavailable or item not found.
    """
    import subprocess

    bw_session = os.getenv("BW_SESSION")
    if not bw_session:
        bw_session_file = Path("~/.openclaw/.bw_session").expanduser()
        if bw_session_file.exists():
            bw_session = bw_session_file.read_text().strip()

    if not bw_session:
        return None

    env = {**os.environ, "BW_SESSION": bw_session}
    try:
        result = subprocess.run(
            ["bw", "get", "item", _BW_ITEM_NAME],
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        if result.returncode != 0:
            return None

        item = json.loads(result.stdout)
        login = item.get("login", {})
        usuario = login.get("username", "")
        senha = login.get("password", "")

        if not usuario or not senha:
            return None

        return Credentials(
            usuario=usuario,
            senha=senha,
            orgao=_DEFAULT_ORGAO,
            login_url=_DEFAULT_LOGIN_URL,
        )
    except Exception:
        return None


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

    # Try Bitwarden first
    bw_creds = _load_from_bitwarden()
    if bw_creds is not None:
        return bw_creds

    # Fallback: local credentials file (backward compatibility)
    if not path.exists():
        raise ConfigError(
            f"Credenciais não encontradas em {path} e Bitwarden indisponível. "
            f"Configure o arquivo ou variáveis de ambiente SEI_*"
        )

    data = json.loads(path.read_text(encoding="utf-8"))
    try:
        return Credentials(
            usuario=str(data["usuario"]),
            senha=str(data["senha"]),
            orgao=str(data.get("orgao", _DEFAULT_ORGAO)),
            login_url=str(data.get("login_url", _DEFAULT_LOGIN_URL)),
            cargo=str(data.get("cargo", "")),
            id_usuario=str(data.get("id_usuario", "")),
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


def _load_json_list(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def _append_json_list(path: Path, item: dict) -> None:
    _ensure_parent(path)
    data = _load_json_list(path)
    data.append(item)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def append_created_process_log(item: dict, path: Path = CREATED_PROCESSES_PATH) -> None:
    _append_json_list(path, item)


def append_created_document_log(item: dict, path: Path = CREATED_DOCUMENTS_PATH) -> None:
    _append_json_list(path, item)


def load_created_processes(path: Path = CREATED_PROCESSES_PATH) -> list[dict]:
    return _load_json_list(path)


def load_created_documents(path: Path = CREATED_DOCUMENTS_PATH) -> list[dict]:
    return _load_json_list(path)
