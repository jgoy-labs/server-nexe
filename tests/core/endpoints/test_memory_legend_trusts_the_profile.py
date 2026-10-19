"""The legend tells the model a stated fact stays true when the conversation it
came from is not in view (13/10: it took «tens 45 anys» back for lack of a
source, after the conversations were gone)."""
import pytest

from core.context_presentation.default import DefaultContextPresenter
from core.context_presentation.port import ContextShape


def _legend(lang):
    return DefaultContextPresenter().frame(ContextShape(has_rag=True, lang=lang)).legend


@pytest.mark.parametrize("lang, needle", [
    ("ca", "encara que no vegis la conversa"),
    ("es", "aunque no veas la conversacion"),
    ("en", "even if you cannot see the conversation"),
])
def test_the_memory_line_says_to_trust_it(lang, needle):
    assert needle in _legend(lang)


@pytest.mark.parametrize("lang, needle", [
    ("ca", "parla-li de tu"),
    ("es", "hablale de tu"),
    ("en", "speak to them as you"),
])
def test_the_legend_says_who_the_user_is(lang, needle):
    """13/10: a 4B read «L'usuari es diu Maria» and answered «em dic Maria»; a 20B
    turned «l'usuari» into «vosaltres»."""
    assert needle in _legend(lang)
