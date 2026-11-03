"""Moteur d'ancres MULTILINGUE (24 langues) — tests.

Objectifs verifies :
  1. une reformulation (meme sens, mots permutes) produit EXACTEMENT les
     memes ancres soft, dans toutes les langues ;
  2. changer l'entite (DNS -> HTTP) change les ancres : le garde-fou
     anti-faux-positif reste actif quelle que soit la langue ;
  3. la detection de langue fonctionne (mots-outil + script) ;
  4. aucune langue n'est codee en dur dans le code : les profils viennent de
     config/lang_profiles.json.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from icy_lang import (  # noqa: E402
    detect_language,
    extract_soft,
    load_profiles,
)

# code : (q1, q2 = reformulation, q3 = meme question mais entite differente)
SAMPLES = {
    "en": ("What is the difference between a DNS cache and a web cache? Answer in two sentences.",
           "Answer in two sentences: what is the difference between a web cache and a DNS cache?",
           "What is the difference between an HTTP cache and a web cache? Answer in two sentences."),
    "fr": ("Quelle est la différence entre un cache DNS et un cache web ? Réponds en deux phrases.",
           "En deux phrases : quelle est la différence entre un cache web et un cache DNS ?",
           "Quelle est la différence entre un cache HTTP et un cache web ? Réponds en deux phrases."),
    "es": ("¿Cuál es la diferencia entre una caché DNS y una caché web? Responde en dos frases.",
           "Responde en dos frases: ¿cuál es la diferencia entre una caché web y una caché DNS?",
           "¿Cuál es la diferencia entre una caché HTTP y una caché web? Responde en dos frases."),
    "pt": ("Qual é a diferença entre um cache DNS e um cache web? Responda em duas frases.",
           "Responda em duas frases: qual é a diferença entre um cache web e um cache DNS?",
           "Qual é a diferença entre um cache HTTP e um cache web? Responda em duas frases."),
    "it": ("Qual è la differenza tra una cache DNS e una cache web? Rispondi in due frasi.",
           "Rispondi in due frasi: qual è la differenza tra una cache web e una cache DNS?",
           "Qual è la differenza tra una cache HTTP e una cache web? Rispondi in due frasi."),
    "de": ("Was ist der Unterschied zwischen einem DNS-Cache und einem Web-Cache?",
           "Was ist der Unterschied zwischen einem Web-Cache und einem DNS-Cache?",
           "Was ist der Unterschied zwischen einem HTTP-Cache und einem Web-Cache?"),
    "nl": ("Wat is het verschil tussen een DNS-cache en een webcache?",
           "Wat is het verschil tussen een webcache en een DNS-cache?",
           "Wat is het verschil tussen een HTTP-cache en een webcache?"),
    "pl": ("Jaka jest różnica między pamięcią DNS i pamięcią WWW?",
           "Jaka jest różnica między pamięcią WWW i pamięcią DNS?",
           "Jaka jest różnica między pamięcią HTTP i pamięcią WWW?"),
    "sv": ("Vad är skillnaden mellan en DNS-cache och en webbcache?",
           "Vad är skillnaden mellan en webbcache och en DNS-cache?",
           "Vad är skillnaden mellan en HTTP-cache och en webbcache?"),
    "da": ("Hvad er forskellen mellem en DNS-cache og en webcache?",
           "Hvad er forskellen mellem en webcache og en DNS-cache?",
           "Hvad er forskellen mellem en HTTP-cache og en webcache?"),
    "cs": ("Jaký je rozdíl mezi DNS mezipaměti a web mezipaměti?",
           "Jaký je rozdíl mezi web mezipaměti a DNS mezipaměti?",
           "Jaký je rozdíl mezi HTTP mezipaměti a web mezipaměti?"),
    "hu": ("Mi a különbség a DNS gyorsítótár és a web gyorsítótár között?",
           "Mi a különbség a web gyorsítótár és a DNS gyorsítótár között?",
           "Mi a különbség a HTTP gyorsítótár és a web gyorsítótár között?"),
    "fi": ("Mikä on ero DNS-välimuistin ja verkkowälimuistin välillä?",
           "Mikä on ero verkkowälimuistin ja DNS-välimuistin välillä?",
           "Mikä on ero HTTP-välimuistin ja verkkowälimuistin välillä?"),
    "no": ("Hva er forskjellen mellom en DNS-buffer og en webbuffer?",
           "Hva er forskjellen mellom en webbuffer og en DNS-buffer?",
           "Hva er forskjellen mellom en HTTP-buffer og en webbuffer?"),
    "tr": ("DNS önbelleği ile web önbelleği arasındaki fark nedir?",
           "Web önbelleği ile DNS önbelleği arasındaki fark nedir?",
           "HTTP önbelleği ile web önbelleği arasındaki fark nedir?"),
    "ru": ("Какова разница между кэшем DNS и веб-кэшем?",
           "Какова разница между веб-кэшем и кэшем DNS?",
           "Какова разница между кэшем HTTP и веб-кэшем?"),
    "uk": ("Яка різниця між кешем DNS і веб-кешем?",
           "Яка різниця між веб-кешем і кешем DNS?",
           "Яка різниця між кешем HTTP і веб-кешем?"),
    "zh": ("DNS 缓存和网页缓存有什么区别？",
           "网页缓存和 DNS 缓存有什么区别？",
           "HTTP 缓存和网页缓存有什么区别？"),
    "ja": ("DNSキャッシュとWebキャッシュの違いは何ですか？",
           "WebキャッシュとDNSキャッシュの違いは何ですか？",
           "HTTPキャッシュとWebキャッシュの違いは何ですか？"),
    "ko": ("DNS 캐시와 웹 캐시의 차이는 무엇입니까?",
           "웹 캐시와 DNS 캐시의 차이는 무엇입니까?",
           "HTTP 캐시와 웹 캐시의 차이는 무엇입니까?"),
    "ar": ("ما الفرق بين ذاكرة DNS المؤقتة وذاكرة الويب المؤقتة؟",
           "ما الفرق بين ذاكرة الويب المؤقتة وذاكرة DNS المؤقتة؟",
           "ما الفرق بين ذاكرة HTTP المؤقتة وذاكرة الويب المؤقتة؟"),
    "hi": ("DNS कैश और वेब कैश में क्या अंतर है?",
           "वेब कैश और DNS कैश में क्या अंतर है?",
           "HTTP कैश और वेब कैश में क्या अंतर है?"),
    "bn": ("DNS ক্যাশ এবং ওয়েব ক্যাশের মধ্যে পার্থক্য কী?",
           "ওয়েব ক্যাশ এবং DNS ক্যাশের মধ্যে পার্থক্য কী?",
           "HTTP ক্যাশ এবং ওয়েব ক্যাশের মধ্যে পার্থক্য কী?"),
}

# Langues dont la detection par mots-outil est testee (les autres sont
# verifiees par le script, cf. test_script_detection).
DETECT_STRONG = {"en", "fr", "es", "pt", "it", "de", "nl", "ru", "pl", "tr"}


def test_at_least_twelve_languages_are_profiled():
    profiles = load_profiles()
    assert len(profiles) >= 12, f"seulement {len(profiles)} langue(s) profilee(s)"
    for code in SAMPLES:
        assert code in profiles, f"langue sans profil : {code}"


def test_no_language_is_hardcoded_in_the_module():
    """Les profils viennent du JSON : le module ne doit contenir aucun mot-outil
    sous forme de litteral (une mention dans un commentaire est sans effet)."""
    import re

    import icy_lang
    src = open(icy_lang.__file__, encoding="utf-8").read()
    for word in ("quelle", "ist", "und", "the", "что", "comme", "wie", "как", "nedir"):
        assert not re.search(r"""["']""" + word + r"""["']""", src, re.IGNORECASE), \
            f"mot-outil en dur dans icy_lang.py : {word}"


