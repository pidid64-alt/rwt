"""46 — токовая защита обратной последовательности АТ (Вып. 13Б, гл. 9).

    (9.1) I_2с.з ≥ k_отс·(I_2нб + I_2нс)/k_в       отстройка от небаланса фильтра и несимметрии системы, k_отс = 1,2
    (9.2) I_2нб = k_нб·I_нагр.макс                  k_нб = 0,02–0,03
    (9.3) I_2с.з ≥ (0,1–0,2)·I_ном, k_ч ≤ 1,5 в зоне резервирования
    (9.4) I_2с.з ≥ k_отс·I_2расч, k_отс = 1,1       согласование по чувствительности со смежными защитами (п. 9.3–9.5)
    (9.6) I_2расч⁽¹⁾   = (k_2ток/k_0ток)·I_0с.з/3               однофазное КЗ на землю
    (9.7) I_2расч⁽¹·¹⁾ = k_п·(k_2ток/k_0ток)·(I_0с.з/3)·Z_0Σ/Z_2Σ  двухфазное КЗ на землю (расчётным при k_п·Z_0Σ/Z_2Σ > 1)
    (9.5) I_2расч = k_2ток·I_2с.з.пред
    (9.13) k_ч = I_2к/I_2с.з ≥ 1,2 (ПУЭ РК п. 1003, пп. 1))
Выдержка времени — по согласованию с последними ступенями защит смежных линий (п. 9.6).
Токи смежных линий приводятся к ступени напряжения защиты (Вып. 13Б п. 1.x: «первичные токи приведены к одной ступени напряжения»).
"""
from __future__ import annotations

from ...errors import Status
from ...trace import Var
from ..context import CalcContext, TerminalContext
from ..results import Check, Criterion, FunctionResult, ParamResult
from ..shortcircuit import branch_phase_currents
from . import register
from .base import FunctionCalc
from .f5051 import zones_for, min_current_case, line_last_time

FID = "46"
INF = float("inf")
ORDER = ["HV", "MV", "LV"]


def coord_lines(ctx: CalcContext, side: str) -> list:
    pos = ORDER.index(side)
    return [ln for ln in ctx.p.network.lines if ln.side in ORDER[pos:] and ln.side in ctx.tr.sides()]


def i2_at(r, side: str) -> float:
    return abs(r.sides[side].i2)


def line_last_time_all(ln) -> float:
    ts = [s.t_s for s in ln.prot.mtz] + [s.t_s for s in ln.prot.dist] + [s.t_s for s in ln.prot.i0] + [s.t_s for s in ln.prot.neg]
    return max(ts) if ts else 0.0


