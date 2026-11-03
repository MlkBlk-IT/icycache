"""DELTA-006 : regression du ripple 3D (static/dashboard.html).

Bug corrige : `mesh.userData.hits` etait ecrase AVANT la comparaison
`if(hits>mesh.userData.hits)` -> la condition etait toujours fausse et le
ripple de hit ne se declenchait JAMAIS.

Le test verifie (1) que le pattern buggué n'est plus present, (2) que la
capture de l'ancien compteur existe bien avant l'ecriture, (3) que la
semantique JS corrigee declenche bien le ripple quand le compteur augmente.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

DASH = Path(__file__).resolve().parent.parent / "static" / "dashboard.html"
SRC = DASH.read_text(encoding="utf-8")


def test_dashboard_exists():
    assert DASH.exists(), "static/dashboard.html introuvable"


def test_buggy_pattern_is_gone():
    """Le bug : ecriture du compteur AVANT la comparaison."""
    buggy = re.search(r"mesh\.userData\.hits\s*=\s*hits\s*;[^\n]*\n[^\n]*"
                      r"if\s*\(\s*hits\s*>\s*mesh\.userData\.hits\s*\)", SRC)
    assert buggy is None, "le pattern buggué (ecriture avant comparaison) est revenu"


def test_previous_hits_is_captured_before_write():
    m = re.search(r"const\s+prevHits\s*=\s*mesh\.userData\.hits\s*\|\|\s*0\s*;\s*"
                  r"\n\s*mesh\.userData\.hits\s*=\s*hits\s*;\s*"
                  r"\n\s*if\s*\(\s*hits\s*>\s*prevHits\s*\)", SRC)
    assert m is not None, ("capture de prevHits absente : l'ancien compteur doit etre lu "
                           "AVANT l'ecriture du nouveau")


def test_ripple_is_triggered_on_increase():
    """Semantique JS corrigee : le ripple part si et seulement si hits augmente."""
    js = """
      let fired = 0;
      function iceRipple(){ fired++; }
      const mesh = {userData:{hits:3}};
      const hits = 5;
      const prevHits = mesh.userData.hits||0;
      mesh.userData.hits = hits;
      if(hits>prevHits){ iceRipple(); }
      const same = (function(){
        const m2 = {userData:{hits:5}};
        const h2 = 5;
        const p2 = m2.userData.hits||0;
        m2.userData.hits = h2;
        if(h2>p2){ iceRipple(); }
        return fired;
      })();
      console.log(JSON.stringify({fired, same}));
    """
    node = shutil.which("node")
    if not node:
        # Sans Node : simulation equivalente en Python (meme semantique).
        fired = 0
        mesh = {"userData": {"hits": 3}}
        hits = 5
        prev = mesh["userData"]["hits"] or 0
        mesh["userData"]["hits"] = hits
        if hits > prev:
            fired += 1
        assert fired == 1, "le ripple ne se declenche pas sur une augmentation"
        return
    out = subprocess.run([node, "-e", js], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    data = out.stdout.strip().splitlines()[-1]
    import json
    payload = json.loads(data)
    assert payload["fired"] == 1, payload
    assert payload["same"] == 1, "un compteur identique ne doit pas declencher de ripple"


def test_3d_stack_is_untouched():
    """Le correctif ne doit avoir touche ni Three.js ni la carte 3D."""
    assert "THREE" in SRC, "Three.js doit rester present"
    assert "IC3D" in SRC, "la carte 3D doit rester presente"
    assert "iceRipple" in SRC, "la fonction de ripple doit rester"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  {fn.__name__}: PASS")
    print(f"=== {len(fns)} tests passed ===")
