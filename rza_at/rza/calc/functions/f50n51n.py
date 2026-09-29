"""50N/51N — ступенчатая токовая защита нулевой последовательности АТ (Вып. 13Б, гл. 12) и варианты защиты от замыканий на землю.

    (12.1) I_0с.з ≥ k_отс·k_ток·I_0с.з.пред, k_отс = 1,1   I ступень — с I ступенью смежных линий, II — со II, III — с последней
    (12.2) I_0с.з ≥ k_отс·3I_0неп                           отстройка от неполнофазного режима (ОАПВ), k_отс = 1,3 (1,4–1,5 для 330–500 кВ, РТ-40)
    (12.3) I_0с.з ≥ k_отс·I_0нб, k_отс = 1,25               отстройка от небаланса в нулевом проводе ТТ при внешних трёхфазных КЗ
    (12.4) I_0с.з ≥ (k_отс/k_в)·(I_0нб + 3I_0н.р)           послеаварийный нагрузочный режим
    (12.5) I_0нб = k_нб·I_расч, k_нб = 0,05 (кратность ≤ 2–3) / 0,05–0,1
    (12.6) k_ч = 3I_0з/I_0с.з ≥ 1,2 (ПУЭ РК п. 1003)
Выдержки времени — по согласованию с соответствующими ступенями защит смежных линий (п. 12.8).
Защита от замыканий на землю на стороне НН — Вып. 13Б, гл. 13 (реле напряжения с минимальной уставкой 15 В, ~9 с, на сигнал).
"""
from __future__ import annotations

from ...errors import Status
from ...pfm import PFM
from ...trace import Var
from ..context import CalcContext, TerminalContext
from ..results import Check, Criterion, FunctionResult, ParamResult
from ..shortcircuit import branch_phase_currents
from . import register
from .base import FunctionCalc

FID = "50N/51N"
INF = float("inf")
STAGES = (1, 2, 3)


def grounded_sides(ctx: CalcContext) -> list[str]:
    tr = ctx.tr
    out = []
    for s in ("HV", "MV"):
        if s in tr.sides():
            w = tr.w(s)
            if w.connection.upper().startswith("Y") and w.neutral != "isolated" and ctx.ct(s, "50N/51N", strict=True) is not None:
                out.append(s)
    return out


def i0_at(r, side: str) -> float:
    return 3.0 * abs(r.sides[side].i0)


def same_side_lines(ctx, side):
    return [ln for ln in ctx.p.network.lines if ln.side == side and ln.prot.i0]


def stage_ref(ln, k: int):
    """Ступень ТЗНП смежной линии, с которой согласуется ступень k защиты АТ."""
    st = ln.prot.i0
    if not st:
        return None
    idx = {1: 0, 2: 1}.get(k, len(st) - 1)
    return st[min(idx, len(st) - 1)]