@register
class F46(FunctionCalc):
    id = FID
    title = "Токовая защита обратной последовательности (46)"

    def sides_used(self, ctx) -> list[str]:
        return [s for s in ctx.tr.sides() if ctx.ct(s, "46", strict=True) is not None and s != "LV"]

    def calculate(self, ctx: CalcContext) -> FunctionResult:
        res = FunctionResult(FID, self.title)
        sides = self.sides_used(ctx)
        if not sides:
            res.missing.append("Нет ТТ, назначенных защите обратной последовательности (46) на сторонах ВН/СН")
            return res
        for side in sides:
            self._side(ctx, res, side)
        return res

    # ── сопряжённые расчёты согласования ──
    def coordination(self, ctx: CalcContext, t, side: str) -> tuple[float, Criterion] | None:
        """Наибольшее I_2расч по согласованию с ТЗНП (9.6, 9.7) и защитами обратной последовательности (9.5) смежных линий."""
        a = ctx.a
        kk = ctx.norm("K.OTS.46.COORD")
        kp = ctx.norm("K.KP.46")
        K = {s: ctx.p.network.base_kv["HV"] / ctx.p.network.base_kv[s] for s in ctx.tr.sides()}
        best = None
        for ln in coord_lines(ctx, side):
            kU = ctx.p.network.base_kv[ln.side] / ctx.p.network.base_kv[side]   # приведение тока линии к ступени напряжения защиты
            node = f"E_{ln.id}"
            # ── с ТЗНП линии (глухозаземлённая сеть) ──
            if ln.prot.i0:
                i0s = min(s.i_a for s in ln.prot.i0 if s.i_a)
                worst = None
                for role in ("min_kz", "max_kz"):
                    for ft in ("1ph", "2ph_g"):
                        for r in ctx.scan_for(side, role, node, ft):
                            if r.flags.get("z0_inf"):
                                continue
                            z1, z2, z0 = r.z_seq
                            ratio = abs(z0) / abs(z2)
                            calc_ft = "2ph_g" if kp.value * ratio > 1.0 else "1ph"
                            if ft != calc_ft:
                                continue
                            i2f = abs(r.fault_seq[2])
                            i0f = abs(r.fault_seq[0])
                            if i2f < 1.0 or i0f < 1.0:
                                continue
                            m = ctx.kz.model(r.mode_id, r.tap_key)
                            lk = r.branches.get(f"LINE_{ln.id}")
                            if lk is None:
                                continue
                            i0line = abs(lk[2]) * m.K.get(node, 1.0) * 1000.0     # I0 линии (фаза), А
                            i2s = i2_at(r, side)
                            k2 = (i2s / K[side]) / (i2f / K[ln.side])
                            k0 = (i0line / K[ln.side]) / (i0f / K[ln.side]) if i0f else 0
                            if k0 < 1e-6:
                                continue
                            v = (k2 / k0) * (i0s / 3.0) * kU * (kp.value * ratio if calc_ft == "2ph_g" else 1.0)
                            if worst is None or v > worst[0]:
                                worst = (v, r, k2, k0, ratio, calc_ft)
                if worst:
                    v, r, k2, k0, ratio, ft = worst
                    ctx.note_norm(t, kp, "Коэффициент k_п (переходные сопротивления)")
                    if ft == "1ph":
                        i2r = t.calc("B13.9.6", {"k_2ток": Var("k_2ток", k2, "", f"режим {r.mode_id}, РПН {r.tap_key}"), "k_0ток": k0, "I_0с_з": Var("I_0с.з", i0s, "А", f"ТЗНП «{ln.name}», наиболее чувствительная ступень"), "k_U": kU},
                                     title=f"Расчётный ток обратной последовательности при согласовании с ТЗНП «{ln.name}» (однофазное КЗ) (9.6)")
                    else:
                        i2r = t.calc("B13.9.7", {"k_п": kp.value, "k_2ток": Var("k_2ток", k2, "", f"режим {r.mode_id}, РПН {r.tap_key}"), "k_0ток": k0, "I_0с_з": Var("I_0с.з", i0s, "А", f"ТЗНП «{ln.name}»"),
                                                 "Z0Z2": Var("Z_0Σ/Z_2Σ", ratio, ""), "k_U": kU},
                                     title=f"Расчётный ток обратной последовательности при согласовании с ТЗНП «{ln.name}» (двухфазное КЗ на землю) (9.7)")
                    need = t.calc("B13.9.4", {"k_отс": kk.value, "I_2расч": i2r}, title=f"Условие согласования по чувствительности с «{ln.name}» (9.4)")
                    c = Criterion(f"coord_i0_{ln.id}", "lower", need.value, f"Согласование с ТЗНП «{ln.name}» ({'2ф.к.з. на землю' if ft == '2ph_g' else '1ф.к.з.'})", kk.ref(ctx.reg.sources),
                                  "B13.9.6" if ft == "1ph" else "B13.9.7", f"k_2ток={k2:.2f}, k_0ток={k0:.2f}, Z0/Z2={ratio:.2f}")
                    if best is None or need.value > best[0]:
                        best = (need.value, c)
            # ── с защитой обратной последовательности линии (9.5) ──
            if ln.prot.neg:
                i2p = min(s.i_a for s in ln.prot.neg if s.i_a)
                worst = None
                for role in ("min_kz", "max_kz"):
                    for r in ctx.scan_for(side, role, node, "2ph"):
                        m = ctx.kz.model(r.mode_id, r.tap_key)
                        lk = r.branches.get(f"LINE_{ln.id}")
                        if lk is None:
                            continue
                        i2l = abs(lk[1]) * m.K.get(node, 1.0) * 1000.0
                        if i2l < 1.0:
                            continue
                        k2 = (i2_at(r, side) / K[side]) / (i2l / K[ln.side])
                        if worst is None or k2 > worst[0]:
                            worst = (k2, r)
                if worst:
                    k2, r = worst
                    i2r = t.calc("B13.9.5", {"k_2ток": Var("k_2ток", k2, "", f"режим {r.mode_id}, РПН {r.tap_key}"), "I_2с_з_пред": Var("I_2с.з.пред", i2p, "А", f"защита ОП «{ln.name}»"), "k_U": kU},
                                 title=f"Расчётный ток при согласовании с защитой обратной последовательности «{ln.name}» (9.5)")
                    need = t.calc("B13.9.4", {"k_отс": kk.value, "I_2расч": i2r}, title=f"Условие согласования (9.4) с «{ln.name}»")
                    c = Criterion(f"coord_neg_{ln.id}", "lower", need.value, f"Согласование с защитой обратной последовательности «{ln.name}»", kk.ref(ctx.reg.sources), "B13.9.5", f"k_2ток={k2:.2f}")
                    if best is None or need.value > best[0]:
                        best = (need.value, c)
        return best

    def _side(self, ctx: CalcContext, res: FunctionResult, side: str):
        a, tr = ctx.a, ctx.tr
        ru = ctx.side_ru(side)
        p = ParamResult("46.I2Pickup", side, f"Ток срабатывания защиты обратной последовательности {ru}", "А", "float", side=side, group=f"Защита ОП {ru}", rounding_dir="up")
        t = ctx.trace(f"Ток срабатывания защиты обратной последовательности {ru}")
        k_ots, k_nb = ctx.norm("K.OTS.46"), ctx.norm("K.NB.46")
        k_v, kv_src = ctx.k_reset()
        ctx.note_norm(t, k_ots, "Коэффициент отстройки k_отс (9.1)")
        ctx.note_norm(t, k_nb, "Коэффициент небаланса фильтра k_нб (9.2)")
        i_nom = ctx.i_nom_winding(side)
        il, mid = ctx.i_load_max(side)
        inb = t.calc("B13.9.2", {"k_нб": k_nb.value, "I_нагр_макс": Var("I_нагр.макс", il, "А", f"режим {mid}")}, title="Ток небаланса на выходе фильтра при максимальной нагрузке (9.2)")
        i2ns = Var("I_2нс", a.i2_asym_pu * i_nom, "А", "несимметрия в системе (допущение проекта: доля I_ном)")
        low1 = t.calc("B13.9.1", {"k_отс": k_ots.value, "I_2нб": inb, "I_2нс": i2ns, "k_в": Var("k_в", k_v, "", "коэффициент возврата", kv_src)}, title="Отстройка от небаланса и несимметрии системы (9.1)")
        crit = [Criterion("unb", "lower", low1.value, "Отстройка от небаланса фильтра и несимметрии системы", k_ots.ref(ctx.reg.sources), "B13.9.1")]
        lowers = [low1.value]
        nmin = ctx.norm("K.MIN.46")
        low2 = t.calc("B13.9.3", {"k_мин": nmin.value, "I_ном": Var("I_ном", i_nom, "А")}, title="Минимальный ток срабатывания по (9.3)")
        crit.append(Criterion("min", "lower", low2.value, "Не менее (0,1–0,2)·I_ном (снижение вероятности неселективных действий)", nmin.ref(ctx.reg.sources), "B13.9.3"))
        lowers.append(low2.value)
        # согласование
        coord = self.coordination(ctx, t, side)
        # чувствительность
        need = ctx.norm("KCH.46")
        kmax = ctx.norm("KCH.46.MAX")
        uppers, lows_sens, rows = [], [], []
        for z in zones_for(ctx, side):
            case = self._i2_min_case(ctx, side, z["node"])
            if case is None:
                continue
            i2k, r = case
            up = t.calc("B13.9.13u", {"I_2к": Var("I_2к", i2k, "А", f"{z['label']}, режим {r.mode_id}, РПН {r.tap_key}"), "k_ч": need.value}, title=f"Верхняя граница по чувствительности: {z['label']}")
            uppers.append(up.value)
            crit.append(Criterion(f"sens_{z['node']}", "upper", up.value, f"Чувствительность: {z['label']}", need.ref(ctx.reg.sources), "B13.9.13u", f"{r.mode_id}/{r.tap_key}"))
            if not z["main"] and z["node"].startswith("E_"):
                lows_sens.append((i2k, z["label"], r))
        if lows_sens and a.limit_46_sens:
            # ограничение относится к наиболее удалённой точке зоны резервирования (наименьший ток ОП)
            i2far, lab, rr = min(lows_sens, key=lambda x: x[0])
            lo = t.calc("B13.9.3s", {"I_2к": Var("I_2к", i2far, "А", f"{lab}, режим {rr.mode_id}, РПН {rr.tap_key}"), "k_ч_макс": kmax.value},
                        title=f"Ограничение чувствительности в наиболее удалённой точке зоны резервирования ({lab}), (9.3): k_ч ≤ {kmax.value:g}")
            crit.append(Criterion("sens_cap", "lower", lo.value, f"Ограничение чувствительности в зоне резервирования (k_ч ≤ {kmax.value:g}): {lab}", kmax.ref(ctx.reg.sources), "B13.9.3s", "рекомендация п. 9.2"))
            lowers.append(lo.value)
        if coord is not None:
            cv, cc = coord
            if uppers and cv > min(uppers):
                res.warnings.append(f"Защита ОП {ru}: согласование ({cv:.0f} А) несовместимо с чувствительностью (не более {min(uppers):.0f} А) — согласование по п. 9.3 выполняется лишь при обеспечении чувствительности")
                t.note("Согласование по чувствительности не принято", f"Требуемое {cv:.0f} А превышает предел по чувствительности {min(uppers):.0f} А.", "Вып. 13Б п. 9.3")
            else:
                crit.append(cc)
                lowers.append(cv)
        p.criteria = crit
        p.lower = max(lowers)
        p.upper = min(uppers) if uppers else None
        # если ограничение чувствительности конфликтует с верхним пределом — оно рекомендательное
        if p.upper is not None and p.lower > p.upper:
            hard = max([low1.value, low2.value] + ([coord[0]] if coord and not (uppers and coord[0] > min(uppers)) else []))
            if hard <= p.upper:
                p.lower = hard
                t.note("Рекомендательное ограничение чувствительности не принято", "Ограничение k_ч ≤ 1,5 (9.3) противоречит требуемой чувствительности ≥ 1,2; сохранена требуемая чувствительность.", "Вып. 13Б п. 9.2")
        p.calc = p.lower
        p.trace = t
        if p.upper is not None and p.lower > p.upper:
            p.status = Status.FAIL
            p.reason = f"Отстройка ({p.lower:.0f} А) несовместима с чувствительностью (не более {p.upper:.0f} А)"
        else:
            p.status = Status.OK
            p.reason = f"Допустимый интервал {p.lower:.0f} … {p.upper:.0f} А" if p.upper is not None else f"Не менее {p.lower:.0f} А"
        p.meta = {"b13": "п. 9.2 (9.1)–(9.3), п. 9.4 (9.4)–(9.7), п. 9.7 (9.13)", "i_nom_a": i_nom}
        res.params.append(p)
        # выдержка времени
        dt, dt_src = ctx.dt()
        times = [(line_last_time_all(ln), f"«{ln.name}»") for ln in coord_lines(ctx, side)]
        t_down, who = max(times) if times else (0.0, "нет данных о смежных защитах")
        if not times:
            res.warnings.append(f"Защита ОП {ru}: нет данных о защитах смежных линий — выдержка времени принята Δt")
        pt = ParamResult("46.Delay", side, f"Выдержка времени защиты обратной последовательности {ru}", "с", "time", side=side, group=f"Защита ОП {ru}", rounding_dir="up")
        tt = ctx.trace(f"Выдержка времени защиты обратной последовательности {ru}")
        tt.note("Смежные защиты", f"Наибольшая выдержка времени последних ступеней смежных защит: {t_down:.2f} с ({who}).", "Вып. 13Б п. 9.6")
        tv = tt.calc("MOD.TIME.COORD", {"t_пред": Var("t_пред", t_down, "с", who), "dt": Var("Δt", dt, "с", "ступень селективности", dt_src)}, title="Выдержка времени по согласованию")
        pt.calc = pt.lower = tv.value
        pt.trace = tt
        pt.criteria = [Criterion("time", "lower", tv.value, "Согласование по времени с последними ступенями смежных защит", dt_src, "MOD.TIME.COORD")]
        pt.status = Status.OK if times else Status.CHECK
        pt.reason = f"t ≥ {t_down:.2f} + {dt:.2f} = {tv.value:.2f} с"
        res.params.append(pt)
        res.checks += self._checks(ctx, side, {f"46.I2Pickup@{side}": p.calc, f"46.Delay@{side}": pt.calc}, None, "расчётные")

    def _i2_min_case(self, ctx, side, node):
        best = None
        for r in ctx.scan_for(side, "min_kz", node, "2ph"):
            v = i2_at(r, side)
            if best is None or v < best[0]:
                best = (v, r)
        return best

    def _checks(self, ctx, side, vals, term, label) -> list[Check]:
        ru = ctx.side_ru(side)
        iset = vals.get(f"46.I2Pickup@{side}")
        if iset is None:
            return []
        out, src = [], ctx.reg.sources
        need = ctx.norm("KCH.46")
        kmax = ctx.norm("KCH.46.MAX")
        rows, wmin = [], None
        for z in zones_for(ctx, side):
            case = self._i2_min_case(ctx, side, z["node"])
            if case is None:
                continue
            i2k, r = case
            k = i2k / iset
            rows.append({"zone": z["label"], "mode": r.mode_id, "tap": r.tap_key, "i2_min_a": i2k, "k_ch": k, "k_req": need.value, "ratio": k / need.value})
            if wmin is None or k < wmin["k_ch"]:
                wmin = rows[-1]
        if rows:
            tr_ = ctx.trace(f"Чувствительность защиты ОП {ru} — {label} уставки")
            ctx.note_norm(tr_, need, "Требуемый коэффициент чувствительности")
            tr_.calc("B13.9.13", {"I_2к": Var("I_2к", wmin["i2_min_a"], "А", f"{wmin['zone']}, режим {wmin['mode']}, РПН {wmin['tap']}"), "I_2с_з": Var("I_2с.з", iset, "А")}, title="Коэффициент чувствительности (9.13)")
            st = Status.OK if wmin["k_ch"] >= need.value else (Status.CHECK if wmin["k_ch"] >= 1.0 else Status.FAIL)
            out.append(Check(f"46.sens@{side}", FID, f"Чувствительность защиты ОП {ru}", "sensitivity", st, wmin["k_ch"], need.value, "", "≥",
                             f"k_ч = {wmin['k_ch']:.2f} {'≥' if st == Status.OK else '<'} {need.value:g} — {wmin['zone']} (режим {wmin['mode']}, РПН {wmin['tap']})", tr_,
                             {"mode": wmin["mode"], "tap": wmin["tap"], "zone": wmin["zone"], "ftype": "2ph"}, rows, [need.ref(src)], f"46.I2Pickup@{side}"))
        # отстройка от небаланса при фактическом k_в терминала
        a = ctx.a
        kvr, kvsrc = ctx.k_reset(term, FID)
        i_nom = ctx.i_nom_winding(side)
        il, _ = ctx.i_load_max(side)
        k_ots, k_nb = ctx.norm("K.OTS.46"), ctx.norm("K.NB.46")
        need_i = k_ots.value * (k_nb.value * il + a.i2_asym_pu * i_nom)
        got = iset * kvr
        st = Status.OK if got >= need_i - 1e-9 else Status.FAIL
        out.append(Check(f"46.unb@{side}", FID, f"Отстройка защиты ОП {ru} от небаланса (k_в = {kvr:g})", "requirement", st, got, need_i, "А", "≥",
                         f"I_возв = k_в·I_2с.з = {got:.1f} А {'≥' if st == Status.OK else '<'} k_отс·(I_2нб+I_2нс) = {need_i:.1f} А (k_в: {kvsrc})", None, {}, [], [k_ots.ref(src)], f"46.I2Pickup@{side}"))
        # ограничение чувствительности (рекомендательное)
        if rows and a.limit_46_sens:
            lines_rows = [r for r in rows if r["zone"].startswith("Конец")]
            if lines_rows:
                w = min(lines_rows, key=lambda r: r["k_ch"])
                st = Status.OK if w["k_ch"] <= kmax.value + 1e-9 else Status.CHECK
                out.append(Check(f"46.cap@{side}", FID, f"Ограничение чувствительности защиты ОП {ru} в зоне резервирования (k_ч ≤ {kmax.value:g})", "requirement", st, w["k_ch"], kmax.value, "", "≤",
                                 f"k_ч в наиболее удалённой точке зоны резервирования = {w['k_ch']:.2f} ({w['zone']}); рекомендация Вып. 13Б п. 9.2 (9.3)", None, {}, [], [kmax.ref(src)], f"46.I2Pickup@{side}"))
        return out

    def recheck(self, ctx: CalcContext, accepted: dict, term: TerminalContext | None = None) -> list[Check]:
        out = []
        for side in self.sides_used(ctx):
            out += self._checks(ctx, side, accepted, term, "принятые (округлённые)")
            # согласование по принятому значению
            key = f"46.I2Pickup@{side}"
            if key in accepted:
                t = ctx.trace("Согласование по чувствительности (повтор)")
                co = self.coordination(ctx, t, side)
                if co is not None:
                    need, c = co
                    st = Status.OK if accepted[key] >= need - 1e-9 else Status.CHECK
                    out.append(Check(f"46.coord@{side}", FID, f"Согласование защиты ОП {ctx.side_ru(side)} по чувствительности со смежными защитами", "coordination", st, accepted[key], need, "А", "≥",
                                     f"I_2с.з = {accepted[key]:.1f} А {'≥' if st == Status.OK else '<'} {need:.1f} А ({c.title})", t, {}, [], [c.ref], key))
        return out
