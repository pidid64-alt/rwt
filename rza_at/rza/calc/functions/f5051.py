"""50/51 — максимальная токовая защита сторон АТ (Вып. 13Б, гл. 10 «с пуском по напряжению» и гл. 11 «без пуска»).

Ток срабатывания:
    с пуском по напряжению   I_с.з ≥ k_отс·I_ном/k_в                       (10.1), k_отс = 1,2; для РПН-стороны I_ном·1,05 (п. 10.2)
    без пуска по напряжению  I_с.з ≥ k_отс·k_зап·I_раб.макс/k_в            (11.1)
    согласование             I_с.з ≥ k_отс·k_ток·I_с.з.пред, k_отс = 1,1   (10.2), п. 10.3
Напряжение срабатывания минимального органа (10.4), (10.5); орган U2 — 0,06·U_ном (10.6).
Чувствительность: k_ч = I_к.min/I_с.з (10.8), органов напряжения (10.9)–(10.11).
Выдержка времени: t ≥ t_пред + Δt (п. 10.7, 11.3), Δt по п. 8.1.11.
"""
from __future__ import annotations

import math

from ...errors import Status
from ...pfm import PFM
from ...trace import Var
from ..context import CalcContext, TerminalContext, status_from_ratio
from ..results import Check, Criterion, FunctionResult, ParamResult
from . import register
from .base import FunctionCalc

FID = "50/51"
INF = float("inf")


def ppv(u_abc) -> list[float]:
    """Модули междуфазных напряжений по фазным (кВ)."""
    a, b, c = u_abc
    return [abs(a - b), abs(b - c), abs(c - a)]


def min_current_case(ctx: CalcContext, side: str, node: str, ftype: str, roles=("min_kz",), exclude_energization: bool = True):
    best = None
    for role in roles:
        for r in ctx.scan_for(side, role, node, ftype, exclude_energization):
            i = max(abs(x) for x in r.sides[side].i_abc)
            if best is None or i < best[0]:
                best = (i, r)
    return best


def zones_for(ctx: CalcContext, side: str) -> list[dict]:
    """Зоны проверки чувствительности МТЗ стороны.

    ВН: шины СН и НН через АТ (резервирование). СН: собственные шины (основная защита, если нет защиты шин) и концы линий СН.
    НН: собственные шины. Резервирование КЗ за трансформатором (линии другого напряжения) не требуется (ПУЭ РК п. 995, пп. 1))."""
    tr, net = ctx.tr, ctx.p.network
    sides = tr.sides()
    z = []
    if side == "HV":
        for o in ("MV", "LV"):
            if o in sides:
                z.append({"node": o, "label": f"Шины {tr.u_nom(o):g} кВ ({o}) — через АТ", "main": False})
        return z
    bp = net.bus_protection.get(side, False)
    z.append({"node": side, "label": f"Шины {tr.u_nom(side):g} кВ ({side})", "main": not bp})
    for ln in net.lines:
        if ln.side == side:
            z.append({"node": f"E_{ln.id}", "label": f"Конец «{ln.name}»", "main": False, "line": ln})
    return z


def line_last_time(ln) -> float:
    ts = [s.t_s for s in ln.prot.mtz] + [s.t_s for s in ln.prot.dist]
    return max(ts) if ts else 0.0


