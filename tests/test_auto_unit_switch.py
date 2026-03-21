"""Tests for automatic unit switching when accessing restricted processes."""

import re
from unittest.mock import MagicMock, patch, call
import pytest
from sei_cli.client import SEIClient


# --- Fixtures: realistic HTML snippets ---

ARVORE_RESTRICTED = '''
<script>
Nos[0] = new infraArvoreNo("PROCESSO","48568435",null,"controlador.php?acao=arvore_visualizar&id_procedimento=48568435","ifrVisualizacao","08810254.000108/2026-71","Pessoal","svg/processo.svg?18","svg/processo.svg?18","svg/processo.svg?18",true,true,"noVisitado",null,"noVisitado","08810254.000108/2026-71");
Nos[0].html = 'Processo aberto somente na unidade <a alt="COMANDO DO POSTO AVANÇADO" title="COMANDO DO POSTO AVANÇADO" class="ancoraSigla">CBM - COBM - CMDO PABM APODI</a>.<br />';
Nos[1] = new infraArvoreNo("DOCUMENTO","48568466","48568435","about:blank","ifrConteudoVisualizacao","Memorando 5 (40182408)","Memorando 5","svg/documento_interno.svg?18","svg/documento_interno.svg?18","svg/documento_interno.svg?18",true,false,null,null,"noVisitado","40182408");
Nos[2] = new infraArvoreNo("DOCUMENTO","48568542","48568435","about:blank","ifrConteudoVisualizacao","Memorando 6 (40182482)","Memorando 6","svg/documento_interno.svg?18","svg/documento_interno.svg?18","svg/documento_interno.svg?18",true,false,null,null,"noVisitado","40182482");
NosAcoes[0] = new infraArvoreAcao("BASE_CONHECIMENTO","BC","48568435","#","ifrVisualizacao","Base","svg/bc.svg?18",true);
NosAcoes[1] = new infraArvoreAcao("UNIDADE_GERADORA","UG48568466","48568466","#",null,"COMANDO DO POSTO AVANÇADO BOMBEIRO MILITAR DE APODI / RN",null,true,"CBM - COBM - CMDO PABM APODI");
NosAcoes[2] = new infraArvoreAcao("UNIDADE_GERADORA","UG48568542","48568542","#",null,"COMANDO DO POSTO AVANÇADO BOMBEIRO MILITAR DE APODI / RN",null,true,"CBM - COBM - CMDO PABM APODI");
</script>
'''

ARVORE_UNRESTRICTED = '''
<script>
Nos[0] = new infraArvoreNo("PROCESSO","48568435",null,"controlador.php?acao=arvore_visualizar&id_procedimento=48568435","ifrVisualizacao","08810254.000108/2026-71","Pessoal","svg/processo.svg?18","svg/processo.svg?18","svg/processo.svg?18",true,true,"noVisitado",null,"noVisitado","08810254.000108/2026-71");
Nos[1] = new infraArvoreNo("DOCUMENTO","48568466","48568435","controlador.php?acao=arvore_visualizar&id_documento=48568466","ifrConteudoVisualizacao","Memorando 5 (40182408)","Memorando 5","svg/documento_interno.svg?18","svg/documento_interno.svg?18","svg/documento_interno.svg?18",true,false,null,null,"noVisitado","40182408");
NosAcoes[0] = new infraArvoreAcao("GERAR_PDF","GP","48568435","controlador.php?acao=procedimento_gerar_pdf&id_procedimento=48568435&arvore=1&infra_hash=abc123","ifrVisualizacao","Gerar PDF","svg/pdf.svg?18",true);
</script>
'''

ARVORE_MULTI_UNIT = '''
<script>
Nos[0] = new infraArvoreNo("PROCESSO","99999",null,"controlador.php?acao=arvore_visualizar","ifrVisualizacao","proc","tipo","svg","svg","svg",true,true,null,null,null,"proc");
Nos[0].html = 'Processo aberto somente na unidade <a class="ancoraSigla">CBM - DAT - 1º CAT (MOSSORÓ)</a>.<br />';
Nos[1] = new infraArvoreNo("DOCUMENTO","111","99999","about:blank","ifrConteudoVisualizacao","Doc1","Doc1","svg","svg","svg",true,false,null,null,null,"111");
Nos[2] = new infraArvoreNo("DOCUMENTO","222","99999","about:blank","ifrConteudoVisualizacao","Doc2","Doc2","svg","svg","svg",true,false,null,null,null,"222");
NosAcoes[0] = new infraArvoreAcao("UNIDADE_GERADORA","UG111","111","#",null,"1º CAT MOSSORÓ",null,true,"CBM - DAT - 1º CAT (MOSSORÓ)");
NosAcoes[1] = new infraArvoreAcao("UNIDADE_GERADORA","UG222","222","#",null,"PABM APODI",null,true,"CBM - COBM - CMDO PABM APODI");
</script>
'''


class TestDetectUnitRestriction:
    def setup_method(self):
        self.client = SEIClient.__new__(SEIClient)

    def test_detects_restricted_process(self):
        result = self.client._detect_unit_restriction(ARVORE_RESTRICTED)
        assert result == "CBM - COBM - CMDO PABM APODI"

    def test_no_restriction_on_accessible_process(self):
        result = self.client._detect_unit_restriction(ARVORE_UNRESTRICTED)
        assert result is None

    def test_detects_from_multi_unit_process(self):
        result = self.client._detect_unit_restriction(ARVORE_MULTI_UNIT)
        assert result == "CBM - DAT - 1º CAT (MOSSORÓ)"


