"""Оркестратор расчёта: проверка данных → универсальные расчёты функций → карты уставок терминалов → статусы проекта."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from ..errors import Status
from ..model.project import Project, now_iso
from ..setpoints import Card, apply_terminal, statuses
from ..terminals.registry import terminal_registry
from . import functions as F
from .context import CalcContext
from .results import FunctionResult
from .validation import Issue, has_errors, validate


@dataclass
class RunResult:
    project_id: str
    version: str
    ts: str
    issues: list
    results: dict = field(default_factory=dict)
    cards: dict = field(default_factory=dict)
    statuses: list = field(default_factory=list)
    blocked: bool = False
    seconds: float = 0.0
    ctx: CalcContext | None = None

    def to_dict(self) -> dict:
        return {"project_id": self.project_id, "version": self.version, "ts": self.ts, "blocked": self.blocked, "seconds": round(self.seconds, 3),
                "issues": [i.to_dict() for i in self.issues], "results": {k: v.to_dict() for k, v in self.results.items()},
                "cards": {k: v.to_dict() for k, v in self.cards.items()}, "statuses": self.statuses}


def run_all(project: Project, terminal_ids: list[str] | None = None, policy: str | None = None, functions: list[str] | None = None) -> RunResult:
    t0 = time.time()
    project.ensure_modes()
    issues = validate(project)
    rr = RunResult(project.meta.id, project.meta.version, now_iso(), issues)
    if has_errors(issues):
        rr.blocked = True
        rr.statuses = statuses(issues, {}, {})
        rr.seconds = time.time() - t0
        return rr
    ctx = CalcContext(project)
    rr.ctx = ctx
    for fid in (functions or F.all_ids()):
        try:
            rr.results[fid] = F.get(fid).calculate(ctx)
        except Exception as e:  # noqa
            fr = FunctionResult(fid, fid)
            fr.missing.append(f"Ошибка расчёта функции {fid}: {e}")
            rr.results[fid] = fr
    reg = terminal_registry()
    assigns = project.terminals
    if terminal_ids:
        assigns = [a for a in assigns if a.terminal_id in terminal_ids] or []
        for tid in terminal_ids:
            if not any(a.terminal_id == tid for a in assigns) and reg.has(tid):
                from ..model.project import TerminalAssign
                assigns.append(TerminalAssign(tid, "", "", [f for f in F.all_ids() if reg.get(tid).supports(f)], {}, ""))
    for a in assigns:
        if not reg.has(a.terminal_id):
            continue
        prof = reg.get(a.terminal_id)
        rr.cards[a.terminal_id] = apply_terminal(ctx, rr.results, prof, a.variant, a.functions or None, policy)
    rr.statuses = statuses(issues, rr.results, rr.cards)
    rr.seconds = time.time() - t0
    return rr
