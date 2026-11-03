# IcyCache — Release notes

> This file is the release annotation for each published version. It is maintained in English;
> the rest of the repository (code, comments, internal docs) is written in French.

---

## v0.4.0 — 2026-11-03

**The test suite runs again, and the semantic cache finally works in every major language.**

### Added

- **A multilingual anchor engine (`src/icy_lang.py`) driven by 24 language profiles
  (`config/lang_profiles.json`).** The semantic cache needs "soft anchors" (named entities) to tell
  *"a DNS cache"* from *"a web cache"*. Casing only marks an entity in some languages, so the
  engine now:
  - tokenises **per script** (Latin / CJK / Cyrillic / Arabic / Devanagari / Bengali) — without
    this, `DNSキャッシュ` was a single token and the acronym was invisible;
  - detects the language (script first, then distinct stop-word hits — at least two hits **and** a
    lead over the second candidate, otherwise "unknown");
  - applies three casing models: `sentence` (en, fr, es, pt, it, vi, tr — a capitalised word that
    is not sentence-initial is an entity), `noun` (de, nl, pl, sv, da, cs, hu, fi, no, ru, uk —
    **all** nouns are capitalised, so they are filtered against a common-word list), `none`
    (zh, ja, ko, ar, hi, bn — no casing, only Latin acronyms and CamelCase count).

  **No language is hardcoded in the source any more** — adding one is a single JSON key.
- **Per-language soft anchors on the MCP path.** `mcp_server.py` compared the *normalised* prompt,
  which is lower-case and therefore carried **zero** soft anchors: the *"Montreal ≠ Quebec City"*
  guard was completely inert there. The raw text is now used on both the lookup and the indexing
  side.
- **`tests/conftest.py`** isolates the four test *scripts* from pytest collection, and
  `pyproject.toml` gains a `[tool.pytest.ini_options]` section (`testpaths`, `python_files`,
  `asyncio_mode`).

### Fixed

- **`pytest tests/` no longer dies silently.** It exited with code 1 and **zero** output: three test
  files are scripts, not pytest modules — `test_cacheforge.py` and `test_cacheforge_ext.py` call
  `sys.exit()` at import when `CF_BASE` is missing, and `test_prefix_proxy.py` ends with
  `os._exit()`, which killed the whole pytest process. `granite_live_test.py` matched `*_test.py`
  and was collected, starting a live LM Studio benchmark during collection.
- **The two async tests could never pass.** `pytest-asyncio` was missing from the `dev` extra and
  from the virtualenv, so `tests/test_upstream_recovery.py` failed with *"async def functions are
  not natively supported"*.
- **The French word "plus" was corrupting every prompt.** `normalize_numbers()` replaced
  `" plus "` with `"+"` everywhere: *"Donne-moi plus de détails"* became *"Donne-moi+de détails"*.
  It changed the exact-cache key **and** the embedding input. Operators are now converted only
  between two numeric operands, in a single shared implementation used by `icy_normalize.py` and
  `icy_semantic.py` (the two copies had drifted apart).
- **The path anchor swallowed every slash.** `(?:\./|/)[^\s]+` matched `"A/B"` → `"/b"` and
  `"12/24"` → `"/24"`, so two paraphrases could never share their hard anchors and the semantic
  cache could never answer. A path now requires a drive root, a relative path, or at least two
  POSIX segments.
- **Named entities were detected by capitalisation alone**, which in French marks a sentence
  start, not an entity. `extract_soft()` now uses acronyms, internal CamelCase and
  capitalisation-outside-sentence-start, filtered per language.

### Changed

- The `RELAX` acceptance path now requires **shared grounding** (identical hard anchors, or at
  least one common strong entity). Without it, *"Montreal"* and *"Quebec City"* were accepted at
  0.99 similarity.
- Version bumped to 0.4.0 — `pyproject.toml`, `package.json`, the README badge and
  `docs/INSTALL.md` now match this release.

### ⚠ Breaking

- **The cache key format changed.** The entries already in `db/cache.db` were written with the
  old normalisation and will never be read again. They expire by TTL (30 days) or can be dropped
  with `DELETE FROM cache; VACUUM;`.

---

## v0.3.2 — 2026-10-26

**Prepared for publication — the first registry publish is still pending.**

### Added

- **The packages are built, tagged and ready to publish.** The repository, the PyPI distribution and
  the npm package all carry the same name — `icycache` — and the README now gives the registry
  install commands (`uv tool install icycache`, `pip install icycache`, `npx -y icycache`) with links
  to both registry pages. Those commands return a 404 until the first publish happens; install from
  source until then.
- **PyPI publication will use trusted publishing (OIDC).** The `Publish` workflow mints a short-lived
  token from the GitHub Actions identity: no PyPI API token is stored on any machine.

### Fixed

- **The README no longer claims the package is unpublished.** v0.3.1 documented the commands as
  "not published yet"; they now resolve to the real registries.
- `docs/INSTALL.md` pointed at `dist/icycache-0.2.0-py3-none-any.whl` — the current version is 0.3.2.

### Changed

