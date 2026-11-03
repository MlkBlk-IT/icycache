"""Moteur d'ancres MULTILINGUE (remplace la liste FR codee en dur).

Le cache semantique a besoin d'ANCRE SOFT = entite nommee, pour distinguer
"cache DNS" de "cache HTTP". Mais la casse n'est un marqueur d'entite que dans
certaines langues :

  - langues "sentence" (en, fr, es, pt, it, vi, tr) : seule la majuscule de
    debut de phrase est automatique -> un mot capitalise EN MILIEU de phrase
    est une entite ;
  - langues "noun" (de, nl, pl, sv, da, cs, hu, fi, no, ru, uk) : TOUS les noms
    sont capitalises -> un mot capitalise n'est PAS une entite, il faut le
    filtrer ;
  - langues "none" (zh, ja, ko, ar, hi, bn) : pas de distinction de casse -> les
    ancres viennent des acronymes latins et du CamelCase uniquement.

Aucune langue n'est codee en dur ici : les profils vivent dans
config/lang_profiles.json. Ajouter une langue = ajouter une cle JSON.

Regle de securite (asymetrique) : TROP d'ancres = cache miss (perte de perf,
jamais de mauvaise reponse) ; PAS ASSEZ d'ancres = faux positif (mauvaise
reponse servie). Toute incertitude (langue non detectee) conserve le
comportement le plus strict, c'est-a-dire le plus d'ancres.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

__all__ = [
    "load_profiles",
    "detect_script",
    "detect_language",
    "extract_soft",
    "PROFILES_PATH",
]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILES_PATH = PROJECT_ROOT / "config" / "lang_profiles.json"

# Tokenisation PAR SCRIPT : un mot latin s'arrete a la 1re lettre CJK/Cyrillique/
# arabe, sinon "DNSキャッシュ" serait un seul token et l'acronyme DNS
# deviendrait invisible. Les runs de chaque script sont tokenises separement.
_LATIN = r"A-Za-z\u00C0-\u024F\u0300-\u036F"
_CYRILLIC = r"\u0400-\u04FF"
_GREEK = r"\u0370-\u03FF"
_HAN = r"\u3400-\u4DBF\u4E00-\u9FFF"
_KANA = r"\u3040-\u30FF"
_HANGUL = r"\uAC00-\uD7AF\u1100-\u11FF"
_ARABIC = r"\u0600-\u06FF\u0750-\u077F"
_DEVANAGARI = r"\u0900-\u097F"
_BENGALI = r"\u0980-\u09FF"

_TOKEN_RE = re.compile(
    f"[{_LATIN}{_CYRILLIC}{_GREEK}]+"
    f"|[{_HAN}]+"
    f"|[{_KANA}]+"
    f"|[{_HANGUL}]+"
    f"|[{_ARABIC}]+"
    f"|[{_DEVANAGARI}]+"
    f"|[{_BENGALI}]+"
)

# Detection de script : l'ordre compte (le japonais utilise aussi des han).
_SCRIPTS = (
    ("hangul", re.compile(r"[\uac00-\ud7af]")),
    ("japanese", re.compile(r"[\u3040-\u309f\u30a0-\u30ff]")),
    ("han", re.compile(r"[\u4e00-\u9fff]")),
    ("cyrillic", re.compile(r"[\u0400-\u04ff]")),
    ("arabic", re.compile(r"[\u0600-\u06ff]")),
    ("devanagari", re.compile(r"[\u0900-\u097f]")),
    ("bengali", re.compile(r"[\u0980-\u09ff]")),
)

# Fin de phrase (vrai separateur de phrase, pas la virgule).
# Inclut "¿" "¡" "؟" : ils ouvrent une question/exclamation dans leur langue.
_SENT_END = ".!?\n\r¿¡؟"

_PROFILES: dict | None = None


def load_profiles(path: Path | str | None = None) -> dict:
    """Profils linguistiques (cache en memoire). Cle sans "_" = une langue."""
    global _PROFILES
    if path is None and _PROFILES is not None:
        return _PROFILES
    p = Path(path) if path else PROFILES_PATH
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    profiles = {k: v for k, v in raw.items() if isinstance(v, dict) and not k.startswith("_")}
    if path is None:
        _PROFILES = profiles
    return profiles


def detect_script(text: str) -> str | None:
    """Script dominant du texte (latin / han / cyrillic / ...)."""
    for name, rx in _SCRIPTS:
        if rx.search(text):
            return name
    return "latin"


def detect_language(text: str) -> tuple[str | None, float]:
    """(code, confiance). None si la langue est ambigue : on garde alors le
    comportement strict (le plus d'ancres), jamais le laxiste."""
    if not text or not text.strip():
        return (None, 0.0)
    profiles = load_profiles()
    if not profiles:
        return (None, 0.0)

    script = detect_script(text)
    if script != "latin":
        for code, prof in profiles.items():
            if prof.get("script") == script:
                return (code, 1.0)
        return (None, 0.0)

    tokens = {m.group(0).lower() for m in _TOKEN_RE.finditer(text)}
    if not tokens:
        return (None, 0.0)
    scores = []
    for code, prof in profiles.items():
        if prof.get("script") != "latin":
            continue
        stop = prof.get("stop") or ()
        hits = len(tokens.intersection(stop))
        if hits:
            scores.append((hits, code))
    if not scores:
        return (None, 0.0)
    scores.sort(key=lambda t: (-t[0], t[1]))
    top_hits, top_code = scores[0]
    second_hits = scores[1][0] if len(scores) > 1 else 0
    # Exigence de 2 mots-outil distincts ET d'une avance sur le 2e candidat :
    # "in" est dans plusieurs listes, un seul hit ne prouve rien.
    if top_hits < 2 or top_hits <= second_hits:
        return (None, 0.0)
    return (top_code, min(1.0, top_hits / 8.0))


def _at_sentence_start(text: str, start: int) -> bool:
    i = start - 1
    while i >= 0 and text[i] in " \t":
        i -= 1
    if i < 0:
        return True
    return text[i] in _SENT_END


def extract_soft(text: str, lang: str | None = None) -> frozenset[str]:
    """Entites fortes du texte, independamment de la langue.

    - acronymes (DNS, HTTP, SQL) : toutes langues ;
    - CamelCase interne (OpenAI, PowerShell) : toutes langues ;
    - mot capitalise hors debut de phrase : selon le profil de la langue
      ("sentence" -> entite ; "noun" -> filtre via la liste 'common').
    """
    if not text:
        return frozenset()
    profiles = load_profiles()
    out: set[str] = set()

    for m in _TOKEN_RE.finditer(text):
        tok = m.group(0)
        n = len(tok)
        if n < 2:
            continue
        if tok.isupper() and tok.isalpha() and n <= 8:
            out.add(tok.lower())
        elif n >= 3 and any(c.isupper() for c in tok[1:]):
            out.add(tok.lower())

    code = lang
    if code is None:
        code, _conf = detect_language(text)
    prof = profiles.get(code) if code else None
    case_mode = (prof or {}).get("case", "sentence")
    if case_mode == "none":
        return frozenset(out)

    common = set((prof or {}).get("common") or ())
    for m in _TOKEN_RE.finditer(text):
        tok = m.group(0)
        if len(tok) < 3:
            continue
        if not (tok[0].isupper() and tok[1:].islower()):
            continue
        if _at_sentence_start(text, m.start()):
            continue
        low = tok.lower()
        if low in common:
            continue
        out.add(low)
    return frozenset(out)
