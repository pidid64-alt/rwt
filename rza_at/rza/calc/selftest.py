"""Контрольные расчёты: примеры Вып. 13Б (ТЗ, разд. 30). Для каждого теста: исходные данные, ожидаемый результат, фактический, допуск, статус."""
from __future__ import annotations

import json
from pathlib import Path

from . import b13
from .. import paths

DATA = paths.SELFTEST_DATA / "b13_examples.json"
FUNCS = {"rnt565_two_winding": b13.rnt565_two_winding, "optimal_voltage_two_winding": b13.optimal_voltage_two_winding, "dzt11_min_current": b13.dzt11_min_current}


def run_reference_tests(path: Path | None = None) -> list[dict]:
    cases = json.loads((path or DATA).read_text(encoding="utf-8"))
    rows = []
    for c in cases:
        fn = FUNCS[c["function"]]
        try:
            out = fn(c["inputs"])
        except Exception as e:  # noqa
            rows.append({"test": c["id"], "title": c["title"], "quantity": "—", "expected": None, "actual": None, "tolerance": None, "status": "error", "message": str(e), "source": c["source"]})
            continue
        for name, (exp, tol) in c["expected"].items():
            act = out.get(name)
            ok = act is not None and abs(act - exp) <= max(abs(exp) * tol, 1e-9)
            rows.append({"test": c["id"], "title": c["title"], "quantity": name, "expected": exp, "actual": act, "tolerance": tol,
                         "deviation": (act - exp) / exp if (act is not None and exp) else None, "status": "pass" if ok else "fail", "source": c["source"], "note": c.get("note", "")})
    return rows


def summary(rows: list[dict]) -> dict:
    return {"total": len(rows), "passed": sum(1 for r in rows if r["status"] == "pass"), "failed": sum(1 for r in rows if r["status"] != "pass")}
