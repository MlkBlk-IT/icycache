"""DELTA-004 : eligibilite du cache EXACT + construction de la cle.

Import de `server` avec une config TEMPORAIRE (DB temp) : la DB de production
(db/cache.db) n'est jamais touchee.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC))

_TMP = tempfile.mkdtemp(prefix="icycache_elig_")
_CFG = Path(_TMP) / "gateway.json"
_DB = Path(_TMP) / "cache.db"


def _write_cfg(cache: dict) -> None:
    _CFG.write_text(json.dumps({
        "proxy": {"host": "127.0.0.1", "port": 8099, "timeout": 5},
        "gateway": {"host": "127.0.0.1", "port": 8099, "default_upstream": "mock"},
        "upstreams": {"mock": {"base_url": "http://127.0.0.1:9", "kind": "openai"}},
        "cache": dict({"db_path": str(_DB), "max_entries": 10, "ttl_seconds": 60},
                      **cache),
    }), encoding="utf-8")


_write_cfg({"cache_when_temperature_unset": True})
os.environ["ICYCACHE_CONFIG"] = str(_CFG)
os.environ["ICYCACHE_DB"] = str(_DB)

import server  # noqa: E402
import icy_normalize  # noqa: E402


def _reload(cache: dict):
    """Pas de reload : on pilote le drapeau lu par cacheable_reason()."""
    old = server.CACHE_UNSET_TEMPERATURE
    server.CACHE_UNSET_TEMPERATURE = bool(cache.get("cache_when_temperature_unset", True))
    return server


def _restore():
    server.CACHE_UNSET_TEMPERATURE = True


# ------------------------------------------------------------ eligibilite ---
def test_temperature_unset_is_cacheable_when_enabled():
    _reload({"cache_when_temperature_unset": True})
    try:
        ok, why = server.cacheable_reason({"model": "m", "messages": []})
    finally:
        _restore()
    assert ok is True and "absent" in why


def test_temperature_unset_is_refused_when_disabled():
    _reload({"cache_when_temperature_unset": False})
    try:
        ok, why = server.cacheable_reason({"model": "m", "messages": []})
    finally:
        _restore()
    assert ok is False and "absent" in why


def test_temperature_zero_is_cacheable():
    _reload({"cache_when_temperature_unset": True})
    try:
        ok, why = server.cacheable_reason({"model": "m", "messages": [], "temperature": 0})
    finally:
        _restore()
    assert ok is True and "temperature=0" in why


def test_nonzero_temperature_is_refused():
    _reload({"cache_when_temperature_unset": True})
    try:
        ok, why = server.cacheable_reason({"model": "m", "messages": [], "temperature": 0.7})
    finally:
        _restore()
    assert ok is False and "non deterministe" in why


def test_unreadable_temperature_is_refused():
    _reload({"cache_when_temperature_unset": True})
    try:
        ok, why = server.cacheable_reason({"model": "m", "messages": [], "temperature": "hot"})
    finally:
        _restore()
    assert ok is False and "illisible" in why


# ------------------------------------------------- propriete / precedence ----
def test_semantic_is_opt_in_by_default(monkeypatch):
    """Sans fichier proprietaire ni env : le cache semantique reste DESACTIVE."""
    monkeypatch.delenv("SEMANTIC_ENABLED", raising=False)
    cfg = server._resolve_semantic_cfg({})
    assert cfg["semantic_enabled"] is False


def test_semantic_env_overrides_config(monkeypatch):
    monkeypatch.setenv("SEMANTIC_ENABLED", "true")
    cfg = server._resolve_semantic_cfg({"enable_semantic": False})
    assert cfg["semantic_enabled"] is True


def test_semantic_gateway_flag_is_only_a_fallback(monkeypatch):
    """Le flag de la config gateway ne sert QUE si le fichier proprietaire
    ne definit pas la cle : aucune valeur n'est ecrasee en silence."""
    monkeypatch.delenv("SEMANTIC_ENABLED", raising=False)
    cfg = server._resolve_semantic_cfg({"enable_semantic": True})
    assert cfg["semantic_enabled"] is True


# ----------------------------------------------------------------- cle ------
def _key(body):
    return icy_normalize.cache_key(body)


def test_key_contains_response_affecting_fields():
    base = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
    variants = [
        dict(base, model="other"),
        dict(base, top_p=0.1),
        dict(base, seed=42),
        dict(base, temperature=0.3),
        dict(base, response_format={"type": "json_object"}),
        dict(base, tools=[{"type": "function", "function": {"name": "f"}}]),
        dict(base, tool_choice="auto"),
    ]
    keys = {_key(base)} | {_key(v) for v in variants}
    assert len(keys) == len(variants) + 1, "un champ affectant la reponse a disparu de la cle"


def test_ignored_fields_do_not_change_the_key():
    """stream / stream_options / user / metadata : exclus (ils ne changent pas
    le contenu genere ; `stream` est gere par serve_hit qui adapte la forme)."""
    base = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
    for ignored in ({"stream": True}, {"stream_options": {"include_usage": True}},
                    {"user": "alice"}, {"metadata": {"a": 1}}):
        assert _key(dict(base, **ignored)) == _key(base), f"{ignored} a change la cle"


def test_tool_call_id_stays_in_the_key():
    """Deux conversations differentes (tool_call_id differents) ne doivent PAS
    partager la meme cle : sinon une reponse d'outil est rejouee a un autre client."""
    a = {"model": "m", "messages": [
        {"role": "assistant", "tool_calls": [{"id": "call_a", "function": {"name": "f", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_a", "content": "42"}]}
    b = {"model": "m", "messages": [
        {"role": "assistant", "tool_calls": [{"id": "call_b", "function": {"name": "f", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "call_b", "content": "42"}]}
    assert _key(a) != _key(b), "tool_call_id efface : conversations fusionnees"


def test_tool_call_ids_are_not_blanked():
    """Les ids des tool_calls d'un message assistant doivent rester dans la cle."""
    a = {"model": "m", "messages": [
        {"role": "assistant", "tool_calls": [{"id": "call_a", "function": {"name": "f", "arguments": "{}"}}]}]}
    b = {"model": "m", "messages": [
        {"role": "assistant", "tool_calls": [{"id": "call_b", "function": {"name": "f", "arguments": "{}"}}]}]}
    assert _key(a) != _key(b), "ids de tool_calls blanchis : collision de conversations"


def test_normalization_still_collapses_equivalent_payloads():
    a = {"model": "m", "messages": [{"role": "user", "content": "Bonjour !"}]}
    b = {"model": "m", "messages": [{"role": "user", "content": "bonjour"}]}
    assert _key(a) == _key(b), "la normalisation doit toujours fusionner les variantes"


def test_scope_is_part_of_the_key():
    """La cle inclut le perimetre (upstream + endpoint) : pas de partage entre upstreams."""
    import hashlib
    body = {"model": "m", "messages": [{"role": "user", "content": "hi"}]}
    k1 = icy_normalize.cache_key(body, {"upstream": "a", "path": "/v1/chat/completions"})
    k2 = icy_normalize.cache_key(body, {"upstream": "b", "path": "/v1/chat/completions"})
    k3 = icy_normalize.cache_key(body, {"upstream": "a", "path": "/v1/messages"})
    assert len({k1, k2, k3}) == 3


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  {fn.__name__}: PASS")
    print(f"=== {len(fns)} tests passed ===")