def test_paraphrase_keeps_the_same_anchors():
    """Reformulation = memes ancres soft (le cache semantique peut repondre)."""
    for code, (q1, q2, _q3) in SAMPLES.items():
        a1, a2 = extract_soft(q1), extract_soft(q2)
        assert a1 == a2, f"{code}: ancres differentes pour une reformulation : {a1} != {a2}"


def test_entity_change_is_detected():
    """Changer l'entite (DNS -> HTTP) change les ancres : garde-fou intact."""
    for code, (q1, _q2, q3) in SAMPLES.items():
        a1, a3 = extract_soft(q1), extract_soft(q3)
        assert a1 != a3, f"{code}: garde-fou anti-faux-positif inactif ({a1} == {a3})"


def test_acronym_is_always_an_anchor():
    for code, (q1, _q2, _q3) in SAMPLES.items():
        assert "dns" in extract_soft(q1), f"{code}: acronyme DNS non detecte"


def test_language_detection():
    for code in sorted(DETECT_STRONG):
        q1 = SAMPLES[code][0]
        got, conf = detect_language(q1)
        assert got == code, f"{code}: detection -> {got} (conf={conf})"


def test_script_detection_for_caseless_languages():
    for code in ("zh", "ja", "ko", "ar", "hi", "bn"):
        got, _conf = detect_language(SAMPLES[code][0])
        assert got == code, f"{code}: detection script -> {got}"


def test_unknown_language_keeps_strict_behaviour():
    """Langue non identifiee => on garde des ancres (sur-cote plutot que sous-cote)."""
    txt = "un Zorblax et un Quaxtron"
    assert extract_soft(txt) >= {"zorblax", "quaxtron"}


def test_sentence_start_is_not_an_entity():
    """Le mot qui ouvre la phrase n'est pas une entite, meme en francais."""
    assert "quelle" not in extract_soft("Quelle est la différence ?")
    assert "reponds" not in extract_soft("Quelle est la différence ? Réponds en deux phrases.")
    assert "reponds" not in extract_soft("Reponds en deux phrases.")


def test_german_nouns_are_not_entities():
    """En allemand TOUS les noms sont capitalises : ils ne doivent pas
    devenir des ancres (sinon aucune reformulation ne matche)."""
    a = extract_soft("Was ist der Unterschied zwischen einem DNS-Cache und einem Web-Cache?")
    assert a == frozenset({"dns"}), a
