"""Модель отчёта (форматонезависимая) и построители 7 видов отчётов ТЗ (разд. 33)."""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime

from ..calc.shortcircuit import FAULT_TYPES, KZ
from ..errors import Status
from ..model.autotransformer import SIDE_RU, tap_states
from ..model.project import Project

STATUS_RU = {"ok": "Выполнено", "check": "Требуется проверка", "fail": "НЕ ВЫПОЛНЕНО", "missing": "Не хватает данных", "out_of_range": "ВНЕ ДИАПАЗОНА ТЕРМИНАЛА", "na": "Не применимо"}
KINDS = {
    "calc": "Расчёт уставок (полный инженерный расчёт)",
    "card": "Карта уставок",
    "kz": "Расчёт токов КЗ",
    "sens": "Проверка чувствительности",
    "selectivity": "Проверка селективности",
    "compare": "Сравнение терминалов",
    "changes": "Протокол изменений",
}


@dataclass
class Block:
    kind: str                   # h1 h2 h3 p note table image pagebreak
    text: str = ""
    header: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    row_status: list = field(default_factory=list)
    widths: list = field(default_factory=list)
    data: bytes = b""
    caption: str = ""


@dataclass
class Doc:
    title: str
    subtitle: str = ""
    meta: list = field(default_factory=list)          # [(ключ, значение)]
    blocks: list = field(default_factory=list)
    draft: bool = False
    draft_reasons: list = field(default_factory=list)
    kind: str = ""

    def h(self, level: int, text: str):
        self.blocks.append(Block(f"h{level}", text))

    def p(self, text: str):
        self.blocks.append(Block("p", text))

    def note(self, text: str):
        self.blocks.append(Block("note", text))

    def table(self, header, rows, row_status=None, widths=None, caption=""):
        self.blocks.append(Block("table", header=header, rows=[[("" if c is None else c) for c in r] for r in rows], row_status=row_status or [None] * len(rows), widths=widths or [], caption=caption))

    def image(self, data: bytes, caption: str = ""):
        self.blocks.append(Block("image", data=data, caption=caption))

    def pagebreak(self):
        self.blocks.append(Block("pagebreak"))


def num(v, d=4):
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "вкл" if v else "выкл"
    if isinstance(v, (int, float)):
        s = f"{v:.{d}g}" if abs(v) < 1e5 else f"{v:.0f}"
        return s.replace(".", ",")
    return str(v)


def export_guard(project: Project, run, terminal_id: str | None = None) -> dict:
    """Полный контроль проекта перед экспортом окончательной карты уставок (ТЗ, разд. 41)."""
    reasons = []
    if run is None:
        return {"final_allowed": False, "reasons": ["Расчёт не выполнен"]}
    if run.blocked:
        reasons.append("Расчёт заблокирован ошибками исходных данных")
    for i in run.issues:
        if i.level == "error":
            reasons.append(f"Ошибка данных: {i.message}")
    for fid, fr in run.results.items():
        for m in fr.missing:
            reasons.append(f"{fid}: не хватает данных — {m}")
        for p in fr.params:
            if p.status == Status.FAIL and not p.fixed:
                reasons.append(f"{fid}: {p.title}: {p.reason}")
    cards = [run.cards[terminal_id]] if terminal_id and terminal_id in run.cards else list(run.cards.values())
    for c in cards:
        if c.profile.status != "verified":
            reasons.append(f"Профиль терминала «{c.profile.label}» не верифицирован по руководству ({c.profile.status})")
        for r in c.rows:
            if r.status in (Status.FAIL, Status.OUT_OF_RANGE):
                reasons.append(f"{c.profile.label}: {r.title}: {r.status.label}")
            if r.status == Status.MISSING:
                reasons.append(f"{c.profile.label}: {r.title}: не хватает данных")
        for fid, cs in c.checks.items():
            for k in cs:
                if k.status in (Status.FAIL, Status.MISSING):
                    reasons.append(f"{fid}: {k.title}: {k.reason}")
    seen, out = set(), []
    for r in reasons:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return {"final_allowed": not out, "reasons": out}