- Version bumped to 0.3.2 — `pyproject.toml` and `package.json` now match the `v0.3.2` tag and this
  release.

### Not changed

No code change: the gateway, the MCP layer, the semantic cache and the normalization engine are
exactly as shipped in v0.3.0.

---

## v0.3.1 — 2026-10-26

**The install instructions were not true yet.**

### Fixed

- **Nothing was published on PyPI or npm.** `pip install icycache` and `npx -y icycache-mcp` both
  returned a 404 while the README presented them as working commands. The README now says so
  explicitly and gives the install-from-source command that works today:
  `pip install "icycache @ git+https://github.com/MlkBlk-IT/icycache.git"`.
- Unlike `loom-mcp` (which belongs to other projects on both registries), the names `icycache` and
  `icycache-mcp` are **free** on PyPI and npm — so these commands are the final ones and will work
  as written once the first publish happens.

### Changed

- Version bumped to 0.3.1 — `pyproject.toml` and `package.json` now match the `v0.3.1` tag and this release.
- The npm package is named **`icycache`**, the same name as the repository. It exposes two binaries:
  `icycache` (the CLI: `serve` / `mcp` / `doctor`) and `icycache-mcp` (the MCP server on stdio), so
  `npx -y icycache` and `npx -y -p icycache icycache-mcp` both resolve to this project. The PyPI
  distribution stays **`icycache`** too (`pip install icycache`).

### Not changed

No code change: the gateway, the MCP layer, the semantic cache and the normalization engine are
exactly as shipped in v0.3.0.

---

## v0.3.0 — 2026-10-26

**DELTA-002** — one correction pass over the request path, covering BUG-001, BUG-002 and DELTA-001.

### Added
- **Resilient upstream client** (`src/upstream_client.py`) — one client pool per base URL, with
  drain → recycle → retry. Fixes **BUG-001** (gateway stuck returning `502` after a `400`).
- **Opt-in semantic cache** (`src/icy_semantic.py`, `config/semantic_cache.json`) — embeddings +
  Qdrant store, with a silent miss when the embedder or Qdrant is unavailable.
- **Tool registry** (`config/tools_registry.json`) — the 100 verified MCP tool anchors from
  DELTA-001, asserted at startup (`total == 100`).
- **Number normalization** — `"two plus two"` → `2+2`. 11 new rules: **1111 → 1122**.
- **Tests** — `tests/test_semantic_cache.py`, `tests/test_upstream_recovery.py`, `tests/test_anchors.py`.
- **Docs** — `docs/BUG-001-502-stuck-after-400.md`, `docs/BUG-002-no-semantic-cache.md`,
  `docs/DELTA-001-tool-proxy-top100.md`, `docs/DELTA-002-unified-fix.md`.

### Changed
- `src/mcp_server.py` — loads the semantic cache config and the tools registry, wires the
  resilient upstream pool.
- `src/prefix_proxy.py` — recycles the httpx client and retries once on an upstream error.
- `src/icy_normalize.py` — number-word → digit conversion, before accents/punctuation stripping.
- `config/normalization_rules.json` — 11 rules added, `total_rules` metadata corrected to 1122.
- `README.md` — rewritten in English, counts aligned with the code (1122 rules, 18 upstreams,
  11 MCP tools), semantic-cache status documented as opt-in.

### Removed
- Legacy pre-rename artefacts: `CacheForge_Project_Documentation.docx`, `start_cacheforge.ps1`,
  `_loop3d_new.js`, `tools/apply_fixes*.py`, `tools/add_live_sse.py`, `tools/prune_legacy_2d.py`,
  `tools/read_live_capture.py`.
- Stale dashboard captures and the legacy 2D canvas assets under `static/`.

### Honest status
- The **semantic cache is implemented but disabled by default** (`semantic_enabled: false`).
  Turning it on requires an embedding endpoint (LM Studio on `:1234`) and a running Qdrant.
- The gateway still refuses to start if another service already holds port `8080`.

---

## v0.2.0 — 2026-10-24

### Added
- New universal gateway `src/server.py` (port 8080) with the shared core `src/icy_core.py`.
- Standalone normalization engine `src/icy_normalize.py`, cache store `src/icy_cache_store.py`.
- MCP facade `src/mcp_gateway.py`, stdio bridge `src/mcp_stdio_bridge.py`.
- MCP tool proxy `src/tool_proxy.py`, upstream helpers `src/upstream_utils.py`.
- Isolated gateway tests `tests/test_gateway.py`.
- `tools/` scripts, packaging (`pyproject.toml`, `package.json`), gateway config
  `config/icycache.gateway.json`, autostart and update scripts.

### Changed
- `src/server.py` — MCP exposure + documentation (+350 lines).
- `README.md` — rebrand and documentation.
- `static/dashboard.html` — dashboard redesign (live nodes, electric gauge, cyberpunk palette).
- `tray.py`, `.ps1` scripts, `requirements.txt`, `config/icycache.json`.

### Deliberately excluded
- PNG captures (`static/*.png`) and the `backup_pre_gateway/` folder — local artefacts, not versioned.
