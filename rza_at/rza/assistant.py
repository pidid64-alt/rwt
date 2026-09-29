"""Инженерный ассистент (правила, без внешней LLM).

Возможности (ТЗ, разд. 24): объяснять расчёт; находить ошибки и нехватку исходных данных; объяснять выбранную уставку;
сравнивать Выпуск 13Б с современной реализацией; проверять логическую согласованность; формировать комментарии; анализировать результаты проверок.

Ограничения: ассистент НЕ утверждает уставки. Каждая рекомендация содержит основание, формулу, исходные данные, источник и —
при недостатке данных — предупреждение. Все выводы формируются из трассы расчёта и результатов проверок (детерминированно, проверяемо).
"""
from __future__ import annotations

from .calc import b13
from .errors import Status

DISCLAIMER = "Комментарий ассистента не является утверждением уставки. Уставки утверждаются специалистами службы РЗА (проверяющий, утверждающий)."


def _fmt(v, unit=""):
    if isinstance(v, float):
        s = f"{v:.4g}".replace(".", ",")
    else:
        s = str(v)
    return f"{s} {unit}".strip()


def explain_param(run, function_id: str, key: str, terminal_id: str | None = None) -> dict:
    fr = run.results.get(function_id)
    pr = fr.param(key) if fr else None
    if pr is None:
        return {"ok": False, "message": "Параметр не найден"}
    steps = []
    for st in (pr.trace.steps if pr.trace else []):
        if st.kind == "calc":
            steps.append({"title": st.title, "formula": st.display, "substituted": st.substituted, "source": st.source})
    binding = None
    lowers = [c for c in pr.criteria if c.kind == "lower" and c.value is not None]
    uppers = [c for c in pr.criteria if c.kind == "upper" and c.value is not None]
    if lowers:
        binding = max(lowers, key=lambda c: c.value)
    elif uppers:
        binding = min(uppers, key=lambda c: c.value)
    lines = []
    lines.append(f"Уставка «{pr.title}» определяется как {'наибольшая из нижних границ' if lowers else 'наименьшая из верхних границ' if uppers else 'инженерный выбор'} по критериям расчёта.")
    if binding is not None:
        lines.append(f"Определяющий критерий: {binding.title} — {_fmt(binding.value, pr.unit)}" + (f" (основание: {binding.ref})" if binding.ref else "") + (f"; наихудший случай {binding.note}" if binding.note else "") + ".")
    if pr.lower is not None and pr.upper is not None:
        lines.append(f"Допустимый интервал по критериям: {_fmt(pr.lower, pr.unit)} … {_fmt(pr.upper, pr.unit)}" + ("" if pr.lower <= pr.upper else " — интервал пуст: критерии несовместимы, требуется пересмотр схемы защиты / данных") + ".")
    out = {"ok": True, "title": pr.title, "status": pr.status.value, "calc": pr.calc, "unit": pr.unit, "text": lines, "steps": steps, "criteria": [c.to_dict() for c in pr.criteria],
           "warnings": [], "disclaimer": DISCLAIMER}
    if pr.status == Status.MISSING or pr.calc is None:
        out["warnings"].append("Недостаточно исходных данных для расчёта параметра: " + (pr.reason or ""))
    card = run.cards.get(terminal_id) if terminal_id else None
    if card:
        row = next((r for r in card.rows if r.pfm_key == pr.key), None)
        if row and row.supported and row.accepted is not None:
            out["terminal"] = {"terminal": card.profile.label, "param": row.param_name, "range": [row.min, row.max], "step": row.step, "unit": row.unit, "accepted": row.accepted,
                               "dev_calc": row.dev_calc, "deviation_rel": row.deviation_rel, "reason": row.reason, "source": row.source,
                               "profile_status": card.profile.status_label if hasattr(card.profile, "status_label") else card.profile.status}
            lines.append(f"Перевод в параметры терминала «{card.profile.label}»: расчёт {_fmt(row.dev_calc, row.unit)} → принято {_fmt(row.accepted, row.unit)} (диапазон {row.min} … {row.max}, шаг {row.step}). {row.reason}")
            if card.profile.status != "verified":
                out["warnings"].append(f"Профиль терминала не верифицирован по руководству (статус «{card.profile.status}») — диапазоны/шаги требуют сверки.")
            if row.step_verified is False:
                out["warnings"].append("Шаг уставки в руководстве не указан явно и принят по числу десятичных знаков диапазона — сверьте с DIGSI/руководством.")
    if pr.meta.get("b13"):
        out["b13"] = pr.meta["b13"]
    return out