def _meta(project: Project, run) -> list:
    m = project.meta
    return [("Проект", m.name), ("Объект", m.substation), ("Версия", f"{m.version} от {m.date} (предыдущая: {m.prev_version or '—'})"), ("Причина версии", m.reason),
            ("Автор", m.author or "—"), ("Проверяющий", m.reviewer or "—"), ("Утверждающий", m.approver or "—"), ("Статус проекта", {"draft": "Черновик", "review": "На проверке", "approved": "Утверждён"}.get(m.status, m.status)),
            ("Дата формирования", datetime.now().strftime("%Y-%m-%d %H:%M")), ("Формат уставок", "Уровень 1 — универсальный расчёт (PFM); уровень 2 — адаптер терминала")]


def _passport(doc: Doc, project: Project):
    tr = project.transformer
    doc.h(2, "Паспорт автотрансформатора")
    doc.table(["Параметр", "Значение"], [
        ["Тип", f"{tr.type_name} ({tr.manufacturer})"], ["Заводской №, год", f"{tr.serial_number}, {tr.year or '—'}"], ["Мощность S_ном (проходная), МВА", num(tr.s_nom_mva)],
        ["Типовая мощность S_тип, МВА", num(tr.s_typ())], ["Группа соединения", tr.group_label()], ["Частота, Гц", num(tr.frequency_hz)],
        ["Схема заземления", tr.grounding_scheme], ["Данные ТТ", "см. таблицу ТТ"], ["Встроенные защиты", ", ".join(tr.builtin_protections)]])
    rows = [[s, SIDE_RU[s], num(tr.w(s).u_nom_kv), num(tr.s_winding(s)), num(tr.i_nom(s, tr.s_winding(s)), 5), tr.w(s).connection, tr.w(s).clock] for s in tr.sides()]
    doc.table(["Сторона", "", "U_ном, кВ", "S обмотки, МВА", "I_ном, А", "Соединение", "Часы"], rows)
    o = tr.oltc
    if o.present:
        doc.p(f"РПН: сторона {o.side}, {o.location}, ±{o.n_steps_plus}×{o.step_pct:g} %, номинальное положение №{o.nominal_position}, используемые положения {o.pos_min()}…{o.pos_max()}.")
        rows = []
        for ts in tap_states(tr):
            rows.append([ts.label(), *[num(ts.u_kv[s]) for s in tr.sides()], *[num(ts.uk_pct.get(p)) for p in ("HV_MV", "HV_LV", "MV_LV") if p in tr.uk], *[num(v, 4) for v in ts.x_ohm.values()]])
        pairs = [p for p in ("HV_MV", "HV_LV", "MV_LV") if p in tr.uk]
        doc.table(["Положение РПН", *[f"U {s}, кВ" for s in tr.sides()], *[f"u_к {p}, %" for p in pairs], *[f"X луча {k}, Ом(ВН)" for k in tap_states(tr)[0].x_ohm]], rows)


def _cts(doc: Doc, project: Project):
    doc.h(2, "Трансформаторы тока")
    doc.table(["ТТ", "Сторона", "Расположение", "K_T", "Класс", "K_ном", "S_ном/S_факт, ВА", "K_дейст", "Защиты"],
              [[c.id, c.side, c.location, f"{c.i1_a:g}/{c.i2_a:g}", c.protection_class, num(c.alf), f"{c.s_nom_va:g}/{c.s_fact_va:g}", num(c.alf_actual(), 3), ", ".join(c.protections)] for c in project.cts])