@register
class F5051(FunctionCalc):
    id = FID
    title = "Максимальная токовая защита сторон АТ (50/51)"

    def sides_used(self, ctx) -> list[str]:
        return [s for s in ctx.tr.sides() if ctx.ct(s, "50/51", strict=True) is not None]

    def calculate(self, ctx: CalcContext) -> FunctionResult:
        tr, a, net = ctx.tr, ctx.a, ctx.p.network
        res = FunctionResult(FID, self.title)
        sides = self.sides_used(ctx)
        if not sides:
            res.missing.append("Нет ТТ для МТЗ (50/51) ни на одной стороне")
            return res
        dt, dt_src = ctx.dt()
        k_otsn = ctx.norm("K.OTS.MTZ")
        k_v, kv_src = ctx.k_reset()
        times: dict[str, float] = {}
        # каскад по времени: НН → СН → ВН
        for side in [s for s in ("LV", "MV", "HV") if s in sides]:
            down = []
            for ln in net.lines:
                if ln.side == side:
                    down.append((line_last_time(ln), f"защиты «{ln.name}»"))
            for te in net.tcc:
                if te.role == "downstream" and te.side == side and te.stages:
                    down.append((max(s.t_s for s in te.stages), te.name))
            if side == "HV" and "MV" in times:
                down.append((times["MV"], "МТЗ стороны СН"))
            if side == "HV" and "LV" in times:
                down.append((times["LV"], "МТЗ стороны НН"))
            if side == "MV" and "LV" in times:
                down.append((times["LV"], "МТЗ стороны НН"))
            t_down, who = max(down) if down else (0.0, "нет данных о нижестоящих защитах")
            if not down:
                res.warnings.append(f"Сторона {side}: нет данных о нижестоящих защитах — время принято равным Δt; введите уставки смежных защит для согласования")
            times[side] = t_down + dt
            self._side(ctx, res, side, k_otsn, k_v, kv_src, dt, dt_src, t_down, who, times[side])
        return res

    # ── расчёт одной стороны ──
    def _side(self, ctx, res, side, k_otsn, k_v, kv_src, dt, dt_src, t_down, who, t_set):
        tr, a, net = ctx.tr, ctx.a, ctx.p.network
        ru = ctx.side_ru(side)
        p = ParamResult("51.IPickup", side, f"Ток срабатывания МТЗ {ru}", "А", "float", side=side, group=f"МТЗ {ru}", rounding_dir="up")
        t = ctx.trace(f"Ток срабатывания МТЗ {ru}")
        ctx.note_norm(t, k_otsn, "Коэффициент отстройки k_отс (Вып. 13Б (10.1))")
        i_nom = ctx.i_nom_winding(side)
        i_nom_var = Var("I_ном", i_nom, "А", f"номинальный ток обмотки {side}")
        if tr.oltc.present and tr.oltc.side == side:
            nrp = ctx.norm("K.RPN.NOM")
            i_nom_var = t.calc("B13.10.2i", {"I_ном0": i_nom, "k_рпн": nrp.value}, title="Номинальный ток стороны с РПН (с учётом +5 %, п. 10.2)")
            i_nom_var = Var("I_ном", i_nom_var.value, "А")
        crit = []
        lowers = []
        if a.use_voltage_start:
            cur = t.calc("B13.10.1", {"k_отс": k_otsn.value, "I_ном": i_nom_var, "k_в": Var("k_в", k_v, "", "коэффициент возврата", kv_src)},
                         title="Отстройка от номинального тока при пуске по напряжению (10.1)")
            crit.append(Criterion("load", "lower", cur.value, "Отстройка от номинального тока (пуск по напряжению)", k_otsn.ref(ctx.reg.sources), "B13.10.1"))
        else:
            il, mid = ctx.i_load_max(side)
            cur = t.calc("B13.11.1", {"k_отс": k_otsn.value, "k_зап": a.k_self_start, "I_раб_макс": Var("I_раб.макс", il, "А", f"режим {mid}"),
                                      "k_в": Var("k_в", k_v, "", "коэффициент возврата", kv_src)}, title="Отстройка от максимального рабочего тока с учётом самозапуска (11.1)")
            crit.append(Criterion("load", "lower", cur.value, "Отстройка от рабочего тока и самозапуска", k_otsn.ref(ctx.reg.sources), "B13.11.1"))
        lowers.append(cur.value)
        # ── согласование по чувствительности (10.2) ──
        coord = self._coordination(ctx, t, side, dt)
        # ── чувствительность (верхняя граница) ──
        uppers, zone_rows = [], []
        kmain, kback = ctx.norm("KCH.MTZ.MAIN"), ctx.norm("KCH.MTZ.BACKUP")
        for z in zones_for(ctx, side):
            ftype = "2ph"
            node = z["node"]
            case = min_current_case(ctx, side, node, ftype)
            if case is None:
                continue
            need = kmain if z["main"] else kback
            imin, r = case
            up = t.calc("B13.10.8u", {"I_к_min": Var("I_к.min", imin, "А", f"{z['label']}, режим {r.mode_id}, РПН {r.tap_key}"), "k_ч": need.value},
                        title=f"Верхняя граница по чувствительности: {z['label']}")
            zone_rows.append((up.value, z, need, imin, r))
            crit.append(Criterion(f"sens_{node}", "upper", up.value, f"Чувствительность: {z['label']}" + (" (основная защита)" if z["main"] else " (резервирование)"),
                                  need.ref(ctx.reg.sources), "B13.10.8u", f"{r.mode_id}/{r.tap_key}"))
            uppers.append(up.value)
        if coord is not None and coord[0] is not None:
            cv, cc = coord
            if uppers and cv > min(uppers):
                res.warnings.append(f"МТЗ {ru}: согласование по чувствительности со смежными защитами ({cv:.0f} А) несовместимо с требуемой чувствительностью ({min(uppers):.0f} А) — приоритет отдан чувствительности (Вып. 13Б п. 10.5)")
                t.note("Согласование по чувствительности не принято", f"Требуемое {cv:.0f} А превышает предел по чувствительности {min(uppers):.0f} А; согласно п. 10.5 согласование выполняется только при обеспечении чувствительности.", "Вып. 13Б п. 10.5")
            else:
                crit.append(cc)
                lowers.append(cv)
        p.criteria = crit
        p.lower = max(lowers)
        p.upper = min(uppers) if uppers else None
        p.calc = p.lower
        p.trace = t
        if p.upper is not None and p.lower > p.upper:
            p.status = Status.FAIL
            p.reason = f"Отстройка ({p.lower:.0f} А) несовместима с чувствительностью (не более {p.upper:.0f} А) — рассмотреть МТЗ с пуском по напряжению или другую защиту"
        else:
            p.status = Status.OK
            p.reason = f"Допустимый интервал {p.lower:.0f} … {p.upper:.0f} А" if p.upper is not None else f"Не менее {p.lower:.0f} А"
        p.meta = {"b13": "п. 10.2 (10.1)" if a.use_voltage_start else "п. 11.1 (11.1)", "i_nom_a": i_nom}
        res.params.append(p)
        # ── выдержка времени ──
        pt = ParamResult("51.Delay", side, f"Выдержка времени МТЗ {ru}", "с", "time", side=side, group=f"МТЗ {ru}", rounding_dir="up")
        tt = ctx.trace(f"Выдержка времени МТЗ {ru}")
        tt.note("Нижестоящие защиты", f"Наибольшая выдержка времени нижестоящих защит: {t_down:.2f} с ({who}).", "Вып. 13Б п. 10.7, п. 11.3")
        tv = tt.calc("MOD.TIME.COORD", {"t_пред": Var("t_пред", t_down, "с", who), "dt": Var("Δt", dt, "с", "ступень селективности", dt_src)}, title="Выдержка времени по условию согласования")
        pt.calc = pt.lower = tv.value
        pt.trace = tt
        pt.criteria = [Criterion("time", "lower", tv.value, "Согласование по времени с нижестоящими защитами", dt_src, "MOD.TIME.COORD")]
        pt.status = Status.OK if t_down > 0 or side == "LV" else Status.CHECK
        pt.reason = f"t ≥ {t_down:.2f} + {dt:.2f} = {tv.value:.2f} с"
        res.params.append(pt)
        # ── органы напряжения ──
        if a.use_voltage_start:
            self._voltage(ctx, res, side, ru)
        # ── проверки ──
        res.checks += self._checks_side(ctx, side, {f"51.IPickup@{side}": p.calc, f"51.Delay@{side}": pt.calc}, k_v, k_otsn, i_nom_var.value, None, "расчётные", zone_rows_cache=None)

    def _coordination(self, ctx, t, side, dt):
        """Согласование по чувствительности с защитами смежных элементов: I_с.з ≥ k_отс·k_ток·I_с.з.пред (10.2)."""
        net = ctx.p.network
        kc = ctx.norm("K.OTS.MTZ.COORD")
        best = None
        for ln in net.lines:
            if not ln.prot.mtz:
                continue
            if not (ln.side == side or (side == "HV" and ln.side in ("MV", "LV")) or (side == "MV" and ln.side == "LV")):
                continue
            stage = min(ln.prot.mtz, key=lambda s: s.i_a or INF)
            node = f"E_{ln.id}"
            kmax = 0.0
            wc = None
            for role in ("min_kz", "max_kz"):
                for r in ctx.scan_for(side, role, node, "3ph"):
                    lk = r.branches.get(f"LINE_{ln.id}")
                    if lk is None:
                        continue
                    from ..shortcircuit import branch_phase_currents
                    m = ctx.kz.model(r.mode_id, r.tap_key)
                    il = max(abs(x) for x in branch_phase_currents(m, r, f"LINE_{ln.id}", ln.side, "p"))
                    ia = max(abs(x) for x in r.sides[side].i_abc)
                    if il > 1.0 and ia / il > kmax:
                        kmax, wc = ia / il, r
            if wc is None:
                continue
            v = t.calc("B13.10.2", {"k_отс": kc.value, "k_ток": Var("k_ток", kmax, "", f"наибольшее по режимам, КЗ в конце «{ln.name}»"),
                                    "I_пред": Var("I_с.з.пред", stage.i_a, "А", f"МТЗ «{ln.name}»")},
                       title=f"Согласование по чувствительности с МТЗ «{ln.name}» (10.2)")
            if best is None or v.value > best[0]:
                best = (v.value, Criterion(f"coord_{ln.id}", "lower", v.value, f"Согласование по чувствительности с МТЗ «{ln.name}»", kc.ref(ctx.reg.sources), "B13.10.2",
                                           f"k_ток = {kmax:.2f}"))
        return best

    def _voltage(self, ctx, res, side, ru):
        tr, a = ctx.tr, ctx.a
        u_nom = tr.u_nom(side)
        pu = ParamResult("51.UMinPickup", side, f"Напряжение срабатывания органа минимального напряжения {ru}", "кВ", "float", side=side, group=f"МТЗ {ru}", rounding_dir="down")
        t = ctx.trace(f"Напряжение срабатывания органа минимального напряжения {ru}")
        kotu, kvu = ctx.norm("K.OTS.U"), ctx.norm("K.V.U")
        umin, uzap = ctx.norm("U.MIN.SELFSTART"), ctx.norm("U.SELFSTART")
        ctx.note_norm(t, kotu, "k_отс (10.4, 10.5)")
        ctx.note_norm(t, kvu, "k_в реле напряжения (10.4)")
        u1 = t.calc("B13.10.4", {"U_мин": Var("U_мин", umin.value * u_nom, "кВ", "напряжение после отключения внешнего КЗ (0,85·U_ном)", umin.ref(ctx.reg.sources)),
                                 "k_отс": kotu.value, "k_в": kvu.value}, title="Возврат реле после отключения внешнего КЗ (10.4)")
        u2 = t.calc("B13.10.5", {"U_зап": Var("U_зап", uzap.value * u_nom, "кВ", "напряжение самозапуска (0,7·U_ном)", uzap.ref(ctx.reg.sources)), "k_отс": kotu.value},
                    title="Отстройка от напряжения самозапуска (10.5)")
        up = min(u1.value, u2.value)
        pu.upper = up
        pu.calc = up
        pu.criteria = [Criterion("u_reset", "upper", u1.value, "Возврат после отключения КЗ (10.4)", kotu.ref(ctx.reg.sources), "B13.10.4"),
                       Criterion("u_self", "upper", u2.value, "Самозапуск двигателей (10.5)", kotu.ref(ctx.reg.sources), "B13.10.5")]
        # нижняя граница по чувствительности (10.10) — трёхфазное КЗ
        kmain, kback = ctx.norm("KCH.UMIN.MAIN"), ctx.norm("KCH.UMIN.BACKUP")
        lows = []
        for z in [z for z in zones_for(ctx, side) if not z["node"].startswith("E_")]:
            best = None
            for r in ctx.scan_for(side, "max_kz", z["node"], "3ph") + ctx.scan_for(side, "min_kz", z["node"], "3ph"):
                v = min(ppv(r.sides[side].u_abc))
                if best is None or v > best[0]:
                    best = (v, r)
            if best is None:
                continue
            need = kmain if z["main"] else kback
            lo = t.calc("B13.10.10u", {"k_ч": need.value, "U_з_max": Var("U_з.max", best[0], "кВ", f"{z['label']}, режим {best[1].mode_id}, РПН {best[1].tap_key}")},
                        title=f"Нижняя граница по чувствительности органа напряжения: {z['label']}")
            lows.append(lo.value)
            pu.criteria.append(Criterion(f"u_sens_{z['node']}", "lower", lo.value, f"Чувствительность органа напряжения: {z['label']}", need.ref(ctx.reg.sources), "B13.10.10u"))
        pu.lower = max(lows) if lows else None
        pu.trace = t
        if pu.lower is not None and pu.lower > pu.upper:
            pu.status = Status.FAIL
            pu.reason = f"Условия возврата ({pu.upper:.1f} кВ) и чувствительности ({pu.lower:.1f} кВ) несовместимы"
        else:
            pu.status = Status.OK
            pu.reason = f"Допустимый интервал {pu.lower or 0:.1f} … {pu.upper:.1f} кВ (междуфазное, первичное)"
        res.params.append(pu)
        # орган U2 — по норме (10.6)
        n2 = ctx.norm("U2.PICKUP.REL")
        p2 = ParamResult("51.U2Pickup", side, f"Напряжение срабатывания органа U2 {ru}", "кВ", "float", side=side, group=f"МТЗ {ru}", fixed=False, rounding_dir="nearest")
        t2 = ctx.trace(f"Напряжение срабатывания органа U2 {ru}")
        ctx.note_norm(t2, n2, "U_2с.з в долях U_ном (10.6)")
        v = t2.calc("B13.10.6", {"k_u2": n2.value, "U_ном": Var("U_ном", u_nom, "кВ", "междуфазное")}, title="Напряжение срабатывания органа обратной последовательности (10.6)")
        p2.calc = v.value
        p2.trace = t2
        p2.criteria = [Criterion("u2", "target", v.value, "Минимальная уставка фильтра U2 (отстройка от небаланса)", n2.ref(ctx.reg.sources), "B13.10.6")]
        p2.reason = "По опыту эксплуатации обеспечивает отстройку от небаланса в нагрузочном режиме (Вып. 13Б п. 10.4.2)"
        p2.status = Status.OK
        res.params.append(p2)

    # ── проверки ──
    def _checks_side(self, ctx, side, vals, k_v, k_otsn, i_nom, term, label, zone_rows_cache=None) -> list[Check]:
        a = ctx.a
        ru = ctx.side_ru(side)
        out = []
        iset = vals.get(f"51.IPickup@{side}")
        if iset is None:
            return out
        src = ctx.reg.sources
        kmain, kback = ctx.norm("KCH.MTZ.MAIN"), ctx.norm("KCH.MTZ.BACKUP")
        rows, wmin = [], None
        for z in zones_for(ctx, side):
            case = min_current_case(ctx, side, z["node"], "2ph")
            if case is None:
                continue
            imin, r = case
            need = kmain if z["main"] else kback
            kch = imin / iset
            rows.append({"zone": z["label"], "mode": r.mode_id, "tap": r.tap_key, "i_min_a": imin, "k_ch": kch, "k_req": need.value, "main": z["main"], "ratio": kch / need.value})
            if wmin is None or rows[-1]["ratio"] < wmin["ratio"]:
                wmin = dict(rows[-1], need=need)
        if rows:
            need = wmin["need"]
            tr_ = ctx.trace(f"Чувствительность МТЗ {ru} — {label} уставки")
            ctx.note_norm(tr_, need, "Требуемый коэффициент чувствительности")
            tr_.calc("B13.10.8", {"I_к_min": Var("I_к.min", wmin["i_min_a"], "А", f"{wmin['zone']}, режим {wmin['mode']}, РПН {wmin['tap']}"), "I_с_з": Var("I_с.з", iset, "А", "принятая уставка" if label != "расчётные" else "расчётная уставка")},
                     title="Коэффициент чувствительности (10.8)")
            st = Status.OK if wmin["k_ch"] >= need.value else (Status.CHECK if wmin["k_ch"] >= 1.0 else Status.FAIL)
            out.append(Check(f"51.sens@{side}", FID, f"Чувствительность МТЗ {ru}", "sensitivity", st, wmin["k_ch"], need.value, "", "≥",
                             f"k_ч = {wmin['k_ch']:.2f} {'≥' if st == Status.OK else '<'} {need.value:g} — {wmin['zone']} (режим {wmin['mode']}, РПН {wmin['tap']}, двухфазное КЗ)", tr_,
                             {"mode": wmin["mode"], "tap": wmin["tap"], "zone": wmin["zone"], "ftype": "2ph"}, rows, [need.ref(src)], f"51.IPickup@{side}"))
        # отстройка от нагрузки при фактическом k_в терминала
        kvr, kvsrc = ctx.k_reset(term, FID)
        need_i = k_otsn.value * i_nom
        got = iset * kvr
        st = Status.OK if got >= need_i - 1e-9 else Status.FAIL
        out.append(Check(f"51.load@{side}", FID, f"Отстройка МТЗ {ru} от номинального тока (с учётом k_в = {kvr:g})", "requirement", st, got / i_nom, k_otsn.value, "", "≥",
                         f"I_возв = k_в·I_с.з = {got:.0f} А {'≥' if st == Status.OK else '<'} k_отс·I_ном = {need_i:.0f} А (k_в: {kvsrc})", None, {}, [], [k_otsn.ref(src)], f"51.IPickup@{side}"))
        # селективность по времени со смежными защитами (по времятоковым характеристикам)
        tset = vals.get(f"51.Delay@{side}")
        if tset is not None:
            from ..selectivity import check_pair
            from ...model.network import Stage
            dt, dt_src = ctx.dt()
            base = ctx.p.network.base_kv
            own = [Stage(i_a=iset, t_s=tset, curve="definite")]
            i_hi = max([max(abs(x) for x in r.sides[side].i_abc) for role in ("max_kz",) for nd in ctx.tr.sides() for r in ctx.scan_for(side, role, nd, "3ph")] or [iset * 10])
            for te in ctx.p.network.tcc:
                if not te.stages:
                    continue
                if te.role == "upstream" and te.side == side:
                    scale = base[side] / base[te.side]
                    rr = check_pair(own, te.stages, "upstream", dt, iset, max(i_hi, iset * 1.5), scale)
                    kind = "вышестоящей"
                elif te.role == "downstream" and (te.side == side or ["HV", "MV", "LV"].index(te.side) > ["HV", "MV", "LV"].index(side)):
                    scale = base[side] / base[te.side]
                    rr = check_pair(own, te.stages, "downstream", dt, iset, max(i_hi, iset * 1.5), scale)
                    kind = "нижестоящей"
                else:
                    continue
                st = Status.OK if rr["ok"] else Status.FAIL
                mg = rr["margin"]
                txt = (f"Наименьший запас по времени {mg:.2f} с при {rr['at_a']:.0f} А {'≥' if st == Status.OK else '<'} Δt = {dt:.2f} с ({kind} защитой: {te.name})" if mg is not None
                       else f"Смежная защита ({te.name}) не приходит в действие в проверяемом диапазоне токов — конфликта нет")
                out.append(Check(f"51.sel@{side}:{te.id}", FID, f"Селективность по времени МТЗ {ru} с {kind} защитой", "selectivity", st, mg, dt, "с", "≥", txt, None,
                                 {"at_a": rr.get("at_a")}, [], [dt_src], f"51.Delay@{side}"))
        return out

    def recheck(self, ctx: CalcContext, accepted: dict, term: TerminalContext | None = None) -> list[Check]:
        out = []
        k_otsn = ctx.norm("K.OTS.MTZ")
        k_v, _ = ctx.k_reset(term, FID)
        for side in self.sides_used(ctx):
            i_nom = ctx.i_nom_winding(side)
            if ctx.tr.oltc.present and ctx.tr.oltc.side == side:
                i_nom *= ctx.norm("K.RPN.NOM").value
            if not ctx.a.use_voltage_start:
                i_nom = ctx.i_load_max(side)[0] * ctx.a.k_self_start
            out += self._checks_side(ctx, side, accepted, k_v, k_otsn, i_nom, term, "принятые (округлённые)")
            out += self._voltage_check(ctx, side, accepted)
        return out

    def _voltage_check(self, ctx, side, accepted) -> list[Check]:
        out = []
        if not ctx.a.use_voltage_start:
            return out
        kmain, kback = ctx.norm("KCH.UMIN.MAIN"), ctx.norm("KCH.UMIN.BACKUP")
        key = f"51.UMinPickup@{side}"
        if key in accepted:
            u_set = accepted[key]
            rows, wmin = [], None
            for z in [z for z in zones_for(ctx, side) if not z["node"].startswith("E_")]:
                best = None
                for r in ctx.scan_for(side, "max_kz", z["node"], "3ph") + ctx.scan_for(side, "min_kz", z["node"], "3ph"):
                    v = min(ppv(r.sides[side].u_abc))
                    if best is None or v > best[0]:
                        best = (v, r)
                if best is None:
                    continue
                need = kmain if z["main"] else kback
                k = u_set / best[0] if best[0] > 1e-9 else INF
                rows.append({"zone": z["label"], "u_res_kv": best[0], "k_ch": k, "k_req": need.value, "ratio": k / need.value, "mode": best[1].mode_id, "tap": best[1].tap_key})
                if wmin is None or rows[-1]["ratio"] < wmin["ratio"]:
                    wmin = dict(rows[-1], need=need)
            if rows:
                st = Status.OK if wmin["k_ch"] >= wmin["need"].value else (Status.CHECK if wmin["k_ch"] >= 1.0 else Status.FAIL)
                out.append(Check(f"51.usens@{side}", FID, f"Чувствительность органа минимального напряжения МТЗ {ctx.side_ru(side)} (трёхфазные КЗ)", "sensitivity", st, wmin["k_ch"], wmin["need"].value, "", "≥",
                                 f"k_чU = U_с.з/U_з.max = {wmin['k_ch']:.2f} — {wmin['zone']} (10.10)", None, {"zone": wmin["zone"]}, rows, [wmin["need"].ref(ctx.reg.sources)], key))
        key2 = f"51.U2Pickup@{side}"
        if key2 in accepted:
            u2_set = accepted[key2]
            rows, wmin = [], None
            for z in zones_for(ctx, side):
                best = None
                for r in ctx.scan_for(side, "min_kz", z["node"], "2ph"):
                    v = 3 ** 0.5 * abs(r.sides[side].u2)
                    if best is None or v < best[0]:
                        best = (v, r)
                if best is None:
                    continue
                need = kmain if z["main"] else kback
                k = best[0] / u2_set if u2_set > 0 else INF
                rows.append({"zone": z["label"], "u2_min_kv": best[0], "k_ch": k, "k_req": need.value, "ratio": k / need.value, "mode": best[1].mode_id, "tap": best[1].tap_key})
                if wmin is None or rows[-1]["ratio"] < wmin["ratio"]:
                    wmin = dict(rows[-1], need=need)
            if rows:
                st = Status.OK if wmin["k_ch"] >= wmin["need"].value else (Status.CHECK if wmin["k_ch"] >= 1.0 else Status.FAIL)
                out.append(Check(f"51.u2sens@{side}", FID, f"Чувствительность органа U2 МТЗ {ctx.side_ru(side)} (двухфазные КЗ)", "sensitivity", st, wmin["k_ch"], wmin["need"].value, "", "≥",
                                 f"k_чU2 = U_2к.min/U_2с.з = {wmin['k_ch']:.2f} — {wmin['zone']} (10.11)", None, {"zone": wmin["zone"]}, rows, [wmin["need"].ref(ctx.reg.sources)], key2))
        return out