class TestDetectDocumentUnits:
    def setup_method(self):
        self.client = SEIClient.__new__(SEIClient)

    def test_maps_docs_to_units(self):
        result = self.client._detect_document_units(ARVORE_RESTRICTED)
        assert result == {
            "48568466": "CBM - COBM - CMDO PABM APODI",
            "48568542": "CBM - COBM - CMDO PABM APODI",
        }

    def test_multi_unit_docs(self):
        result = self.client._detect_document_units(ARVORE_MULTI_UNIT)
        assert result == {
            "111": "CBM - DAT - 1º CAT (MOSSORÓ)",
            "222": "CBM - COBM - CMDO PABM APODI",
        }

    def test_no_ug_on_unrestricted(self):
        result = self.client._detect_document_units(ARVORE_UNRESTRICTED)
        assert result == {}


class TestAutoUnitSwitch:
    def setup_method(self):
        self.client = SEIClient.__new__(SEIClient)

    @patch.object(SEIClient, 'status')
    def test_no_switch_when_unrestricted(self, mock_status):
        """Should yield None without calling switch_unit."""
        with self.client._auto_unit_switch(ARVORE_UNRESTRICTED) as switched:
            assert switched is None
        mock_status.assert_not_called()

    @patch.object(SEIClient, 'switch_unit')
    @patch.object(SEIClient, 'list_units')
    @patch.object(SEIClient, 'status')
    def test_switches_and_restores(self, mock_status, mock_units, mock_switch):
        """Should switch to required unit and restore original after."""
        from sei_cli.models import SystemStatus, Unit
        mock_status.return_value = SystemStatus(
            valid=True,
            unidade_sigla="CBM - DAT - SEC  - 1°SAT/1°CAT",
            unidade_descricao="SECRETARIA 1° SAT",
            usuario="TEST",
            ultimo_acesso="",
        )
        mock_units.return_value = [
            Unit(sigla="CBM - COBM - CMDO PABM APODI", descricao="PABM", link="110008367"),
            Unit(sigla="CBM - DAT - SEC  - 1°SAT/1°CAT", descricao="SAT", link="110007086"),
        ]

        with self.client._auto_unit_switch(ARVORE_RESTRICTED) as switched:
            assert switched == "CBM - COBM - CMDO PABM APODI"

        # Should have switched to target and back
        assert mock_switch.call_count == 2
        mock_switch.assert_any_call("CBM - COBM - CMDO PABM APODI")
        mock_switch.assert_any_call("CBM - DAT - SEC  - 1°SAT/1°CAT")

    @patch.object(SEIClient, 'list_units')
    @patch.object(SEIClient, 'status')
    def test_raises_when_no_access(self, mock_status, mock_units):
        """Should raise RuntimeError if user can't access required unit."""
        from sei_cli.models import SystemStatus, Unit
        mock_status.return_value = SystemStatus(
            valid=True,
            unidade_sigla="SOME OTHER UNIT",
            unidade_descricao="Other",
            usuario="TEST",
            ultimo_acesso="",
        )
        mock_units.return_value = [
            Unit(sigla="SOME OTHER UNIT", descricao="Other", link="999"),
        ]

        with pytest.raises(RuntimeError, match="não tem acesso"):
            with self.client._auto_unit_switch(ARVORE_RESTRICTED):
                pass

    @patch.object(SEIClient, 'switch_unit')
    @patch.object(SEIClient, 'list_units')
    @patch.object(SEIClient, 'status')
    def test_no_switch_when_already_on_correct_unit(self, mock_status, mock_units, mock_switch):
        """Should not switch if already on the required unit."""
        from sei_cli.models import SystemStatus
        mock_status.return_value = SystemStatus(
            valid=True,
            unidade_sigla="CBM - COBM - CMDO PABM APODI",
            unidade_descricao="PABM",
            usuario="TEST",
            ultimo_acesso="",
        )

        with self.client._auto_unit_switch(ARVORE_RESTRICTED) as switched:
            assert switched is None

        mock_switch.assert_not_called()

    @patch.object(SEIClient, 'switch_unit')
    @patch.object(SEIClient, 'list_units')
    @patch.object(SEIClient, 'status')
    def test_restores_even_on_exception(self, mock_status, mock_units, mock_switch):
        """Should restore original unit even if an exception occurs inside."""
        from sei_cli.models import SystemStatus, Unit
        mock_status.return_value = SystemStatus(
            valid=True,
            unidade_sigla="CBM - DAT - SEC  - 1°SAT/1°CAT",
            unidade_descricao="SAT",
            usuario="TEST",
            ultimo_acesso="",
        )
        mock_units.return_value = [
            Unit(sigla="CBM - COBM - CMDO PABM APODI", descricao="PABM", link="110008367"),
        ]

        with pytest.raises(ValueError):
            with self.client._auto_unit_switch(ARVORE_RESTRICTED) as switched:
                raise ValueError("test error")

        # Should still have tried to restore
        assert mock_switch.call_count == 2
        mock_switch.assert_any_call("CBM - DAT - SEC  - 1°SAT/1°CAT")
