"""Parser for SEI Relatório de Serviço Operacional.

Extracts structured data from the HTML body of Livro Diário do Fiscal
documents: personnel (with DO/Ordinário/Extraordinário/Permuta status),
vehicles, armament, occurrences, guard/patrol schedules, and service notes.

The HTML uses consistent CSS classes and table structures across all
PABM Apodi relatórios. Section markers (A-I, 1ª-8ª PARTE) are always
in <p class="Texto_Justificado_Recuo_Primeira_Linha">.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import unescape
from typing import Any

from bs4 import BeautifulSoup, Tag


# --- Data models ---

@dataclass
class Militar:
    """A military member mentioned in the report."""
    nome: str
    posto: str  # rank: SD BM, 3º SGT BM, 2° SGT BM, 1° SGT BM, etc.
    funcao: str  # role: Fiscal, Chefe de Guarnição, Condutor, Operador, etc.
    viatura: str | None = None  # VTR assignment: ABT-02, AS-42, UR-28
    status: str = "ordinario"  # ordinario, extraordinario, permuta, do


@dataclass
class Viatura:
    """Vehicle status entry from section H."""
    tipo: str  # IVECO 170E28, MITSUBISHI TRITON, etc.
    placa: str
    prefixo: str  # ABT-02, AS-42, UR-28, ABTS-06
    hodometro: str
    situacao: str  # Operante, Inoperante, etc.


@dataclass
class Ocorrencia:
    """An incident/call from section 7ª PARTE."""
    boletim: str  # e.g. 00044088/2026
    codigo: str  # e.g. 1577
    natureza: str  # e.g. TREINAMENTO / INSTRUÇÃO


@dataclass
class Armamento:
    """Weapon/equipment entry from section G."""
    quantidade: int
    tipo: str
    modelo: str
    num_serie: str
    acessorio: str


@dataclass
class GuardaRonda:
    """Guard/patrol shift."""
    tipo: str  # "guarda" or "ronda"
    horario: str
    militar: str


@dataclass
class RelatorioServico:
    """Parsed Relatório de Serviço Operacional."""
    # Header
    fiscal: str = ""
    posto_fiscal: str = ""
    data_inicio: str = ""  # DD/MM/YYYY
    data_fim: str = ""
    unidade: str = ""  # e.g. PABM - Apodi RN / 3°GBM

    # Personnel
    militares: list[Militar] = field(default_factory=list)

    # Sections A-F (simple text)
    parada: str = ""
    rancho: str = ""
    agua: str = ""
    luz: str = ""
    revista: str = ""
    faxina: str = ""

    # Section G
    armamento: list[Armamento] = field(default_factory=list)

    # Section H
    viaturas: list[Viatura] = field(default_factory=list)

    # Section I (HTs/radios)
    hts: list[dict[str, str]] = field(default_factory=list)

    # Parts 2-6
    justica_disciplina: str = ""
    assuntos_gerais: list[str] = field(default_factory=list)
    ensino_instrucao: str = ""
    guarda_ronda: list[GuardaRonda] = field(default_factory=list)
    escala_faxina: list[dict[str, str]] = field(default_factory=list)

    # Part 7
    ocorrencias: list[Ocorrencia] = field(default_factory=list)

    # Part 8
    passagem_de: str = ""
    passagem_para: str = ""
    data_passagem: str = ""


def _norm(text: str) -> str:
    """Normalize whitespace and common HTML entities."""
    text = unescape(text)
    text = text.replace("\xa0", " ").replace("\u200b", "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _parse_rank_name(text: str) -> tuple[str, str]:
    """Split '2° SGT BM Vilson' into (rank, name).
    
    Handles: SD BM, CB BM, 3º SGT BM, 2° SGT BM, 1° SGT BM,
    ST BM, 2° TEN, 1° TEN, CAP, MAJ, TC, CEL
    """
    text = _norm(text)
    # Common rank patterns
    m = re.match(
        r"(SD\s+BM|CB\s+BM|[123][°º]?\s*SGT\s+(?:QP)?BM|ST\s+BM|"
        r"[12][°º]?\s*TEN\s*(?:QOEM)?(?:\s*BM)?|CAP(?:\s+BM)?|"
        r"MAJ(?:\s+BM)?|TC(?:\s+BM)?|CEL(?:\s+BM)?)\s+(.*)",
        text, re.IGNORECASE,
    )
    if m:
        return _norm(m.group(1)), _norm(m.group(2))
    return "", text


def _extract_tables_between(soup: BeautifulSoup, start_text: str, end_text: str) -> list[Tag]:
    """Find all <table> elements between two section markers."""
    tables = []
    in_section = False
    for el in soup.find_all(["p", "table"]):
        text = _norm(el.get_text())
        if start_text in text:
            in_section = True
            continue
        if end_text and end_text in text:
            break
        if in_section and el.name == "table":
            tables.append(el)
    return tables


def _text_between(soup: BeautifulSoup, start_text: str, end_text: str) -> str:
    """Get text content between two section markers."""
    parts = []
    in_section = False
    for el in soup.find_all(["p", "table"]):
        text = _norm(el.get_text())
        if start_text in text:
            in_section = True
            # Content might be after the marker in the same <p>
            after = text.split(start_text, 1)[1].strip()
            if after:
                parts.append(after)
            continue
        if end_text and end_text in text:
            break
        if in_section:
            t = _norm(el.get_text())
            if t:
                parts.append(t)
    return " ".join(parts).strip()


def _get_section_text(soup: BeautifulSoup, section_id: str, next_section: str) -> str:
    """Get simple text for sections like 'A. Parada:' through next section."""
    return _text_between(soup, f"{section_id}", next_section)


def _table_rows(table: Tag) -> list[list[str]]:
    """Extract table as list of rows, each row a list of cell texts."""
    rows = []
    for tr in table.find_all("tr"):
        cells = [_norm(td.get_text()) for td in tr.find_all(["td", "th"])]
        rows.append(cells)
    return rows


def parse_relatorio(html_content: str) -> RelatorioServico:
    """Parse a Relatório de Serviço Operacional HTML body into structured data.
    
    Args:
        html_content: The HTML content from the body textarea (txaEditor).
                     Can be HTML-escaped (from SEI editor) or raw HTML.
    
    Returns:
        RelatorioServico with all extracted fields.
    """
    # Unescape if needed (SEI textareas are HTML-escaped)
    if "&lt;" in html_content[:500]:
        html_content = unescape(html_content)

    soup = BeautifulSoup(html_content, "lxml")
    r = RelatorioServico()

    # --- Header ---
    _parse_header(soup, r)

    # --- 1ª PARTE: Escala ---
    _parse_escala(soup, r)

    # --- Sections A-F (simple text) ---
    r.parada = _get_section_text(soup, "A. Parada", "B. Rancho")
    r.rancho = _get_section_text(soup, "B. Rancho", "C. Água")
    r.agua = _get_section_text(soup, "C. Água", "D. Luz")
    r.luz = _get_section_text(soup, "D. Luz", "E. Revista")
    r.revista = _get_section_text(soup, "E. Revista", "F. Faxina")
    r.faxina = _get_section_text(soup, "F. Faxina", "G. Armamento")

    # --- Section G: Armamento ---
    _parse_armamento(soup, r)

    # --- Section H: Viaturas ---
    _parse_viaturas(soup, r)

    # --- Section I: HTs ---
    _parse_hts(soup, r)

    # --- 2ª PARTE ---
    r.justica_disciplina = _text_between(
        soup, "2ª PARTE", "3ª PARTE"
    ).replace("Justiça e Disciplina:", "").strip()

    # --- 3ª PARTE: Assuntos Gerais ---
    _parse_assuntos_gerais(soup, r)

    # --- 4ª PARTE ---
    r.ensino_instrucao = _text_between(
        soup, "4ª PARTE", "5ª PARTE"
    ).replace("Ensino e Instrução:", "").strip()

    # --- 5ª PARTE: Guarda e Ronda ---
    _parse_guarda_ronda(soup, r)

    # --- 6ª PARTE: Escala de Faxina ---
    _parse_escala_faxina(soup, r)

    # --- 7ª PARTE: Ocorrências ---
    _parse_ocorrencias(soup, r)

    # --- 8ª PARTE: Passagem ---
    _parse_passagem(soup, r)

    return r


def _parse_header(soup: BeautifulSoup, r: RelatorioServico) -> None:
    """Extract fiscal name, dates, and unit from the header paragraph."""
    for p in soup.find_all("p"):
        text = _norm(p.get_text())

        # Fiscal name: "2° SGT BM Vilson - Fiscal de Operações"
        m = re.search(r"(.+?)\s*-?\s*Fiscal de Opera", text)
        if m and not r.fiscal:
            raw = _norm(m.group(1))
            r.posto_fiscal, r.fiscal = _parse_rank_name(raw)

        # Date: "do dia DD para o dia DD de MÊS de AAAA"
        m = re.search(
            r"do dia (\d{1,2})\s+para\s+o dia (\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})",
            text,
        )
        if m and not r.data_inicio:
            dia1, dia2, mes_nome, ano = m.groups()
            mes_num = _mes_to_num(mes_nome)
            r.data_inicio = f"{int(dia1):02d}/{mes_num:02d}/{ano}"
            r.data_fim = f"{int(dia2):02d}/{mes_num:02d}/{ano}"

        # Unit: "Ao Comando do PABM - Apodi RN / 3°GBM"
        m = re.search(r"Ao Comando do (.+?),\s*relat", text)
        if m and not r.unidade:
            r.unidade = _norm(m.group(1))


def _mes_to_num(nome: str) -> int:
    """Convert Portuguese month name to number."""
    meses = {
        "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3,
        "abril": 4, "maio": 5, "junho": 6, "julho": 7,
        "agosto": 8, "setembro": 9, "outubro": 10,
        "novembro": 11, "dezembro": 12,
    }
    return meses.get(nome.lower(), 0)


def _parse_escala(soup: BeautifulSoup, r: RelatorioServico) -> None:
    """Parse 1ª PARTE tables to extract personnel with their status.
    
    Table layouts:
    - Oficial/Fiscal tables (4 cols): [Role, Ordinário, Extraordinário, Permuta]
    - VTR tables: Row 0 is header. Row 1 has 5+ cols: [VTR, Função, Ord, Ext, Perm].
      Subsequent rows have 4 cols: [Função, Ord, Ext, Perm].
    
    A filled cell (not XXXX/empty) means the person is in that status column.
    """
    tables = _extract_tables_between(soup, "1ª PARTE", "A. Parada")

    for table in tables:
        rows = _table_rows(table)
        if not rows:
            continue

        # Skip header row ("Serviço 24h", "Ordinário", ...)
        data_rows = [r for r in rows if r[0] != "Serviço 24h"]
        if not data_rows:
            continue

        first_row = data_rows[0]
        vtr_name = None
        role_type = None

        # Detect if this is a VTR table (first data row starts with VTR prefix)
        first_cell = first_row[0] if first_row else ""
        is_vtr_table = bool(
            re.match(r"(ABT|ABTS|AS|UR)\s*-?\s*\d+", first_cell, re.IGNORECASE)
        )

        if is_vtr_table:
            vtr_name = re.sub(r"\s+", "", first_cell).upper()
            # Replace hyphens: "ABT - 02" → "ABT-02"
            vtr_name = re.sub(r"(\w+)\s*-\s*(\d+)", r"\1-\2", first_cell.upper().strip())
        elif "Oficial" in first_cell:
            role_type = "Oficial de Operações"
        elif "Fiscal" in first_cell:
            role_type = "Fiscal de Operações"

        for row in data_rows:
            if len(row) < 2:
                continue

            # Determine column offsets based on row structure
            # VTR first row: [VTR, Função, Ord, Ext, Perm] → offset=2
            # VTR other rows: [Função, Ord, Ext, Perm] → offset=1
            # Simple tables: [Role, Ord, Ext, Perm] → offset=1
            first = row[0]
            if re.match(r"(ABT|ABTS|AS|UR)\s*-?\s*\d+", first, re.IGNORECASE):
                # This is the VTR header row — function in col 1, status cols 2-4
                funcao = row[1] if len(row) > 1 else ""
                status_cols = {2: "ordinario", 3: "extraordinario", 4: "permuta"}
            elif role_type:
                funcao = role_type
                status_cols = {1: "ordinario", 2: "extraordinario", 3: "permuta"}
            else:
                funcao = first
                status_cols = {1: "ordinario", 2: "extraordinario", 3: "permuta"}

            if not funcao or funcao == "Serviço 24h":
                continue

            for col_idx, status_name in status_cols.items():
                if col_idx >= len(row):
                    continue
                cell = _norm(row[col_idx])
                if cell and cell != "XXXX" and cell != "," and len(cell) > 2:
                    posto, nome = _parse_rank_name(cell)
                    if nome and nome != "XXXX":
                        mil = Militar(
                            nome=nome,
                            posto=posto,
                            funcao=funcao,
                            viatura=vtr_name,
                            status=status_name,
                        )
                        r.militares.append(mil)


def _parse_armamento(soup: BeautifulSoup, r: RelatorioServico) -> None:
    """Parse section G (Armamento) table."""
    tables = _extract_tables_between(soup, "G. Armamento", "H. Viatura")
    for table in tables:
        for row in _table_rows(table):
            if len(row) >= 5:
                try:
                    qtd = int(re.sub(r"\D", "", row[0]) or "0")
                except ValueError:
                    qtd = 0
                r.armamento.append(Armamento(
                    quantidade=qtd,
                    tipo=row[1],
                    modelo=row[2],
                    num_serie=row[3],
                    acessorio=row[4] if len(row) > 4 else "",
                ))


def _parse_viaturas(soup: BeautifulSoup, r: RelatorioServico) -> None:
    """Parse section H (Viaturas) table.
    
    Expected columns: Viatura | Placa | Prefixo | Hodômetro | Situação
    Some rows (BARCO, MOTOR, REBOQUE) may lack standard prefixes.
    """
    tables = _extract_tables_between(soup, "H. Viatura", "I. HT")
    if not tables:
        tables = _extract_tables_between(soup, "H. VTR", "I. HT")

    for table in tables:
        for row in _table_rows(table):
            if len(row) < 5:
                continue
            # Skip header rows
            if "Viatura" in row[0] and "Placa" in row[1]:
                continue
            # Skip observation/footnote rows
            if row[0].startswith("Obs") or row[0].startswith("*"):
                continue
            prefixo = re.sub(r"\s+", "", row[2])
            # Normalize prefixo: "ABT - 02" → "ABT-02"
            prefixo = re.sub(r"(\w+)\s*-\s*(\d+)", r"\1-\2", row[2].strip())
            r.viaturas.append(Viatura(
                tipo=row[0],
                placa=row[1],
                prefixo=prefixo or row[0][:20],  # fallback to tipo for boats etc
                hodometro=row[3],
                situacao=row[4],
            ))


def _parse_hts(soup: BeautifulSoup, r: RelatorioServico) -> None:
    """Parse section I (HTs/radios) table."""
    tables = _extract_tables_between(soup, "I. HT", "2ª PARTE")
    # Some reports might use "J. Equipamentos" instead of going to 2ª PARTE
    if not tables:
        tables = _extract_tables_between(soup, "I. HT", "J. Equipamento")

    for table in tables:
        for row in _table_rows(table):
            if len(row) >= 3:
                if "Modelo" in row[0] and "Tombamento" in row[1]:
                    continue
                r.hts.append({
                    "modelo": row[0],
                    "tombamento": row[1],
                    "viatura": row[2],
                })


def _parse_assuntos_gerais(soup: BeautifulSoup, r: RelatorioServico) -> None:
    """Parse 3ª PARTE (Assuntos Gerais) — numbered items."""
    text = _text_between(soup, "3ª PARTE", "Conferência")
    if not text:
        text = _text_between(soup, "3ª PARTE", "4ª PARTE")
    text = text.replace("Assuntos Gerais e Administrativos.", "").strip()

    # Split by numbered items (1. xxx 2. xxx)
    items = re.split(r"(?:^|\s)(\d+\.)\s+", text)
    current = ""
    for part in items:
        if re.match(r"\d+\.", part):
            if current.strip():
                r.assuntos_gerais.append(current.strip())
            current = ""
        else:
            current += " " + part
    if current.strip():
        r.assuntos_gerais.append(current.strip())


def _parse_guarda_ronda(soup: BeautifulSoup, r: RelatorioServico) -> None:
    """Parse 5ª PARTE (Guarda e Ronda) tables."""
    tables = _extract_tables_between(soup, "5ª PARTE", "6ª PARTE")

    for i, table in enumerate(tables):
        tipo = "guarda" if i == 0 else "ronda"
        for row in _table_rows(table):
            if len(row) >= 2:
                horario = row[0]
                militar = row[1] if len(row) > 1 else ""
                if "HORÁRIO" in horario.upper() or "MILITAR" in horario.upper():
                    continue
                if horario and militar:
                    r.guarda_ronda.append(GuardaRonda(
                        tipo=tipo,
                        horario=horario,
                        militar=_norm(militar),
                    ))


def _parse_escala_faxina(soup: BeautifulSoup, r: RelatorioServico) -> None:
    """Parse 6ª PARTE (Escala de Faxina) table."""
    tables = _extract_tables_between(soup, "6ª PARTE", "7ª PARTE")
    for table in tables:
        for row in _table_rows(table):
            if len(row) >= 2:
                local = row[0]
                militar = row[1]
                if "LOCAL" in local.upper() or "MILITAR" in local.upper():
                    continue
                if local and militar:
                    r.escala_faxina.append({
                        "local": local,
                        "militar": militar,
                    })


def _parse_ocorrencias(soup: BeautifulSoup, r: RelatorioServico) -> None:
    """Parse 7ª PARTE (Ocorrências) table."""
    tables = _extract_tables_between(soup, "7ª PARTE", "8ª PARTE")
    for table in tables:
        for row in _table_rows(table):
            if len(row) >= 3:
                boletim = row[0]
                # Skip header
                if "Boletim" in boletim or "Código" in boletim:
                    continue
                r.ocorrencias.append(Ocorrencia(
                    boletim=boletim,
                    codigo=row[1],
                    natureza=row[2],
                ))


def _parse_passagem(soup: BeautifulSoup, r: RelatorioServico) -> None:
    """Parse 8ª PARTE (Passagem de serviço)."""
    text = _text_between(soup, "8ª PARTE", "")
    text = text.replace("Passagem de serviço:", "").strip()

    # "Passei o serviço ... ao meu substituto legal, o 1° SGT BM Leandro"
    m = re.search(
        r"substituto\s+legal\s*,?\s*o\s+(.+?)(?:,\s*com|\.)",
        text, re.IGNORECASE,
    )
    if m:
        r.passagem_para = _norm(m.group(1))

    # Extract date: "DD de MÊS de AAAA"
    m = re.search(r"(\d{1,2})\s+de\s+(\w+)\s+de\s+(\d{4})", text)
    if m:
        dia, mes, ano = m.groups()
        mes_num = _mes_to_num(mes)
        r.data_passagem = f"{int(dia):02d}/{mes_num:02d}/{ano}"

    # Fiscal who passed: from the signature line
    # "Antonio Vilson de Souza - 2° SGT QPBM"
    m = re.search(r"([A-ZÀ-Ú][a-zà-ú]+(?:\s+[A-ZÀ-Ú][a-zà-ú]+)*)\s*-\s*(\d°?\s*SGT|SD|CB|ST|TEN|CAP)", text)
    if m:
        r.passagem_de = _norm(m.group(0).split("-")[0])


def to_dict(r: RelatorioServico) -> dict[str, Any]:
    """Convert RelatorioServico to a JSON-serializable dict."""
    from dataclasses import asdict
    return asdict(r)


def summarize(r: RelatorioServico) -> str:
    """Generate a human-readable summary of the report."""
    lines = []
    lines.append(f"📋 Relatório: {r.data_inicio} → {r.data_fim}")
    lines.append(f"👮 Fiscal: {r.posto_fiscal} {r.fiscal}")
    lines.append(f"📍 Unidade: {r.unidade}")

    # Personnel summary
    ord_count = sum(1 for m in r.militares if m.status == "ordinario")
    ext_count = sum(1 for m in r.militares if m.status == "extraordinario")
    perm_count = sum(1 for m in r.militares if m.status == "permuta")
    lines.append(f"👥 Efetivo: {len(r.militares)} total ({ord_count} ord, {ext_count} ext, {perm_count} perm)")

    # VTR by prefix
    vtrs_by_prefix = {}
    for m in r.militares:
        if m.viatura:
            vtrs_by_prefix.setdefault(m.viatura, []).append(m)
    for vtr, mils in vtrs_by_prefix.items():
        names = ", ".join(f"{m.posto} {m.nome}" for m in mils)
        lines.append(f"  🚒 {vtr}: {names}")

    # Vehicles status
    if r.viaturas:
        lines.append("🚗 Viaturas:")
        for v in r.viaturas:
            sit_lower = v.situacao.lower()
            if "inoperante" in sit_lower:
                emoji = "❌"
            elif "operante" in sit_lower:
                emoji = "✅"
            else:
                emoji = "⚠️"
            lines.append(f"  {emoji} {v.prefixo} ({v.placa}): {v.situacao}")

    # Occurrences
    if r.ocorrencias:
        lines.append(f"🚨 Ocorrências: {len(r.ocorrencias)}")
        for o in r.ocorrencias:
            lines.append(f"  • {o.boletim} — {o.natureza}")

    # General notes
    if r.assuntos_gerais:
        lines.append("📝 Notas:")
        for note in r.assuntos_gerais:
            lines.append(f"  • {note[:100]}")

    # Passagem
    if r.passagem_para:
        lines.append(f"🔄 Passagem para: {r.passagem_para}")

    return "\n".join(lines)
