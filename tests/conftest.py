from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def login_html() -> str:
    return (FIXTURES / "login_page.html").read_text(encoding="utf-8")


@pytest.fixture
def controle_html() -> str:
    return (FIXTURES / "controle_processos.html").read_text(encoding="utf-8")


@pytest.fixture
def recebidos_html() -> str:
    return (FIXTURES / "tblProcessosRecebidos.html").read_text(encoding="utf-8")


@pytest.fixture
def gerados_html() -> str:
    return (FIXTURES / "tblProcessosGerados.html").read_text(encoding="utf-8")
