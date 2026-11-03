"""DELTA-003 : cache semantique comme SECOND NIVEAU — tests isoles (aucun reseau).

Fakes : FakeStore (filtre par scope + seuil), FakeEmbedder (vecteur constant).
Aucun appel Qdrant / LM Studio : les tests ne doivent dependre d'aucun service.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from icy_semantic import (  # noqa: E402
    SemanticLookup, accepts, extract_hard, extract_soft,
    semantic_eligibility, semantic_scope,
)

CFG = {"semantic_enabled": True, "semantic_threshold": 0.95, "semantic_relax_threshold": 0.97}


class _Point:
    """Mimique un PointStruct Qdrant (.score / .payload)."""
    __slots__ = ("score", "payload", "sig")

    def __init__(self, d):
        self.score = float(d.get("score", 0.0))
        self.payload = d.get("payload") or {}
        self.sig = d.get("sig")


class FakeStore:
    def __init__(self, points=None, available=True):
        self.available = available
        self.points = points or []
        self.upserts = []

    def ensure(self, dim):
        return None

    def search(self, sig, vec, seuil, top=1):
        best = None
        for p in self.points:
            if p.get("sig") != sig:
                continue
            if float(p.get("score", 0.0)) < float(seuil):
                continue
            if best is None or p["score"] > best["score"]:
                best = p
        return _Point(best) if best else None

    def upsert(self, vec, payload):
        self.upserts.append(payload)


class FakeEmbedder:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    def embed(self, text):
        self.calls += 1
        if self.fail:
            raise RuntimeError("embedder down")
        return [0.1, 0.2, 0.3]


def _cand(sig="S", score=0.99, hard=(), soft=(), response="STORED"):
    return {"sig": sig, "score": score,
            "payload": {"sig": sig, "response": response, "model": "m",
                        "anchors_hard": sorted(hard), "anchors_soft": sorted(soft),
                        "created_at": "2026-11-02 10:00:00"}}


# ---------------------------------------------------------------- scope ------
def test_scope_separates_upstream_model_and_endpoint():
    b = {"model": "m", "temperature": 0}
    s1 = semantic_scope(b, "up-a", "/v1/chat/completions", "openai")
    s2 = semantic_scope(b, "up-b", "/v1/chat/completions", "openai")
    s3 = semantic_scope(b, "up-a", "/v1/messages", "anthropic")
    s4 = semantic_scope({"model": "m2", "temperature": 0}, "up-a", "/v1/chat/completions", "openai")
    s5 = semantic_scope({"model": "m", "temperature": 0, "top_p": 0.5},
                        "up-a", "/v1/chat/completions", "openai")
    assert len({s1, s2, s3, s4, s5}) == 5, "le scope doit isoler upstream/endpoint/modele/params"


def test_scope_is_stable_for_same_request():
    b = {"model": "m", "temperature": 0, "messages": [{"role": "user", "content": "x"}]}
    assert semantic_scope(b, "u", "/v1/chat/completions") == semantic_scope(
        b, "u", "/v1/chat/completions")


# ------------------------------------------------------------ eligibilite ----
def test_eligibility_rejects_tools_and_tool_choice():
    ok, why = semantic_eligibility({"messages": [{"role": "user", "content": "hi"}],
                                    "tools": [{"type": "function"}]})
    assert not ok and "tools" in why
    ok, why = semantic_eligibility({"messages": [{"role": "user", "content": "hi"}],
                                    "tool_choice": "auto"})
    assert not ok and "tool_choice" in why


def test_eligibility_rejects_tool_history():
    ok, why = semantic_eligibility({"messages": [
        {"role": "assistant", "tool_calls": [{"id": "c1", "function": {"name": "f"}}]}]})
    assert not ok and "tool_calls" in why
    ok, why = semantic_eligibility({"messages": [
        {"role": "tool", "tool_call_id": "c1", "content": "42"}]})
    assert not ok and "tool_call_id" in why


def test_eligibility_rejects_multimodal():
    ok, why = semantic_eligibility({"messages": [
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "u"}}]}]})
    assert not ok and "multimodal" in why


def test_eligibility_accepts_plain_text():
    ok, why = semantic_eligibility({"messages": [{"role": "user", "content": "hello"}]})
    assert ok and why == "eligible"


# ------------------------------------------------------------- hit / miss ----
def test_semantic_hit_returns_payload():
    store = FakeStore([_cand(sig="S", score=0.99, hard=[], soft=["montreal"])])
    lk = SemanticLookup(CFG, store=store, embedder=FakeEmbedder())
    found = lk.lookup("what is the weather in montreal today", "What is the weather in Montreal today", "S")
    assert found is not None, "hit semantique attendu"
    payload, score = found
    assert payload["response"] == "STORED"
    assert score >= 0.95


def test_semantic_miss_below_threshold():
    store = FakeStore([_cand(sig="S", score=0.80)])
    lk = SemanticLookup(CFG, store=store, embedder=FakeEmbedder())
    assert lk.lookup("q", "Q", "S") is None


def test_semantic_miss_wrong_scope_is_rejected():
    """Un hit stocke sous un autre scope ne doit JAMAIS etre servi."""
    store = FakeStore([_cand(sig="OTHER", score=0.99)])
    lk = SemanticLookup(CFG, store=store, embedder=FakeEmbedder())
    assert lk.lookup("q", "Q", "S") is None


def test_hard_anchor_mismatch_rejected():
    """Nombres / quotes / paths / URLs / unites differents => rejet."""
    cases = [
        ("read D:/a/file.txt", "read D:/b/file.txt"),
        ("fetch https://example.com/api", "fetch https://other.com/api"),
        ("port 8080 weight 10kg", "port 9090 weight 10kg"),
        ('say "hello"', 'say "bye"'),
        ("2+2 equals 4", "2+2 equals 5"),
    ]
    for q, cand_q in cases:
        cand = _cand(sig="S", score=0.99, hard=extract_hard(cand_q), soft=[])
        store = FakeStore([cand])
        lk = SemanticLookup(CFG, store=store, embedder=FakeEmbedder())
        assert lk.lookup(q, q, "S") is None, f"ancres hard divergentes acceptees : {q!r}"


def test_named_entity_mismatch_rejected():
    """Montreal != Quebec City (ancres SOFT issues du texte BRUT)."""
    q = "weather in Montreal today"
    cand = _cand(sig="S", score=0.99, hard=[], soft=["quebec", "city"])
    store = FakeStore([cand])
    lk = SemanticLookup(CFG, store=store, embedder=FakeEmbedder())
    assert lk.lookup(q, q, "S") is None


def test_named_entity_match_accepted():
    q = "weather in Montreal today"
    cand = _cand(sig="S", score=0.99, hard=[], soft=["montreal"])
    store = FakeStore([cand])
    lk = SemanticLookup(CFG, store=store, embedder=FakeEmbedder())
    assert lk.lookup(q, q, "S") is not None


def test_unavailable_store_returns_none():
    lk = SemanticLookup(CFG, store=FakeStore(available=False), embedder=FakeEmbedder())
    assert lk.available is False
    assert lk.lookup("q", "Q", "S") is None


def test_embedder_failure_is_silent_miss():
    lk = SemanticLookup(CFG, store=FakeStore([_cand(sig="S")]), embedder=FakeEmbedder(fail=True))
    assert lk.lookup("q", "Q", "S") is None


def test_soft_anchors_survive_lowercased_text():
    """Sur texte normalise (minuscules) extract_soft ne rend RIEN : le caller
    doit passer les ancres du texte BRUT, sinon le garde-fou disparait."""
    assert extract_soft("weather in montreal today") == frozenset()
    assert "montreal" in extract_soft("Weather in Montreal today")
    assert accepts("weather in montreal today",
                   {"anchors_hard": [], "anchors_soft": ["montreal"]}, 0.99,
                   query_soft=extract_soft("Weather in Montreal today"))


def test_lookup_never_raises_on_broken_store():
    class Broken:
        available = True

        def search(self, *a, **k):
            raise RuntimeError("qdrant boom")

    lk = SemanticLookup(CFG, store=Broken(), embedder=FakeEmbedder())
    assert lk.lookup("q", "Q", "S") is None


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  {fn.__name__}: PASS")
    print(f"=== {len(fns)} tests passed ===")