@register
class F50N51N(FunctionCalc):
    id = FID
    title = "Токовая защита нулевой последовательности (50N/51N)"

    def calculate(self, ctx: CalcContext) -> FunctionResult:
        res = FunctionResult(FID, self.title)
        sides = grounded_sides(ctx)
        if not sides:
            res.missing.append("Нет заземлённых обмоток ВН/СН с ТТ, назначенными защите нулевой последовательности (50N/51N)")
        for s in sides:
            for k in STAGES:
                self._stage(ctx, res, s, k)
        self._lv_earth(ctx, res)
        res.meta["variants"] = self.variants(ctx)
        return res

    # ── I_расч для небаланса (12.5): наибольший ток внешнего трёхфазного КЗ на CT стороны ──
    def _unb_current(self, ctx, side) -> tuple[float, str]:
        best, who = 0.0, ""
        for o in ctx.tr.sides():
            if o == side:
                continue
            for r in ctx.scan("max_kz", o, "3ph"):
                v = max(abs(x) for x in r.sides[side].i_abc)
                if v > best:
                    best, who = v, f"КЗ на шинах {o}, режим {r.mode_id}, РПН {r.tap_key}"
        return best, who

    def _stage(self, ctx: CalcContext, res: FunctionResult, side: str, k: int):
        a, tr = ctx.a, ctx.tr
        ru = ctx.side_ru(side)
        inst = f"{side}:{k}"
        grp = f"ТЗНП {ru}, ступень {k}"
        p = ParamResult("51N.I0Pickup", inst, f"Ток срабатывания {k}-й ступени ТЗНП {ru} (3I0)", "А", "float", side=side, group=grp, rounding_dir="up")
        t = ctx.trace(f"Ток срабатывания {k}-й ступени ТЗНП {ru}")
        crit, lowers = [], []
        kc = ctx.norm("K.OTS.ZNP.COORD")
        ctx.note_norm(t, kc, "Коэффициент отстройки при согласовании k_отс (12.1)")
        K = {s: ctx.p.network.base_kv["HV"] / ctx.p.network.base_kv[s] for s in tr.sides()}
        # ── согласование (12.1) ──
        best = None
        for ln in same_side_lines(ctx, side):
            ref = stage_ref(ln, k)
            if ref is None or not ref.i_a:
                continue
            node = f"E_{ln.id}"
            kmax, wc = 0.0, None
            for role in ("max_kz", "min_kz"):
                for r in ctx.scan_for(side, role, node, "1ph"):
                    if r.flags.get("z0_inf"):
                        continue
                    m = ctx.kz.model(r.mode_id, r.tap_key)
                    lk = r.branches.get(f"LINE_{ln.id}")
                    if lk is None:
                        continue
                    il0 = 3.0 * abs(lk[2]) * m.K.get(node, 1.0) * 1000.0
                    ia0 = i0_at(r, side)
                    if il0 > 1.0 and ia0 / il0 > kmax:
                        kmax, wc = ia0 / il0, r
            if wc is None:
                continue
            v = t.calc("B13.12.1", {"k_отс": kc.value, "k_ток": Var("k_ток", kmax, "", f"наибольший по режимам и положениям РПН (режим {wc.mode_id}, РПН {wc.tap_key}), КЗ в конце «{ln.name}»"),
                                    "I_0пред": Var("I_0с.з.пред", ref.i_a, "А", f"{'I' if k == 1 else 'II' if k == 2 else 'последняя'} ступень ТЗНП «{ln.name}»")},
                       title=f"Согласование {k}-й ступени с {'I' if k == 1 else 'II' if k == 2 else 'последней'} ступенью ТЗНП «{ln.name}» (12.1)")
            if best is None or v.value > best[0]:
                best = (v.value, Criterion(f"coord_{ln.id}", "lower", v.value, f"Согласование с {'I' if k == 1 else 'II' if k == 2 else 'последней'} ступенью ТЗНП «{ln.name}»", kc.ref(ctx.reg.sources), "B13.12.1", f"k_ток={kmax:.2f}"))
        if best:
            lowers.append(best[0])
            crit.append(best[1])
        elif same_side_lines(ctx, side):
            pass
        else:
            res.warnings.append(f"ТЗНП {ru}: нет данных о ступенях ТЗНП смежных линий стороны — согласование {k}-й ступени не выполнено")
        # ── неполнофазный режим (12.2) ──
        if a.i0_oapv_a and k in (1, 2):
            ko = ctx.norm("K.OTS.ZNP.OAPV.HV" if a.hv_class_330_plus and side == "HV" else "K.OTS.ZNP.OAPV")
            ctx.note_norm(t, ko, "Коэффициент отстройки от неполнофазного режима (12.2)")
            v = t.calc("B13.12.2", {"k_отс": ko.value, "I_0неп": Var("3I_0неп", a.i0_oapv_a, "А", "допущение проекта")}, title="Отстройка от 3I0 в неполнофазном режиме (12.2)")
            lowers.append(v.value)
            crit.append(Criterion("oapv", "lower", v.value, "Отстройка от неполнофазного режима (ОАПВ)", ko.ref(ctx.reg.sources), "B13.12.2"))
        # ── небаланс при внешних КЗ (12.3) — для 2-й и 3-й ступеней ──
        ct = ctx.ct(side, "50N/51N")
        if k in (2, 3):
            iras, who = self._unb_current(ctx, side)
            if iras > 0:
                kb = ctx.norm("K.NB.ZNP.LOW" if iras <= 3.0 * ct.i1_a else "K.NB.ZNP.HIGH")
                ku = ctx.norm("K.OTS.ZNP.UNB")
                ctx.note_norm(t, kb, "Коэффициент небаланса k_нб (12.5)")
                ctx.note_norm(t, ku, "Коэффициент отстройки (12.3)")
                inb = t.calc("B13.12.5", {"k_нб": kb.value, "I_расч": Var("I_расч", iras, "А", who)}, title="Ток небаланса в нулевом проводе ТТ (12.5)")
                v = t.calc("B13.12.3", {"k_отс": ku.value, "I_0нб": inb}, title="Отстройка от небаланса при внешних трёхфазных КЗ (12.3)")
                crit.append(Criterion("unb", "lower", v.value, "Отстройка от небаланса в нулевом проводе ТТ при внешних КЗ", ku.ref(ctx.reg.sources), "B13.12.3", who))
                lowers.append(v.value)
        if k == 3:
            il, mid = ctx.i_load_max(side)
            kv, kv_src = ctx.k_reset()
            kb2 = ctx.norm("K.NB.ZNP.LOW")
            ku = ctx.norm("K.OTS.ZNP.UNB")
            inb2 = t.calc("B13.12.5", {"k_нб": kb2.value, "I_расч": Var("I_расч", il, "А", f"нагрузочный режим {mid}")}, title="Небаланс в нулевом проводе в послеаварийном нагрузочном режиме (12.5)")
            i0n = Var("3I_0н.р", a.i0_unb_extra_pu * ctx.i_nom_winding(side), "А", "несимметрия в системе (допущение проекта)")
            v = t.calc("B13.12.4", {"k_отс": ku.value, "k_в": Var("k_в", kv, "", "коэффициент возврата", kv_src), "I_0нб": inb2, "I_0нр": i0n}, title="Отстройка в послеаварийном нагрузочном режиме (12.4)")
            crit.append(Criterion("load", "lower", v.value, "Отстройка от небаланса в послеаварийном нагрузочном режиме", ku.ref(ctx.reg.sources), "B13.12.4"))
            lowers.append(v.value)
        if not lowers:
            lowers.append(0.0)
        # ── чувствительность (12.6) ──
        need = ctx.norm("KCH.ZNP")
        uppers, zone_desc = [], []
        zones = self._zones(ctx, side, k)
        for z in zones:
            case = self._i0_min(ctx, side, z["node"])
            if case is None:
                continue
            i0k, r = case
            up = t.calc("B13.12.6u", {"I_0з": Var("3I_0з", i0k, "А", f"{z['label']}, режим {r.mode_id}, РПН {r.tap_key}"), "k_ч": need.value}, title=f"Верхняя граница по чувствительности: {z['label']}")
            uppers.append(up.value)
            crit.append(Criterion(f"sens_{z['node']}", "upper", up.value, f"Чувствительность: {z['label']}", need.ref(ctx.reg.sources), "B13.12.6u", f"{r.mode_id}/{r.tap_key}"))
        p.criteria = crit
        p.lower = max(lowers)
        p.upper = min(uppers) if uppers else None
        p.calc = p.lower
        p.trace = t
        advisory = k in (1, 2)
        if p.upper is not None and p.lower > p.upper:
            p.status = Status.CHECK if advisory else Status.FAIL
            p.reason = (f"Нижняя граница {p.lower:.0f} А превышает предел по чувствительности {p.upper:.0f} А. "
                        + ("Для I–II ступеней чувствительность к КЗ на шинах желательна; пригодность определяется чувствительностью III ступени (Вып. 13Б п. 12.9)." if advisory else "Требуемая чувствительность III ступени не обеспечивается."))
        else:
            p.status = Status.OK
            p.reason = f"Допустимый интервал {p.lower:.0f} … {p.upper:.0f} А" if p.upper is not None else f"Не менее {p.lower:.0f} А"
        i_ref = None
        for z in zones:
            cs = self._i0_min(ctx, side, z["node"])
            if cs is not None and (i_ref is None or cs[0] < i_ref):
                i_ref = cs[0]
        p.meta = {"b13": "п. 12.2.1 (12.1)" if k < 3 else "п. 12.4, 12.5 (12.3)–(12.4); п. 12.9 (12.6)", "stage": k, "side": side, "advisory": advisory, "i_ref_a": i_ref}
        res.params.append(p)
        # выдержка времени (12.8)
        dt, dt_src = ctx.dt()
        lines = same_side_lines(ctx, side)
        tprev, who = 0.0, ""
        for ln in lines:
            ref = stage_ref(ln, k)
            if ref is not None and ref.t_s >= tprev:
                tprev, who = ref.t_s, f"«{ln.name}»"
        pt = ParamResult("51N.Delay", inst, f"Выдержка времени {k}-й ступени ТЗНП {ru}", "с", "time", side=side, group=grp, rounding_dir="up")
        tt = ctx.trace(f"Выдержка времени {k}-й ступени ТЗНП {ru}")
        tt.note("Смежные защиты", f"Выдержка времени согласуемой ступени смежных линий: {tprev:.2f} с {who}.", "Вып. 13Б п. 12.8")
        tv = tt.calc("MOD.TIME.COORD", {"t_пред": Var("t_пред", tprev, "с", who or "нет данных"), "dt": Var("Δt", dt, "с", "ступень селективности", dt_src)}, title="Выдержка времени по согласованию (12.8)")
        pt.calc = pt.lower = tv.value
        pt.trace = tt
        pt.criteria = [Criterion("time", "lower", tv.value, "Согласование по времени со ступенями смежных линий", dt_src, "MOD.TIME.COORD")]
        pt.status = Status.OK if lines else Status.CHECK
        pt.reason = f"t ≥ {tprev:.2f} + {dt:.2f} = {tv.value:.2f} с"
        res.params.append(pt)
        res.checks += self._checks_stage(ctx, side, k, {f"51N.I0Pickup@{inst}": p.calc, f"51N.Delay@{inst}": pt.calc}, None, "расчётные")

    def _zones(self, ctx, side, k):
        tr = ctx.tr
        z = []
        if k in (1, 2):
            z.append({"node": side, "label": f"Шины {tr.u_nom(side):g} кВ ({side}) — однофазное КЗ"})
        else:
            for ln in ctx.p.network.lines:
                if ln.side == side:
                    z.append({"node": f"E_{ln.id}", "label": f"Конец «{ln.name}» — однофазное КЗ"})
            if not z:
                z.append({"node": side, "label": f"Шины {tr.u_nom(side):g} кВ ({side}) — однофазное КЗ"})
        return z

    def _i0_min(self, ctx, side, node):
        best = None
        for r in ctx.scan_for(side, "min_kz", node, "1ph"):
            if r.flags.get("z0_inf"):
                continue
            v = i0_at(r, side)
            if best is None or v < best[0]:
                best = (v, r)
        return best

    def _checks_stage(self, ctx, side, k, vals, term, label) -> list[Check]:
        inst = f"{side}:{k}"
        iset = vals.get(f"51N.I0Pickup@{inst}")
        if iset is None or iset <= 0:
            return []
        need = ctx.norm("KCH.ZNP")
        rows, wmin = [], None
        for z in self._zones(ctx, side, k):
            case = self._i0_min(ctx, side, z["node"])
            if case is None:
                continue
            v, r = case
            kk = v / iset
            rows.append({"zone": z["label"], "mode": r.mode_id, "tap": r.tap_key, "i0_min_a": v, "k_ch": kk, "k_req": need.value, "ratio": kk / need.value})
            if wmin is None or kk < wmin["k_ch"]:
                wmin = rows[-1]
        out = []
        if wmin:
            tr_ = ctx.trace(f"Чувствительность {k}-й ступени ТЗНП {ctx.side_ru(side)} — {label} уставки")
            ctx.note_norm(tr_, need, "Требуемый коэффициент чувствительности")
            tr_.calc("B13.12.6", {"I_0з": Var("3I_0з", wmin["i0_min_a"], "А", f"{wmin['zone']}, режим {wmin['mode']}, РПН {wmin['tap']}"), "I_0с_з": Var("I_0с.з", iset, "А")}, title="Коэффициент чувствительности (12.6)")
            ok = wmin["k_ch"] >= need.value
            advisory = k in (1, 2)
            st = Status.OK if ok else (Status.CHECK if (advisory or wmin["k_ch"] >= 1.0) else Status.FAIL)
            out.append(Check(f"50N.sens@{inst}", FID, f"Чувствительность {k}-й ступени ТЗНП {ctx.side_ru(side)}" + (" (желательна)" if advisory else ""), "sensitivity", st, wmin["k_ch"], need.value, "", "≥",
                             f"k_ч = {wmin['k_ch']:.2f} {'≥' if ok else '<'} {need.value:g} — {wmin['zone']} (режим {wmin['mode']}, РПН {wmin['tap']})", tr_,
                             {"mode": wmin["mode"], "tap": wmin["tap"], "zone": wmin["zone"], "ftype": "1ph"}, rows, [need.ref(ctx.reg.sources)], f"51N.I0Pickup@{inst}"))
        # время
        tset = vals.get(f"51N.Delay@{inst}")
        return out

    def recheck(self, ctx: CalcContext, accepted: dict, term: TerminalContext | None = None) -> list[Check]:
        out = []
        for s in grounded_sides(ctx):
            for k in STAGES:
                out += self._checks_stage(ctx, s, k, accepted, term, "принятые (округлённые)")
                inst = f"{s}:{k}"
                iset = accepted.get(f"51N.I0Pickup@{inst}")
                if iset is not None and k == 3:
                    kv, kv_src = ctx.k_reset(term, FID)
                    il, _ = ctx.i_load_max(s)
                    kb, ku = ctx.norm("K.NB.ZNP.LOW"), ctx.norm("K.OTS.ZNP.UNB")
                    need_i = ku.value * (kb.value * il + ctx.a.i0_unb_extra_pu * ctx.i_nom_winding(s))
                    got = iset * kv
                    st = Status.OK if got >= need_i - 1e-9 else Status.FAIL
                    out.append(Check(f"50N.load@{inst}", FID, f"Отстройка III ступени ТЗНП {ctx.side_ru(s)} в нагрузочном режиме (k_в = {kv:g})", "requirement", st, got, need_i, "А", "≥",
                                     f"k_в·I_0с.з = {got:.1f} А {'≥' if st == Status.OK else '<'} {need_i:.1f} А (k_в: {kv_src})", None, {}, [], [ku.ref(ctx.reg.sources)], f"51N.I0Pickup@{inst}"))
        return out

    # ── защита от замыканий на землю на стороне НН (гл. 13) ──
    def _lv_earth(self, ctx, res):
        tr = ctx.tr
        if "LV" not in tr.sides():
            return
        w = tr.w("LV")
        if not (w.connection.upper().startswith("D") or w.neutral == "isolated"):
            return
        n = ctx.norm("U0.LV.MIN")
        p = ParamResult("59N.U0Pickup", "LV", "Напряжение срабатывания защиты от замыканий на землю на стороне НН (3U0, вторичное)", "В", "float", calc=n.value, fixed=True, side="LV", group="Замыкания на землю в сети НН")
        p.trace = ctx.trace("Защита от замыканий на землю на стороне НН")
        p.trace.note("Основание", "Защита выполняется максимальным реле напряжения с минимально возможной уставкой; выдержка времени ≈ 9 с; действует на сигнал.", n.ref(ctx.reg.sources))
        p.criteria = [Criterion("u0", "fixed", n.value, "Минимально возможная уставка реле напряжения", n.ref(ctx.reg.sources))]
        p.status = Status.CHECK
        p.reason = "Значение — минимальная уставка реле РН-53/60Д; для цифрового терминала принять по чувствительности к замыканиям в сети НН (проверка по ёмкостному току)"
        res.params.append(p)

    def variants(self, ctx: CalcContext) -> list[dict]:
        """Варианты защиты от замыканий на землю в зависимости от схемы заземления нейтрали, напряжения, конструкции АТ, расположения ТТ и схемы обмоток."""
        tr, cts = ctx.tr, ctx.p.cts
        has_neutral_ct = any(c.side == "N" or c.location == "neutral" for c in cts)
        has_line_ct = {s: ctx.ct(s, "50N/51N") is not None for s in tr.sides()}
        gr = grounded_sides(ctx)
        auto = tr.is_auto()
        out = []
        out.append({"id": "znp_residual", "name": "ТЗНП по утроенному току нулевой последовательности линейных ТТ (гл. 12 Вып. 13Б)",
                    "applicable": bool(gr), "why": (f"Заземлённые обмотки: {', '.join(gr)}; ТТ есть на сторонах {[s for s, v in has_line_ct.items() if v]}." if gr else "Нет заземлённых обмоток с ТТ."),
                    "note": "Ступенчатая, согласуется со ступенями ТЗНП смежных линий; в MVP реализован расчёт параметров.", "implemented": True})
        out.append({"id": "znp_neutral", "name": "ТЗНП по току в нейтрали общей обмотки АТ (ТТ в нейтрали)",
                    "applicable": bool(auto and has_neutral_ct), "why": ("Есть ТТ в нейтрали общей обмотки." if has_neutral_ct else "ТТ в нейтрали не заданы.") + (" АТ: ток нейтрали = сумма 3I0 сторон ВН и СН." if auto else ""),
                    "note": "Ток нейтрали не зависит от насыщения фазных ТТ; не различает сторону повреждения — селективность обеспечивается временем.", "implemented": False})
        out.append({"id": "ref_87n", "name": "Дифференциальная защита нулевой последовательности (REF, 87N)",
                    "applicable": bool(has_neutral_ct and gr), "why": "Требуются ТТ линейных выводов заземлённой обмотки и ТТ в нейтрали." if not has_neutral_ct else "ТТ в нейтрали и ТТ линейных выводов имеются.",
                    "note": "Повышает чувствительность к замыканиям на землю в обмотке (дифзащита 87T с исключением I0 менее чувствительна). Требует поддержки в терминале (7UT6: функция REF).", "implemented": False})
        lvd = "LV" in tr.sides() and (tr.w("LV").connection.upper().startswith("D") or tr.w("LV").neutral == "isolated")
        out.append({"id": "lv_3u0", "name": "Защита от замыканий на землю в сети НН (по 3U0, Вып. 13Б гл. 13)", "applicable": bool(lvd),
                    "why": "Обмотка НН соединена в треугольник / нейтраль сети изолирована." if lvd else "Обмотка НН заземлена или отсутствует.",
                    "note": "Действует на сигнал (~9 с); минимальная уставка реле напряжения.", "implemented": True})
        return out
