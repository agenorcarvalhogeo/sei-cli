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
    tipo: str  # "interno", "externo", "processo"
    id_documento: str | None = None
    link: str | None = None
    assinado: bool = False


@dataclass(slots=True)
class BlockDocument:
    seq: str
    processo: str
    documento_id: str
    tipo_documento: str
    assinante: str
    assinado: bool = False
    link_processo: str | None = None
    link_documento: str | None = None


@dataclass(slots=True)
class Block:
    numero: str
    estado: str
    unidade_origem: str
    unidade_destino: str
    descricao: str
    link: str | None = None
    documentos: list[BlockDocument] = field(default_factory=list)


@dataclass(slots=True)
class ProcessDetails:
    processo_numero: str
    processo_link: str
    documentos: list[Document] = field(default_factory=list)


def as_json(data: Any) -> Any:
    if hasattr(data, "__dataclass_fields__"):
        return asdict(data)
    if isinstance(data, list):
        return [as_json(item) for item in data]
    return data
