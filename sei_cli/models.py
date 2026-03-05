from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Credentials:
    usuario: str
    senha: str
    orgao: str
    login_url: str


@dataclass(slots=True)
class SessionData:
    base_url: str
    last_url: str | None = None
    cookies: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class LoginForm:
    action: str


@dataclass(slots=True)
class LoginStatus:
    success: bool
    message: str
    current_url: str | None = None


@dataclass(slots=True)
class Process:
    numero: str
    tipo: str
    especificacao: str
    id_procedimento: str | None
    link: str
    novo: bool
    atribuido: str | None = None
    marcador: str | None = None
    caixa: str = "recebidos"


@dataclass(slots=True)
class ProcessList:
    recebidos: list[Process] = field(default_factory=list)
    gerados: list[Process] = field(default_factory=list)


@dataclass(slots=True)
class SystemStatus:
    valid: bool
    unidade_sigla: str | None = None
    unidade_descricao: str | None = None
    usuario: str | None = None
    ultimo_acesso: str | None = None


@dataclass(slots=True)
class Unit:
    sigla: str
    descricao: str
    link: str | None = None


@dataclass(slots=True)
class Document:
    numero: str
    nome: str
    link: str


@dataclass(slots=True)
class Block:
    id: str
    tipo: str
    descricao: str
    estado: str | None = None
    link: str | None = None


@dataclass(slots=True)
class ProcessDetails:
    processo_numero: str
    processo_link: str
    documentos: list[Document] = field(default_factory=list)


@dataclass(slots=True)
class SearchResult:
    query: str
    processos: list[Process] = field(default_factory=list)


@dataclass(slots=True)
class BlockDetails:
    block_id: str
    documentos: list[Document] = field(default_factory=list)


def as_json(data: Any) -> Any:
    if hasattr(data, "__dataclass_fields__"):
        return asdict(data)
    if isinstance(data, list):
        return [as_json(item) for item in data]
    return data
