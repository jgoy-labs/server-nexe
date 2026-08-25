"""
────────────────────────────────────
Server Nexe — test
Author: Jordi Goy
Location: tests/plugins/web_ui_module/test_uploads_stay_out_of_the_product.py
Description: #930 (segona meitat) — `plugins/web_ui_module/ui/uploads/` viu DINS
             l'arbre del producte, i era la SUITE qui l'omplia: mesurat el
             24/08 hi havia `test.txt`, `test_1.txt`, `test_2.txt` i
             `test_3.txt`, un per cada execució d'aquella nit (23:45, 00:04,
             00:14, 00:24). `test_upload_txt_file` mocka la memòria però la
             pujada és REAL, i el fitxer es quedava allà. D'allà se l'enduia el
             build, perquè el rsync copia del directori de treball.

             Repartiment de feines, perquè quedi clar què garanteix cadascú:
             que això no VIATGI ho garanteix el gate per naturalesa
             (tests/installer/test_g20_privacy_gate_by_nature.py) i els
             excludes del build; el fixture del conftest és HIGIENE — que la
             suite no vagi acumulant documents dins el producte.

             El primer intent va ser redirigir el directori, i estava malament:
             el guard WS5-01 es mesura contra el path real del mòdul, i moure'l
             feia que un document pujat es tornés a servir per `/ui/static/`
             sense auth (200 en comptes de 404). Un fixture que desactiva un
             control de seguretat és pitjor que la brossa que volia evitar.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PRODUCTE = REPO / "plugins" / "web_ui_module" / "ui" / "uploads"
CONFTEST = REPO / "conftest.py"


class TestUploadsDoNotPileUpInTheProduct:

    def test_the_product_upload_directory_is_not_accumulating(self):
        """Mesura directa: ara mateix, què hi ha al directori del producte.

        Si un test anterior hi ha deixat res, això es queixa — que és
        exactament com es va descobrir (quatre fitxers d'altres nits).
        """
        if not PRODUCTE.is_dir():
            return  # el directori el crea el producte al primer upload

        residus = sorted(p.name for p in PRODUCTE.iterdir() if p.name != ".gitkeep")

        assert not residus, (
            f"#930: hi ha {residus} dins l'arbre del producte ({PRODUCTE}). "
            "Un test hi ha escrit i no ho ha netejat; el build copia del "
            "directori de treball i s'ho endú al bundle"
        )

    def test_the_conftest_still_cleans_after_every_test(self):
        """Control d'abast del de sobre: la neteja no pot desaparèixer.

        El control de sobre només es queixa si l'atzar el fa córrer DESPRÉS del
        test que embruta. Aquest verifica que el mecanisme hi és, sigui quin
        sigui l'ordre.
        """
        text = CONFTEST.read_text(encoding="utf-8")

        assert "_uploads_never_pile_up_in_the_product" in text, (
            "#930: el conftest ha perdut la neteja del directori d'uploads"
        )
        i = text.index("def _uploads_never_pile_up_in_the_product")
        assert "@pytest.fixture(autouse=True)" in text[max(0, i - 200):i], (
            "la neteja d'uploads ha deixat de ser autouse: només protegiria els "
            "tests que la demanin, i el que embruta no la demana"
        )
        cos = text[i:i + 1600]
        assert "before" in cos and "iterdir" in cos, (
            "la neteja ha de ser per DIFERÈNCIA (què hi havia abans vs després); "
            "una llista de noms coneguts és el que va deixar passar aquests quatre"
        )
