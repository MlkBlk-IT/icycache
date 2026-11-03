"""Cache sémantique hybride — DELTA-002 Volet B.

Qdrant est importé LAZILY: si qdrant-client n'est pas installé ou Qdrant est down,
tout échec = miss silencieux → upstream. Jamais de panne.

Embedding model: auto-discovery via /v1/models (pas de hardcodage).
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid

# Source UNIQUE de la normalisation des nombres (mots-nombres -> chiffres,
# operateurs verbaux -> symboles). Importee aussi par icy_normalize, qui calcule
# la cle de cache EXACT : les deux copies divergeaient et les deux cassaient
# le francais ("plus de details" -> "plus+de details").
from icy_normalize import normalize_numbers  # noqa: F401
from icy_lang import extract_soft  # noqa: F401

logger = logging.getLogger("icycache.semantic")

# ---- Ancres (grounding anti-faux-positif) -----------------------------------

_HARD = [
    ("num", r"\b\d+(?:[.,]\d+)?\b"),
    ("quote", r"[\"'`]([^\"'`]{1,60})[\"'`]"),
    # Un chemin = racine windows ("C:\dir\f"), relatif ("./dir") ou absolu POSIX
    # avec AU MOINS 2 segments. L'ancien motif "(?:\./|/)[^\s]+" matchait TOUT
    # slash : "A/B" -> "/b", "12/24" -> "/24", "cache DNS/web" -> "/web".
    # Consequence : deux paraphrases francaises avaient des ancres hard
    # differentes => le cache semantique ne pouvait jamais repondre.
    ("path", r"\b[A-Za-z]:\\[^\s]+|(?:\./[^\s]+)|(?:/(?:[\w.\-]+/)+[\w.\-]+)"),
    ("unit", r"\b\d+\s?(?:kg|km|cm|mm|mb|gb|tb|ms|min|h|%|°c|°f|usd|eur)\b"),
    ("url", r"https?://[^\s]+"),
]


def extract_hard(text: str) -> frozenset[str]:
    low = text.lower()
    out = set()
    for _, pat in _HARD:
        out.update(m.group(0).strip() for m in re.finditer(pat, low))
    return frozenset(out)


# Ancres SOFT = entites fortes, resolues par le moteur MULTILINGUE
# (src/icy_lang.py) : la casse n'est un marqueur d'entite que dans certaines
# langues. Aucune langue n'est codee en dur ici (cf. extract_soft ci-dessus).


def accepts(query_norm: str, cand: dict, score: float,
            HARD_MIN: float = 0.95, RELAX: float = 0.97, query_soft=None) -> bool:
    if score < HARD_MIN:
        return False
    qh, ch = extract_hard(query_norm), frozenset(cand.get("anchors_hard", []))
    if qh != ch:
        return False
    qs = frozenset(query_soft) if query_soft is not None else extract_soft(query_norm)
    cs = frozenset(cand.get("anchors_soft", []))
    if qs == cs:
        return True
    # RELAX : grounding PARTAGE obligatoire. Les ancres hard (nombres, chemins,
    # URLs, quotes) doivent etre identiques, OU les deux textes doivent partager
    # au moins une entite forte. Sans ce garde-fou, "Montreal" et "Quebec City"
    # seraient acceptes a 0.99 de similarite. (Le texte normalise etant en
    # minuscules, il ne porte AUCUNE ancre soft : sans ce partage, la voie RELAX
    # ne declencherait plus jamais, ni sur la gateway ni sur le MCP.)
    if score >= RELAX and (qh or (qs & cs)):
        return True
    return False


# ---- Embedder (auto-discovery LM Studio) ------------------------------------

class Embedder:
    def __init__(self, base_url: str, model: str | None = None, timeout: float = 10.0):
        import httpx
        self._c = httpx.Client(base_url=base_url, timeout=timeout)
        self._m = model
        if not self._m:
            self._m = self._discover_model()

    def _discover_model(self) -> str:
        try:
            r = self._c.get("/v1/models")
            r.raise_for_status()
            for m in r.json().get("data", []):
                mid = m.get("id", "")
                if "embed" in mid.lower() or "bge" in mid.lower() or "e5" in mid.lower():
                    return mid
            # fallback: premier modèle dispo
            models = r.json().get("data", [])
            if models:
                return models[0]["id"]
        except Exception as e:
            logger.warning("Embedder auto-discovery failed: %s", e)
        raise RuntimeError("No embedding model found via /v1/models")

    def embed(self, text: str) -> list[float]:
        r = self._c.post("/v1/embeddings", json={"model": self._m, "input": text})
        r.raise_for_status()
        v = r.json()["data"][0]["embedding"]
        n = sum(x * x for x in v) ** 0.5 or 1.0
        return [x / n for x in v]


# ---- Store Qdrant (lazy import) ---------------------------------------------

class SemanticStore:
    COLL = "icycache_semantic"
    _qdrant = None
    _client = None

    def __init__(self, url: str):
        self._url = url
        self._lock = threading.Lock()
        self._init_qdrant()

    def _init_qdrant(self):
        try:
            from qdrant_client import QdrantClient, models
            SemanticStore._qdrant = (QdrantClient, models)
            self._client = QdrantClient(url=self._url)
        except ImportError:
            logger.info("qdrant-client not installed — semantic cache disabled (miss silencieux)")
            self._client = None
        except Exception as e:
            logger.warning("Qdrant unreachable: %s — semantic cache disabled", e)
            self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def ensure(self, dim: int):
        if not self._client:
            return
        try:
            QdrantClient, models = SemanticStore._qdrant
            if not self._client.collection_exists(self.COLL):
                self._client.create_collection(
                    self.COLL,
                    vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
                )
        except Exception as e:
            logger.warning("Qdrant ensure collection failed: %s", e)
            self._client = None

    def search(self, sig: str, vec: list[float], seuil: float, top: int = 1):
        if not self._client:
            return None
        try:
            QdrantClient, models = SemanticStore._qdrant
            res = self._client.query_points(
                collection_name=self.COLL, query=vec, limit=top,
                score_threshold=seuil,
                query_filter=models.Filter(must=[models.FieldCondition(
                    key="sig", match=models.MatchValue(value=sig))]),
                with_payload=True,
            ).points
            return res[0] if res else None
        except Exception as e:
            logger.warning("Qdrant search failed: %s — miss silencieux", e)
            return None

    def upsert(self, vec: list[float], payload: dict):
        if not self._client:
            return
        try:
            QdrantClient, models = SemanticStore._qdrant
            with self._lock:
                self._client.upsert(self.COLL, points=[models.PointStruct(
                    id=str(uuid.uuid4()), vector=vec, payload=payload)])
        except Exception as e:
            logger.warning("Qdrant upsert failed: %s — index skipped", e)


# ---- Indexation async (ne bloque jamais) ------------------------------------

def index_async(store: SemanticStore, embedder: Embedder, sig: str,
                 query_norm: str, resp_json: str, query_raw: str | None = None):
    """Indexation en arriere-plan (DELTA-002, cote MCP).

    `query_raw` (texte BRUT) alimente les ancres soft, comme pour la voie
    DELTA-003 : le texte normalise est en minuscules et ne porte donc aucune
    ancre soft. Sans cette coherence, un hit semantique du MCP ne pouvait pas
    etre compare a une entite forte (le garde-fou "Montreal != Quebec City"
    etait inerte sur cette voie).
    """
    def _job():
        try:
            v = embedder.embed(query_norm)
            store.ensure(len(v))
            store.upsert(v, {
                "sig": sig,
                "response": resp_json,
                "anchors_hard": sorted(extract_hard(query_norm)),
                "anchors_soft": sorted(extract_soft(query_raw if query_raw is not None else query_norm)),
                "ts": time.time(),
            })
        except Exception:
            pass  # index échoue → pas grave
    threading.Thread(target=_job, daemon=True).start()

# =============================================================================
# DELTA-003 : cache semantique comme SECOND NIVEAU (gateway HTTP)
# -----------------------------------------------------------------------------
# Regles :
#  - le cache EXACT reste le 1er lookup ; le semantique n'est consulte qu'APRES
#    un miss exact ;
#  - un hit semantique ne franchit JAMAIS le scope (upstream, endpoint, modele,
#    parametres de generation) ;
#  - toute requete potentiellement non rejouable (tools, tool_choice,
#    tool_calls / tool_call_id dans l'historique, contenu multimodal) est BYPASSEE ;
#  - embedder/Qdrant indisponible = miss SILENCIEUX, jamais d'echec de requete.
# =============================================================================
import hashlib  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from typing import Any, Dict, Tuple  # noqa: E402

# Champs de generation qui changent la reponse : ils font partie du scope.
_SCOPE_FIELDS = ("model", "temperature", "top_p", "seed", "response_format",
                 "max_tokens", "max_completion_tokens", "n", "stop", "logit_bias",
                 "frequency_penalty", "presence_penalty", "reasoning_effort",
                 "logprobs", "top_logprobs")


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def semantic_scope(body: Dict[str, Any], upstream: str, path: str, kind: str = "openai") -> str:
    """Signature de perimetre. Un hit semantique ne franchit JAMAIS ce scope."""
    scope = {"upstream": upstream, "path": path, "kind": kind}
    for f in _SCOPE_FIELDS:
        if isinstance(body, dict) and f in body:
            scope[f] = body[f]
    return hashlib.sha256(_canonical(scope).encode("utf-8")).hexdigest()[:32]


def semantic_eligibility(body: Dict[str, Any]) -> Tuple[bool, str]:
    """(eligible, raison). Refus EXPLICITE, jamais de bypass muet."""
    if not isinstance(body, dict):
        return False, "body invalide"
    if body.get("tools") or body.get("tool_choice") is not None:
        return False, "tools/tool_choice : reponse d'outil non rejouable"
    for m in body.get("messages") or []:
        if not isinstance(m, dict):
            continue
        if m.get("tool_calls"):
            return False, "historique avec tool_calls : lie a un etat de conversation"
        if m.get("tool_call_id"):
            return False, "historique avec tool_call_id : correlation non rejouable"
        content = m.get("content")
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") not in (None, "text"):
                    return False, "contenu multimodal : non rejouable"
    if isinstance(body.get("input"), list):
        return False, "input multi-items : non rejouable"
    return True, "eligible"


class SemanticLookup:
    """2e niveau de cache. store/embedder injectables (tests sans reseau)."""

    def __init__(self, cfg: Dict[str, Any], store=None, embedder=None):
        self.cfg = dict(cfg or {})
        self.threshold = float(self.cfg.get("semantic_threshold", 0.95))
        self.relax = float(self.cfg.get("semantic_relax_threshold", 0.97))
        self._store = store
        self._embedder = embedder
        self._embedder_failed = False

    @property
    def embedder(self):
        """Auto-discovery LM Studio : LAZY (ne doit jamais casser l'import)."""
        if self._embedder is None and not self._embedder_failed:
            try:
                self._embedder = Embedder(
                    self.cfg.get("semantic_embed_url", "http://127.0.0.1:1234"),
                    model=self.cfg.get("semantic_embed_model"))
            except Exception as e:
                self._embedder_failed = True
                logger.warning("Embedder indisponible (%s) - cache semantique desactive", e)
        return self._embedder

    @property
    def available(self) -> bool:
        if self._store is None or not getattr(self._store, "available", True):
            return False
        return self.embedder is not None

    def lookup(self, query_norm: str, query_raw: str, scope_sig: str):
        """-> (payload, score) ou None. Jamais d'exception (miss silencieux)."""
        if not self.available:
            return None
        try:
            vec = self.embedder.embed(query_norm)
            cand = self._store.search(scope_sig, vec, self.threshold)
            if not cand:
                return None
            score = float(getattr(cand, "score", 0.0))
            payload = getattr(cand, "payload", None) or {}
            if not accepts(query_norm, payload, score, self.threshold, self.relax,
                           query_soft=extract_soft(query_raw)):
                return None
            return payload, score
        except Exception as e:
            logger.warning("Semantic lookup failed (miss silencieux): %s", e)
            return None

    def index(self, query_norm: str, query_raw: str, scope_sig: str, response_json: str) -> None:
        """Indexation en tache de fond : ne bloque jamais la reponse."""
        if not self.available:
            return

        def _job():
            try:
                vec = self.embedder.embed(query_norm)
                self._store.ensure(len(vec))
                self._store.upsert(vec, {
                    "sig": scope_sig,
                    "response": response_json,
                    "model": None,
                    "anchors_hard": sorted(extract_hard(query_norm)),
                    "anchors_soft": sorted(extract_soft(query_raw)),
                    "ts": time.time(),
                    "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                })
            except Exception:
                pass  # indexation echouee -> sans grave

        threading.Thread(target=_job, daemon=True).start()


def build_semantic_lookup(cfg: Dict[str, Any], store=None, embedder=None):
    """Construit la couche semantique. None si desactive ou indisponible."""
    if not (cfg or {}).get("semantic_enabled", False):
        return None
    try:
        st = store or SemanticStore(cfg.get("qdrant_url", "http://127.0.0.1:6333"))
        if not getattr(st, "available", True):
            logger.info("Qdrant indisponible - cache semantique ignore")
            return None
        return SemanticLookup(cfg, store=st, embedder=embedder)
    except Exception as e:
        logger.warning("Cache semantique indisponible (%s) - desactive", e)
        return None