def _network(doc: Doc, project: Project):
    net = project.network
    doc.h(2, "Сеть и режимы")
    rows = []
    for s in net.sources:
        for st, z in (("макс", s.max), ("мин", s.min)):
            rows.append([s.id, s.name, s.side, st, num(z.r1), num(z.x1), num(z.r0), num(z.x0)])
    doc.table(["Источник", "Название", "Сторона", "Режим", "R1, Ом", "X1, Ом", "R0, Ом", "X0, Ом"], rows)
    if net.lines:
        doc.table(["Линия", "Сторона", "Длина, км", "Z1, Ом", "Z0, Ом", "Подпитка с противоположного конца"], [[l.name, l.side, num(l.length_km), num(abs(l.z1())), num(abs(l.z0())), "есть" if l.remote_source else "нет"] for l in net.lines])
    doc.table(["Режим", "Название", "Роли", "Источники", "Параллельный АТ", "РПН", "Нагрузка"], [[m.id, m.name, ", ".join(m.roles), ", ".join(f"{k}:{v}" for k, v in m.sources.items()), "да" if m.parallel_at else "нет", m.tap or "min/nom/max", num(m.load_factor)] for m in project.modes])


def kz_rows(project: Project, full: bool = False) -> tuple[list, list]:
    kz = KZ(project)
    sides = project.transformer.sides()
    header = ["Режим", "РПН", "Точка КЗ", "Вид КЗ", "I_КЗ, А", *[f"I_{s} (ТТ), А" for s in sides], "I_нейтрали, А", "Z1, Ом", "Z0, Ом"]
    rows = []
    for m in project.modes:
        if not full and not ({"max_kz", "min_kz"} & set(m.roles)):
            continue
        for tk in kz.tap_keys_for(m):
            for nd in sides:
                for ft in FAULT_TYPES:
                    try:
                        r = kz.fault(m.id, tk, nd, ft)
                    except Exception:
                        continue
                    rows.append([m.id, tk, f"шины {nd}", FAULT_TYPES[ft], num(r.i_fault_abs(), 5), *[num(r.side_i_max(s), 5) for s in sides], num(abs(r.neutral_3i0), 5),
                                 num(abs(r.z_seq[0]), 4), num(abs(r.z_seq[2]), 4) if not r.flags["z0_inf"] else "∞"])
    return header, rows


def _checks_table(doc: Doc, checks: list, title: str):
    if not checks:
        return
    doc.h(3, title)
    doc.table(["Проверка", "Значение", "Норматив", "Ср.", "Статус", "Обоснование / наихудший случай", "Источник"],
              [[c.title, num(c.value, 4), num(c.threshold, 4), c.cmp, STATUS_RU[c.status.value], c.reason, "; ".join(c.refs)] for c in checks], [c.status.value for c in checks],
              widths=[5, 1.3, 1.3, 0.6, 1.8, 6, 3])


def _trace_block(doc: Doc, pr):
    if not pr.trace:
        return
    lines = []
    for st in pr.trace.steps:
        if st.kind == "calc":
            lines.append([st.title, st.display, st.substituted, st.source])
        elif st.kind == "choice":
            alts = "; ".join(f"{o.get('short', o.get('source'))} {o.get('clause', '')}: {num(o.get('value'))}" + (" ✓" if o.get("chosen") else "") for o in st.options)
            lines.append([st.title, "выбор нормативного значения", alts, st.source])
        elif st.kind == "note":
            lines.append([st.title, "", st.note, st.source])
        elif st.kind == "input":
            v = st.result
            lines.append([st.title, "исходные данные", f"{v.name} = {num(v.value)} {v.unit}", st.source])
    if lines:
        doc.table(["Шаг", "Формула", "Подстановка / результат", "Источник"], lines, widths=[4, 4.5, 6, 3.5])


