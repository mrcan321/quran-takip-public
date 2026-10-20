"""server/app.py process_chunk = referans state machine mi? Flask/ASR taklit edilir, TRJSON metni "ASR ciktisi" olur."""
import sys
import types
from pathlib import Path

import numpy as np

from . import env

_app = None


def load_app():
    global _app
    if _app is not None:
        return _app

    class _Stub:
        def __init__(self, *a, **k):
            pass

        def route(self, *a, **k):
            return lambda f: f

    sys.modules.setdefault("flask", types.SimpleNamespace(Flask=_Stub, render_template=None, request=None))
    sys.modules.setdefault("flask_sock", types.SimpleNamespace(Sock=_Stub))
    path = env.REPO / "server" / "app.py"
    src = path.read_text(encoding="utf-8")
    i0 = src.index("# Backend seçimi")
    i1 = src.index("\n\n\n", i0)
    src = src[:i0] + "ASR_TRANSCRIBE_FN = None\n" + src[i1:]
    src = src.replace('if __name__ == "__main__":', "if False:")
    argv = sys.argv
    sys.argv = ["app.py"]
    sys.path.insert(0, str(env.REPO / "server"))
    mod = types.ModuleType("app_under_test")
    mod.__file__ = str(path)
    try:
        exec(compile(src, str(path), "exec"), mod.__dict__)
    finally:
        sys.argv = argv
    mod.MIN_CONFIDENCE_FIRST_LOCK = env.ev.FIRST_LOCK_THRESHOLD
    mod.align_transcription = env.phone_align
    _app = mod
    return mod


def _cell_app(r):
    s = r["status"]
    if s == "matched":
        v = r["verses"][r.get("gap_filled", 0)]
        return f"M{v['surah']}:{v['ayah']}/{r['state']}"
    if s == "pending":
        return f"P{r['pending_surah']}:{r['pending_ayah']}{'?' if r.get('ambiguous') else ''}/{r['state']}"
    return {"low_confidence": "L", "too_short": "S", "silent": "-", "empty": "-"}[s] + f"/{r['state']}"


def _cell_ref(r):
    s = r["status"]
    if s == "matched":
        return f"M{r['first_surah']}:{r['first_ayah']}/{r['state']}"
    if s == "pending":
        return f"P{r['pending_surah']}:{r['pending_ayah']}{'?' if r.get('ambiguous') else ''}/{r['state']}"
    return {"low_confidence": "L", "too_short": "S", "silent": "-", "empty": "-"}[s] + f"/{r['state']}"


def compare(recsets):
    """recsets: [{dosya: parcalar}, ...] → (fark sayisi, parca sayisi, ornekler)"""
    app = load_app()
    diffs, n, examples = 0, 0, []
    for recs in recsets:
        for fn, chunks in sorted(recs.items()):
            st_a = app.SessionState()
            refs = env.run_sm(chunks)
            for k, c in enumerate(chunks):
                text = c[1] or ""
                app.ASR_TRANSCRIBE_FN = lambda _a, _t=text: _t
                ra = app.process_chunk(np.full(1600, c[0] or 0.0, dtype=np.float64), k, st_a, 0.0)
                n += 1
                if _cell_app(ra) != _cell_ref(refs[k]):
                    diffs += 1
                    if len(examples) < 10:
                        examples.append(f"{fn} #{k}: app={_cell_app(ra)} ref={_cell_ref(refs[k])} metin={text}")
    return diffs, n, examples
