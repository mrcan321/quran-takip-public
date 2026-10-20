"""G2 gozluk eklentisinin ekran duzeni (tilavet-android/app/src/main/assets/g2/layout.js): node --test ile
tests/g2/layout.test.mjs; meal.bin verilirse tum mealler de denenir (G2_MEALS satiri)."""
import json
import os
import re
import shutil
import subprocess

from . import env

TEST = env.TESTS / "g2" / "layout.test.mjs"


def layout_tests(meal_bin):
    """→ ({g2_passed, g2_failures, [g2_meals, g2_max_pages, dropped_chars]}, notlar)"""
    node = shutil.which("node")
    if not node:
        return {"g2_failures": 1}, ["g2: node bulunamadi"]
    e = dict(os.environ)
    if meal_bin.exists() and meal_bin.stat().st_size > 100_000:
        e["TILAVET_MEAL_BIN"] = str(meal_bin)
    p = subprocess.run([node, "--test", str(TEST)], cwd=env.REPO, capture_output=True, text=True, encoding="utf-8", env=e)
    out = p.stdout + p.stderr
    num = lambda k: int(m.group(1)) if (m := re.search(rf"^# {k} (\d+)", out, re.M)) else 0  # noqa: E731
    passed, failed = num("pass"), num("fail")
    r = {"g2_passed": passed, "g2_failures": failed if (passed or failed) else 1}
    notes = [ln.strip() for ln in out.splitlines() if ln.startswith("not ok")][:10]
    if not (passed or failed):
        notes.append("g2: test ciktisi okunamadi: " + out[-500:])
    m = re.search(r"G2_MEALS (\{.*\})", out)
    if m:
        d = json.loads(m.group(1))
        r.update({"g2_meals": d["meals"], "g2_max_pages": d["max_pages"], "dropped_chars": d["dropped_chars"],
                  "g2_big_max_pages": d.get("big_max_pages"), "g2_big_paged": d.get("big_paged"),
                  "g2_onepage_paged": d.get("onepage_paged"), "g2_onepage_px_min": d.get("onepage_px_min"),
                  "g2_onepage_px_median": d.get("onepage_px_median"), "g2_onepage_below_20": d.get("onepage_below_20"),
                  "g2_onepage_default_paged": d.get("onepage_default_paged"),
                  "g2_onepage_default_max_pages": d.get("onepage_default_max_pages")})
        if d["dropped"]:
            notes.append(f"g2: gozluk fontunda olmayan meal karakterleri (atiliyor): {d['dropped']}")
    elif "TILAVET_MEAL_BIN" not in e:
        notes.append("g2: meal.bin yok/eksik — tum mealler denenmedi")
    return r, notes