def build_report(kind: str, project: Project, run, terminal_id: str | None = None, guard: dict | None = None) -> Doc:
    doc = Doc(KINDS[kind], f"{project.meta.name} — {project.meta.substation}", _meta(project, run), kind=kind)
    guard = guard or export_guard(project, run, terminal_id)
    doc.draft = kind == "card" and not guard["final_allowed"]
    doc.draft_reasons = guard["reasons"] if doc.draft else []
    cards = [run.cards[terminal_id]] if terminal_id and terminal_id in run.cards else list(run.cards.values())
    if kind == "calc":
        doc.h(1, "1. Исходные данные")
        _passport(doc, project)
        _cts(doc, project)
        _network(doc, project)
        doc.h(1, "2. Расчёт токов КЗ")
        h, rows = kz_rows(project)
        doc.p("Ниже — расчётные режимы «максимальный/минимальный КЗ» для положений РПН min, номинальное, max (Вып. 13Б п. 1.4). Полная таблица — в отчёте «Расчёт КЗ».")
        doc.table(h, rows[:120])
        doc.h(1, "3. Расчёт защит (уровень 1 — универсальные параметры PFM)")
        for fid, fr in run.results.items():
            doc.h(2, f"{fid} — {fr.title}")
            for w in fr.warnings + fr.missing:
                doc.note("Внимание: " + w)
            for pr in fr.params:
                doc.h(3, f"{pr.title} [{pr.key}]")
                doc.p(f"Расчётная уставка: {num(pr.calc)} {pr.unit}; допустимый интервал: {num(pr.lower)} … {num(pr.upper)} {pr.unit}; статус: {STATUS_RU[pr.status.value]}. {pr.reason}")
                if pr.criteria:
                    doc.table(["Критерий", "Вид", "Значение", "Основание"], [[c.title, {"lower": "не менее", "upper": "не более", "target": "цель", "fixed": "выбор"}[c.kind], num(c.value), c.ref] for c in pr.criteria],
                              widths=[8, 1.5, 2, 6])
                _trace_block(doc, pr)
            _checks_table(doc, fr.checks, "Проверки (расчётные уставки)")
        doc.h(1, "4. Перевод в параметры терминалов и повторная проверка")
        for c in cards:
            doc.h(2, c.profile.label + f" — {c.profile.summary()['status_label']}")
            doc.table(["Функция", "Параметр", "Расчёт", "Принято", "Ед.", "Диапазон", "Шаг", "Статус", "Пояснение"],
                      [[r.function, r.param_name or r.title, num(r.calc), num(r.accepted), r.unit, f"{num(r.min)} … {num(r.max)}" if r.min is not None else "", num(r.step), STATUS_RU[r.status.value], r.reason] for r in c.rows],
                      [r.status.value for r in c.rows], widths=[1.5, 4, 1.5, 1.5, 1.2, 2.2, 1, 2, 7])
            for fid, cs in c.checks.items():
                _checks_table(doc, cs, f"Повторная проверка после округления — {fid}")
    elif kind == "card":
        doc.h(1, "Карта уставок")
        for c in cards:
            doc.h(2, f"{c.profile.label} ({c.profile.summary()['status_label']})")
            src = c.profile.data.get("sources", [{}])[0]
            if src:
                doc.p(f"Источник параметров терминала: {src.get('doc', '—')}, {src.get('order_no', '')}, {src.get('release', '')}")
            rows = [[r.function, r.param_name or r.title, num(r.calc), num(r.accepted), r.unit, f"{num(r.min)} … {num(r.max)}" if r.min is not None else "", num(r.step), r.basis[:160], r.reason[:200], STATUS_RU[r.status.value]]
                    for r in c.rows if r.supported]
            doc.table(["Функция", "Параметр", "Расчёт", "Принято", "Ед.", "Диапазон", "Шаг", "Основание", "Комментарий", "Статус"], rows, [r.status.value for r in c.rows if r.supported], widths=[1.4, 4, 1.4, 1.4, 1.2, 2.2, 1, 5, 6, 2])
            na = [r for r in c.rows if not r.supported]
            if na:
                doc.h(3, "Не реализуется в терминале")
                doc.table(["Функция", "Уставка", "Причина"], [[r.function, r.title, r.reason] for r in na], [r.status.value for r in na], widths=[2, 6, 12])
    elif kind == "kz":
        doc.h(1, "Расчёт токов короткого замыкания")
        doc.p("Метод симметричных составляющих; положения РПН min/nom/max; направление токов ТТ — в защищаемый объект. Ток в месте КЗ и токи ТТ сторон — действительные значения на напряжении стороны.")
        doc.h(2, "Расчётные точки и режимы"); _network(doc, project)
        h, rows = kz_rows(project, full=True)
        doc.h(2, "Токи КЗ на шинах (все режимы библиотеки)")
        doc.table(h, rows)
    elif kind == "sens":
        doc.h(1, "Проверка чувствительности")
        for fid, fr in run.results.items():
            _checks_table(doc, [c for c in fr.checks if c.kind == "sensitivity"], f"{fid}: расчётные уставки")
        for c in cards:
            for fid, cs in c.checks.items():
                _checks_table(doc, [k for k in cs if k.kind == "sensitivity"], f"{fid}: после округления, терминал {c.profile.label}")
        # детали наихудших случаев
        for fid, fr in run.results.items():
            for chk in fr.checks:
                if chk.kind == "sensitivity" and chk.details:
                    doc.h(3, f"Случаи: {chk.title}")
                    keys = [k for k in chk.details[0].keys() if k in ("zone", "mode", "tap", "node", "ftype", "k_ch", "kch", "k_req", "i_min_a", "i0_min_a", "i2_min_a", "z_meas_ohm", "u_res_kv", "i_diff", "i_char")]
                    doc.table(keys, [[num(d.get(k)) for k in keys] for d in chk.details[:60]])
    elif kind == "selectivity":
        doc.h(1, "Проверка селективности")
        rows = []
        for fid, fr in run.results.items():
            for c in fr.checks:
                if c.kind in ("selectivity", "coordination"):
                    rows.append((fid, c))
        for c in cards:
            for fid, cs in c.checks.items():
                rows += [(f"{fid} ({c.profile.label})", k) for k in cs if k.kind in ("selectivity", "coordination")]
        doc.table(["Функция", "Проверка", "Запас", "Требуется", "Статус", "Обоснование"], [[f, c.title, num(c.value), num(c.threshold), STATUS_RU[c.status.value], c.reason] for f, c in rows], [c.status.value for _, c in rows], widths=[2, 6, 1.5, 1.5, 2, 9])
        doc.h(2, "Времена срабатывания (расчётные)")
        trows = []
        for fid, fr in run.results.items():
            for p in fr.params:
                if p.kind == "time" and not p.fixed:
                    trows.append([fid, p.title, num(p.calc), p.reason])
        doc.table(["Функция", "Уставка", "t, с", "Основание"], trows, widths=[2, 8, 1.5, 8])
        from ..calc import charts
        try:
            from .charts_png import tcc_png
            for s in project.transformer.sides():
                png = tcc_png(project, run, s, terminal_id)
                if png:
                    doc.image(png, f"Времятоковые характеристики МТЗ стороны {s}: своя защита, вышестоящие и нижестоящие; зона селективности выделена")
        except Exception:
            pass
    elif kind == "compare":
        from ..compare import compare_matrix
        doc.h(1, "Сравнение терминалов")
        doc.p("Программа не выбирает «лучшее» устройство: показаны расчёт (универсальный), принятые уставки и статусы по каждому терминалу.")
        m = compare_matrix(project, run, list(run.cards))
        doc.table(m["header"], m["rows_text"], m["row_status"], widths=[1.5, 5, 1.8] + [3] * (len(m["header"]) - 3))
    elif kind == "changes":
        doc.h(1, "Протокол изменений")
        doc.h(2, "Версии проекта")
        rows = [[s.version, s.date, s.author, s.reason] for s in project.history] + [[project.meta.version, project.meta.date, project.meta.author, project.meta.reason + " (текущая)"]]
        doc.table(["Версия", "Дата", "Автор", "Причина изменения"], rows)
        doc.h(2, "Журнал изменений")
        doc.table(["Время", "Пользователь", "Тип", "Раздел / путь", "Было", "Стало", "Причина", "Версия"],
                  [[c.ts, c.user, c.kind, f"{c.section} {c.path}".strip(), str(c.old)[:60], str(c.new)[:60], c.reason, c.version] for c in reversed(project.changelog)], widths=[2.5, 2, 1.3, 5, 3, 3, 4, 1.2])
    return doc
