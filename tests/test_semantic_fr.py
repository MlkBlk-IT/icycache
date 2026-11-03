"""Lot 2 : cache semantique et normalisation en FRANCAIS.

Ces tests verrouillent les corrections appliquees en 2026-11-03 :
  - normalize_numbers ne doit plus casser "plus de" (operateur verbal vs
    operateur arithmetique) ;
  - extract_hard ne doit plus avaler les slash ("A/B" -> "/b") ;
  - extract_soft doit detecter des ENTITES (acronymes, noms propres) et non
    les majuscules de debut de phrase ;
  - accepts() doit accepter une paraphrase FR reelle tout en refusant deux
    entites differentes (Montreal != Quebec City).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import icy_normalize  # noqa: E402
import icy_semantic  # noqa: E402
from icy_semantic import accepts, extract_hard, extract_soft, normalize_numbers  # noqa: E402

# ------------------------------------------------- normalize_numbers ---------

def test_english_arithmetic_is_normalized():
    assert "2+2" in normalize_numbers("What is two plus two?")
    assert normalize_numbers("5 minus 3") == "5-3"
    assert normalize_numbers("3 times 4") == "3*4"
    assert normalize_numbers("8 divided by 2") == "8/2"


def test_french_plus_de_is_not_an_operator():
    """'plus de' = 'more of' : ce n'est PAS une operation arithmetique."""
    assert normalize_numbers("Donne-moi plus de details sur le cache") == \
        "Donne-moi plus de details sur le cache"
    assert normalize_numbers("Il y a plus de 3 fichiers") == "Il y a plus de 3 fichiers"
    assert normalize_numbers("Plus de 10 unites") == "Plus de 10 unites"


def test_french_plus_de_and_arithmetic_coexist():
    t = normalize_numbers("Il y a plus de 3 fichiers et 2 plus 2 egale 4")
    assert "plus de 3" in t, t
    assert "2+2" in t, t


def test_single_source_for_number_normalization():
    """Les deux modules doivent partager la MEME implementation."""
    assert icy_semantic.normalize_numbers is icy_normalize.normalize_numbers


def test_normalizer_cache_key_does_not_corrupt_plus_de():
    """La cle de cache exact passe par Normalizer.normalize() : pas de '+de'."""
    out = icy_normalize.Normalizer().normalize("Donne-moi plus de 3 fichiers")
    assert "+de" not in out, out


# ------------------------------------------------------------ extract_hard ---

def test_slash_is_not_a_path_anchor():
    """'A/B' et '12/24' ne sont pas des chemins."""
    assert extract_hard("Compare A/B et C/D") == frozenset()
    h = extract_hard("le rapport 12/24 est stable")
    assert "12" in h and "24" in h
    assert not any(a.startswith("/") for a in h), h


def test_real_paths_are_still_anchors():
    assert any("/usr/local/bin" in a for a in extract_hard("lit /usr/local/bin/config"))
    assert any("file.txt" in a for a in extract_hard("ouvre D:/a/file.txt"))
    assert any("file.txt" in a for a in extract_hard("ouvre C:\\a\\file.txt"))


# ------------------------------------------------------------ extract_soft ---

def test_soft_anchors_ignore_sentence_start():
    q3 = "Quelle est la difference entre un cache DNS et un cache web ? Reponds en deux phrases."
    assert extract_soft(q3) == frozenset({"dns"}), extract_soft(q3)


def test_soft_anchors_acronyms_are_case_insensitive():
    assert extract_soft("le cache DNS") == frozenset({"dns"})
    assert extract_soft("le cache dns") == frozenset()


def test_soft_anchors_lowercase_text_has_none():
    assert extract_soft("weather in montreal today") == frozenset()
    assert "montreal" in extract_soft("Weather in Montreal today")


# --------------------------------------------------------------- accepts ----

def test_french_paraphrase_is_accepted():
    """Q3/Q4 de tests/granite_live_test.py : meme question, autre formulation."""
    q3 = "Quelle est la difference entre un cache DNS et un cache web ? Reponds en deux phrases."
    q4 = "En deux phrases : un cache web et un cache DNS, quelle difference ?"
    cand = {"anchors_hard": sorted(extract_hard(q4)), "anchors_soft": sorted(extract_soft(q4))}
    assert accepts(q3, cand, 0.99, query_soft=extract_soft(q3)), \
        "une paraphrase FR avec la meme entite doit etre acceptee"


def test_french_different_entity_is_rejected():
    """cache DNS != cache HTTP : garde-fou anti-faux-positif conserve."""
    q = "Quelle est la difference entre un cache DNS et un cache web ?"
    cand = {"anchors_hard": [], "anchors_soft": ["http"]}
    assert not accepts(q, cand, 0.99, query_soft=extract_soft(q))


def test_named_entity_mismatch_still_rejected():
    q = "weather in Montreal today"
    cand = {"anchors_hard": [], "anchors_soft": ["quebec", "city"]}
    assert not accepts(q, cand, 0.99, query_soft=extract_soft(q))


def test_hard_anchor_mismatch_still_rejected():
    q = "port 8080 weight 10kg"
    cand = {"anchors_hard": sorted(extract_hard("port 9090 weight 10kg")), "anchors_soft": []}
    assert not accepts(q, cand, 0.99, query_soft=extract_soft(q))
