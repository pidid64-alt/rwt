"""Сравнение терминалов: один расчёт → несколько устройств (без автоматического выбора «лучшего»)."""
from __future__ import annotations

from .calc import functions as F
from .errors import Status
from .setpoints import apply_terminal
from .terminals.registry import terminal_registry


def compare_matrix(project, run, terminal_ids: list[str]) -> dict:
    """Матрица: параметр | расчёт | устройство A | устройство B …"""
    reg = terminal_registry()
    cards = {}
    for tid in terminal_ids:
        if tid in run.cards:
            cards[tid] = run.cards[tid]
        elif reg.has(tid) and run.ctx is not None:
            prof = reg.get(tid)
            cards[tid] = apply_terminal(run.ctx, run.results, prof, "", None, None)
    header = ["Функция", "Параметр", "Расчёт"] + [c.profile.label for c in cards.values()]
    rows, rows_text, statuses = [], [], []
    for fid, fr in run.results.items():
        for pr in fr.params:
            if pr.fixed and pr.pfm_id.endswith(("Delay",)):
                continue
            cells, texts, sts = [], [], []
            for tid, card in cards.items():
                r = next((x for x in card.rows if x.pfm_key == pr.key), None)
                if r is None or not r.supported:
                    cells.append({"text": "—", "status": "na", "note": r.reason if r else "нет в карте"})
                    texts.append("не реализуется")
                    sts.append("na")
                else:
                    cells.append({"accepted": r.accepted, "unit": r.unit, "param": r.param_name, "status": r.status.value, "note": r.reason[:220], "dev_calc": r.dev_calc,
                                  "range": [r.min, r.max], "step": r.step})
                    a = r.accepted
                    texts.append(f"{a:g}" if isinstance(a, float) else str(a))
                    texts[-1] += f" {r.unit}" if r.unit else ""
                    sts.append(r.status.value)
            rows.append({"function": fid, "key": pr.key, "title": pr.title, "calc": pr.calc, "unit": pr.unit, "cells": cells})
            cv = pr.calc
            ctext = (f"{cv:.4g}" if isinstance(cv, float) else str(cv)) + (f" {pr.unit}" if pr.unit else "")
            rows_text.append([fid, pr.title, ctext] + texts)
            from .errors import worst
            statuses.append(worst([Status(s) for s in sts if s != "na"] or [Status.NA]).value)
    return {"header": header, "rows": rows, "rows_text": rows_text, "row_status": statuses, "terminals": [{"id": tid, "label": c.profile.label, "status": c.profile.status, "card_status": c.status.value} for tid, c in cards.items()]}
