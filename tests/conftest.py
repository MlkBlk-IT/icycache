"""Isole les scripts de test (non-pytest) de la collecte pytest.

Ces 4 fichiers sont des SCRIPTS et non des modules pytest :
les collecter casse la suite entiere.

- tests/test_cacheforge.py, tests/test_cacheforge_ext.py
    Lancés par tests/run_isolated.py (DB temporaire + faux upstream :8191).
    A l'import ils font sys.exit() si CF_BASE est absent -> INTERNALERROR.
- tests/test_prefix_proxy.py
    Script avec os._exit(0|1) en fin de module -> il TUE pytest en silence
    (code de sortie 1, aucune trace, tampon stdout perdu).
- tests/granite_live_test.py
    Benchmark LIVE contre LM Studio (http://127.0.0.1:8080). Matche le motif
    *_test.py -> collecte par defaut -> trafic reel + appel LLM au moment de
    la collecte.

Execution isolee (scripts) :
    venv\\Scripts\\python.exe tests\\run_isolated.py
    venv\\Scripts\\python.exe tests\\test_prefix_proxy.py
"""
collect_ignore_glob = [
    "test_cacheforge*.py",
    "test_prefix_proxy.py",
    "granite_live_test.py",
]