def review_project(project, run) -> list[dict]:
    """Проверка логической согласованности и полноты: список замечаний с основанием и источником."""
    out = []

    def add(sev, title, basis, formula="", inputs=None, source="", warn=""):
        out.append({"severity": sev, "title": title, "basis": basis, "formula": formula, "inputs": inputs or [], "source": source, "warning": warn})

    for i in run.issues:
        add({"error": "error", "warning": "warning", "info": "info"}[i.level], i.message, f"Контроль исходных данных ({i.code})", inputs=[i.path], warn=i.hint)
    for fid, fr in run.results.items():
        for m in fr.missing:
            add("missing", f"{fid}: {m}", "Расчёт защиты выполнен не полностью", warn="Недостаточно исходных данных — результат неполный")
        for w in fr.warnings:
            add("warning", f"{fid}: {w}", "Предупреждение расчётного модуля")
        for c in fr.checks:
            if c.status in (Status.FAIL, Status.CHECK):
                add("error" if c.status == Status.FAIL else "warning", f"{c.title}: {c.reason}", f"Проверка «{c.kind}»",
                    formula=(c.trace.steps[-1].substituted if c.trace and c.trace.steps else ""), inputs=[f"порог: {c.threshold}"], source="; ".join(c.refs))
    for tid, card in run.cards.items():
        if card.profile.status != "verified":
            add("warning", f"Профиль терминала «{card.profile.label}» не верифицирован ({card.profile.status})", "Диапазоны и шаги не сверены с руководством", source="Модуль «База устройств»",
                warn="Экспорт окончательной карты уставок будет заблокирован до верификации профиля")
        for r in card.rows:
            if r.status == Status.NA and r.supported is False and r.function not in ("Объект",):
                add("warning", f"{r.title}: {r.reason}", f"Терминал «{card.profile.label}»", warn="Функция/ступень не реализована в выбранном терминале — назначьте другое устройство или согласуйте иное решение")
    assigned = {f for a in project.terminals for f in a.functions}
    for fid in run.results:
        if fid not in assigned:
            add("warning", f"Функция {fid} не назначена ни одному терминалу", "Логическая согласованность проекта", warn="Уставки функции не попадут в карту уставок")
    for ln in project.network.lines:
        if not (ln.prot.dist or ln.prot.i0 or ln.prot.mtz or ln.prot.neg):
            add("warning", f"Для линии «{ln.name}» не заданы уставки защит", "Согласование по чувствительности и времени требует уставок смежных защит", warn="Недостаточно данных для согласования")
    out.append({"severity": "info", "title": "Ограничение ассистента", "basis": DISCLAIMER, "formula": "", "inputs": [], "source": "", "warning": ""})
    return out


def compare_13b(project, run) -> list[dict]:
    """Режим «13Б vs современная РЗА»: для каждого физического критерия — 13Б, современная реализация, числа проекта."""
    res = []
    fr = run.results.get("87T")
    for c in b13.criteria_table():
        item = dict(c)
        item["project_values"] = []
        if fr:
            for pid in c["modern"].get("params", []):
                pr = fr.param(pid)
                if pr is not None and pr.calc is not None:
                    item["project_values"].append({"param": pr.title, "pfm": pid, "calc": pr.calc, "unit": pr.unit, "lower": pr.lower, "upper": pr.upper})
        res.append(item)
    return res
