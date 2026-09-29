"""21 — дистанционная защита АТ от многофазных КЗ (Вып. 13Б, гл. 8 и прил. П7).

Реализованы две ступени защиты, направленные через АТ в сторону противоположного напряжения (ТТ и ТН стороны установки):
    1-я ступень (согласование с 1-ми ступенями защит смежных линий, (8.3)/(8.4)):
        Z_I ≤ Z_ат/(1+β+δ) + (1−α)/(1+β+δ)·Z_л^I/k_ток = 0,87·Z_ат + 0,78·Z_л^I/k_ток,  α = 0,1; β = 0,05; δ = 0,1
        (расчёт для положения РПН с наименьшим Z_ат и наибольшим k_ток — «минимально возможное с учётом регулирования», п. 8.1.8)
    2-я ступень (дальнее резервирование): отстройка от сопротивления нагрузки (8.5)/(8.6), k = k_отс·k_в = 1,25;
        чувствительность k_ч = Z_с.з/Z_к ≥ 1,2 при КЗ в конце зоны резервирования (п. 8.1.12, ПУЭ РК п. 1003), Z_к — измеренное реле сопротивление.
    Выдержки: I — по согласованию с 1-й ступенью линий + Δt; II — с 3-й ступенью линий + Δt (п. 8.1.11).
Измеряемое сопротивление вычисляется по расчёту КЗ: междуфазный контур Z = (U_x − U_y)/(I_x − I_y) в месте установки защиты
(с учётом подпитки, режима и положения РПН). Проверка по току точной работы (8.16) относится к электромеханическим реле и не выполняется.
"""
from __future__ import annotations

import cmath
import math

from ...errors import Status
from ...trace import Var
from ..context import CalcContext, TerminalContext
from ..results import Check, Criterion, FunctionResult, ParamResult
from ..shortcircuit import branch_phase_currents, to_abc
from . import register
from .base import FunctionCalc

FID = "21"
INF = float("inf")
OPP = {"HV": "MV", "MV": "HV"}


def measured_z(r, side: str) -> complex | None:
    """Измеряемое сопротивление (Ом, первичное, на напряжении стороны) — междуфазный контур с наибольшим током."""
    sd = r.sides[side]
    i = [x / 1000.0 for x in sd.i_abc]      # кА
    u = list(sd.u_abc)                      # кВ (фаза-нейтраль)
    best = None
    for x, y in ((1, 2), (0, 1), (2, 0)):
        di = i[x] - i[y]
        if best is None or abs(di) > abs(best[0]):
            best = (di, u[x] - u[y])
    if best is None or abs(best[0]) < 1e-6:
        return None
    return best[1] / best[0]


@register
class F21(FunctionCalc):
    id = FID
    title = "Дистанционная защита (21)"

    def sides_used(self, ctx) -> list[str]:
        out = []
        for s in ("HV", "MV"):
            if s in ctx.tr.sides() and ctx.ct(s, "21", strict=True) is not None and any(v.side == s for v in ctx.p.vts):
                out.append(s)
        return out

    def calculate(self, ctx: CalcContext) -> FunctionResult:
        res = FunctionResult(FID, self.title)
        sides = self.sides_used(ctx)
        if not sides:
            res.missing.append("Нет ТТ и ТН для дистанционной защиты (21) на сторонах ВН/СН")
            return res
        for s in sides:
            self._side(ctx, res, s)
        return res

    def _at_impedance(self, tap, side: str, other: str) -> float:
        """Сопротивление АТ между сторонами (Ом на напряжении стороны установки) в положении РПН."""
        x = tap.x_ohm
        pair = x["H"] + x.get("M", 0.0) if "MV" in tap.u_kv and {side, other} == {"HV", "MV"} else None
        if pair is None:
            return float("nan")
        uh, um = tap.u_kv["HV"], tap.u_kv["MV"]
        return pair if side == "HV" else pair * (um / uh) ** 2

    def _k_tok(self, ctx, side: str, other: str, ln) -> tuple[float, object]:
        node = f"E_{ln.id}"
        best, wc = 0.0, None
        for role in ("max_kz", "min_kz"):
            for r in ctx.scan_for(side, role, node, "3ph", cascade=True):
                lk = r.branches.get(f"LINE_{ln.id}")
                if lk is None:
                    continue
                m = ctx.kz.model(r.mode_id, r.tap_key, True)
                il = max(abs(x) for x in branch_phase_currents(m, r, f"LINE_{ln.id}", node, "p"))
                ia = max(abs(x) for x in r.sides[other].i_abc)
                if il > 1.0 and ia / il > best:
                    best, wc = ia / il, r
        return best, wc

    def _side(self, ctx: CalcContext, res: FunctionResult, side: str):
        a, tr, net = ctx.a, ctx.tr, ctx.p.network
        other = OPP[side]
        ru = ctx.side_ru(side)
        if other not in tr.sides():
            return
        al, be, de = ctx.norm("ALPHA.21"), ctx.norm("BETA.21"), ctx.norm("DELTA.21")
        lines = [ln for ln in net.lines if ln.side == other and ln.prot.dist]
        dt, dt_src = ctx.dt()
        # ── 1-я ступень ──
        p1 = ParamResult("21.Z1", side, f"Сопротивление срабатывания 1-й ступени дистанционной защиты {ru} (в сторону {other})", "Ом", "float", side=side, group=f"Дистанционная защита {ru}", rounding_dir="down")
        t1 = ctx.trace(f"Сопротивление срабатывания 1-й ступени {ru}")
        for n, title in ((al, "α — погрешность ТТ и реле в сторону уменьшения зоны (8.3)/(8.4)"), (be, "β — погрешность ТН (8.3)/(8.4)"), (de, "δ — неточность расчёта и запас (8.3)/(8.4)")):
            ctx.note_norm(t1, n, title)
        if not lines:
            res.missing.append(f"Дист. защита {ru}: нет данных о 1-х ступенях дистанционных защит смежных линий стороны {other} (для согласования)")
        best = None
        for ln in lines:
            z_l1 = ln.prot.dist[0].z_ohm
            if not z_l1:
                continue
            ktok, wcase = self._k_tok(ctx, side, other, ln)
            if wcase is None:
                continue
            for tap in ctx.taps():
                z_at = self._at_impedance(tap, side, other)
                if z_at != z_at:
                    continue
                # приведение сопротивления линии к напряжению стороны установки защиты (коэффициент трансформации АТ в положении РПН)
                nr = (tap.u_kv[side] / tap.u_kv[other]) ** 2
                z_line_s = z_l1 * nr
                val = (z_at / (1 + be.value + de.value)) + ((1 - al.value) / (1 + be.value + de.value)) * z_line_s / ktok
                if best is None or val < best[0]:
                    best = (val, ln, tap, z_at, z_line_s, ktok, wcase, z_l1)
        if best:
            val, ln, tap, z_at, z_line_s, ktok, wcase, z_l1 = best
            t1.note("Расчётное положение РПН", f"Минимальный допустимый Z_I получен для положения РПН «{tap.label()}» (наименьшее сопротивление АТ, п. 8.1.8) и линии «{ln.name}».", "Вып. 13Б п. 8.1.8")
            v = t1.calc("B13.8.3", {"Z_ат": Var("Z_ат", z_at, "Ом", f"сопротивление АТ {side}–{other}, {tap.label()}"), "Z_л1": Var("Z_л^I·(U_S/U_R)²", z_line_s, "Ом", f"I ступень «{ln.name}» ({z_l1:g} Ом), приведено к стороне {side}"),
                                   "k_ток": Var("k_ток", ktok, "", f"наибольший по режимам, КЗ в конце «{ln.name}», режим {wcase.mode_id}, РПН {wcase.tap_key}"),
                                   "alpha": al.value, "beta": be.value, "delta": de.value}, title=f"Сопротивление срабатывания 1-й ступени по согласованию с 1-й ступенью «{ln.name}» ((8.3)/(8.4))")
            p1.calc = p1.upper = v.value
            p1.criteria = [Criterion("coord", "upper", v.value, f"Согласование с 1-й ступенью защиты «{ln.name}»", al.ref(ctx.reg.sources), "B13.8.3", f"{tap.label()}, k_ток={ktok:.2f}")]
            # нижняя граница (информативно): охват АТ — 1-я ступень должна охватывать часть обмоток АТ
            p1.lower = 0.0
            p1.status = Status.OK
            p1.reason = f"Не более {v.value:.2f} Ом (первичное, на стороне {side})"
            p1.rounding_dir = "down"
            p1.trace = t1
            p1.meta = {"b13": "п. 8.1.8 (8.3)/(8.4)", "line": ln.id, "tap": tap.key, "k_tok": ktok}
            res.params.append(p1)
            z1_upper = v.value
        else:
            z1_upper = None
        # ── 2-я ступень ──
        p2 = ParamResult("21.Z2", side, f"Сопротивление срабатывания 2-й ступени дистанционной защиты {ru}", "Ом", "float", side=side, group=f"Дистанционная защита {ru}", rounding_dir="down")
        t2 = ctx.trace(f"Сопротивление срабатывания 2-й ступени {ru}")
        kl = ctx.norm("K.LOAD.21")
        ctx.note_norm(t2, kl, "k = k_отс·k_в (8.5), (8.6)")
        il, mid = ctx.i_load_max(side, ("load", "post_accident"))
        un = tr.u_nom(side)
        zload = t2.calc("MOD.21.ZLOAD", {"U_мин": Var("U_мин", a.u_work_min_pu * un, "кВ", f"{a.u_work_min_pu:g}·U_ном (допущение проекта)"), "I_нагр": Var("I_нагр", il, "А", f"режим {mid}")},
                        title="Минимальное сопротивление нагрузки в месте установки защиты (послеаварийный режим)")
        phi_diff = a.max_torque_deg - a.load_pf_deg
        aa = a.z_offset_a
        if abs(aa) < 1e-9:
            up = t2.calc("B13.8.6", {"Z_нагр": zload, "k": kl.value, "cosd": Var("cos(φ_мч − φ_нагр)", math.cos(math.radians(phi_diff)), "", f"φ_мч = {a.max_torque_deg:g}°, φ_нагр = {a.load_pf_deg:g}°")},
                         title="Отстройка от сопротивления нагрузки, характеристика через начало координат (8.6)")
        else:
            c = math.cos(math.radians(phi_diff))
            up = t2.calc("B13.8.5", {"Z_нагр": zload, "k": kl.value, "a": aa, "c": Var("cos(φ_мч − φ_нагр)", c, "")},
                         title="Отстройка от сопротивления нагрузки, характеристика со смещением (8.5)")
        crit2 = [Criterion("load", "upper", up.value, "Отстройка от сопротивления нагрузки", kl.ref(ctx.reg.sources), "B13.8.6" if abs(aa) < 1e-9 else "B13.8.5")]
        # чувствительность: измеренное сопротивление при КЗ в конце зоны резервирования
        need = ctx.norm("KCH.21.ZONE2")
        far = [ln for ln in net.lines if ln.side == other]
        nodes = [(f"E_{ln.id}", f"конец «{ln.name}»") for ln in far] or [(other, f"шины {other}")]
        zmax, zc = 0.0, None
        for node, label in nodes:
            for role in ("min_kz", "max_kz"):
                for r in ctx.scan_for(side, role, node, "2ph", cascade=True):
                    z = measured_z(r, side)
                    if z is not None and abs(z) > zmax:
                        zmax, zc = abs(z), (label, r)
        low = None
        if zc:
            lab, r = zc
            lv = t2.calc("B13.8.12u", {"k_ч": need.value, "Z_к": Var("Z_к", zmax, "Ом", f"измеренное сопротивление, КЗ: {lab}, режим {r.mode_id}, РПН {r.tap_key}")},
                         title="Нижняя граница по чувствительности при КЗ в конце зоны резервирования (каскадное отключение, п. 8.1.12)")
            crit2.append(Criterion("sens", "lower", lv.value, f"Чувствительность при КЗ: {lab}", need.ref(ctx.reg.sources), "B13.8.12u", f"{r.mode_id}/{r.tap_key}"))
            low = lv.value
        p2.upper = up.value
        p2.lower = low
        p2.calc = up.value
        p2.criteria = crit2
        p2.trace = t2
        if low is not None and low > up.value:
            p2.status = Status.FAIL
            p2.reason = f"Необходимый охват {low:.2f} Ом превышает допустимый по нагрузке {up.value:.2f} Ом — резервирование не обеспечивается; рассмотреть смещение характеристики/иное выполнение"
        else:
            p2.status = Status.OK
            p2.reason = f"Допустимый интервал {low or 0:.2f} … {up.value:.2f} Ом"
        res.params.append(p2)
        # смещение
        po = ParamResult("21.Z2Offset", side, f"Смещение характеристики 2-й ступени {ru}", "о.е.", "float", calc=aa, fixed=True, side=side, group=f"Дистанционная защита {ru}")
        po.trace = ctx.trace("Смещение характеристики")
        po.trace.note("Инженерный выбор", "Смещение a = 0 (характеристика через начало координат) — параметр «Исходные данные защит». Смещение в первый квадрант допустимо при 0,1 ≤ a ≤ 0,5 и обеспечении «зацепления» ступеней (Вып. 13Б п. 8.1.9, (8.9)/(8.10)).", "Вып. 13Б п. 8.1.9")
        po.status = Status.OK
        po.reason = "Параметр выбирается проектом"
        res.params.append(po)
        # выдержки времени
        t_i = max([ln.prot.dist[0].t_s for ln in lines], default=0.0)
        t_iii = max([ln.prot.dist[-1].t_s for ln in lines], default=0.0)
        for pid, tdown, lab in (("21.Z1Delay", t_i, "1-й ступени линий"), ("21.Z2Delay", t_iii, "3-й ступени линий")):
            pt = ParamResult(pid, side, f"Выдержка времени {'1' if pid == '21.Z1Delay' else '2'}-й ступени {ru}", "с", "time", side=side, group=f"Дистанционная защита {ru}", rounding_dir="up")
            tt = ctx.trace(f"Выдержка времени {'1' if pid == '21.Z1Delay' else '2'}-й ступени дистанционной защиты {ru}")
            tt.note("Смежные защиты", f"Выдержка времени {lab}: {tdown:.2f} с.", "Вып. 13Б п. 8.1.11")
            tv = tt.calc("MOD.TIME.COORD", {"t_пред": Var("t_пред", tdown, "с", lab), "dt": Var("Δt", dt, "с", "ступень селективности", dt_src)}, title="Выдержка времени по согласованию (п. 8.1.11)")
            pt.calc = pt.lower = tv.value
            pt.trace = tt
            pt.criteria = [Criterion("time", "lower", tv.value, f"Согласование по времени с {lab}", dt_src, "MOD.TIME.COORD")]
            pt.status = Status.OK if lines else Status.CHECK
            pt.reason = f"t ≥ {tdown:.2f} + {dt:.2f} = {tv.value:.2f} с"
            res.params.append(pt)
        z2 = p2.calc
        res.checks += self._checks(ctx, side, {f"21.Z1@{side}": p1.calc, f"21.Z2@{side}": z2}, z1_upper, up.value, None, "расчётные")

    def _checks(self, ctx, side, vals, z1_upper, z2_upper, term, label) -> list[Check]:
        out = []
        ru = ctx.side_ru(side)
        other = OPP[side]
        z2 = vals.get(f"21.Z2@{side}")
        need = ctx.norm("KCH.21.ZONE2")
        net = ctx.p.network
        if z2 is not None:
            far = [ln for ln in net.lines if ln.side == other]
            nodes = [(f"E_{ln.id}", f"конец «{ln.name}»") for ln in far] or [(other, f"шины {other}")]
            rows, wmin = [], None
            for node, lab in nodes:
                zmax, zc = 0.0, None
                for role in ("min_kz", "max_kz"):
                    for r in ctx.scan_for(side, role, node, "2ph", cascade=True):
                        z = measured_z(r, side)
                        if z is not None and abs(z) > zmax:
                            zmax, zc = abs(z), r
                if zc is None:
                    continue
                k = z2 / zmax
                rows.append({"zone": lab, "mode": zc.mode_id, "tap": zc.tap_key, "z_meas_ohm": zmax, "k_ch": k, "k_req": need.value, "ratio": k / need.value})
                if wmin is None or k < wmin["k_ch"]:
                    wmin = rows[-1]
            if wmin:
                tr_ = ctx.trace(f"Чувствительность 2-й ступени дистанционной защиты {ru} — {label} уставки")
                ctx.note_norm(tr_, need, "Требуемый коэффициент чувствительности")
                tr_.calc("B13.8.12", {"Z_с_з": Var("Z_с.з", z2, "Ом"), "Z_к": Var("Z_к", wmin["z_meas_ohm"], "Ом", f"{wmin['zone']}, режим {wmin['mode']}, РПН {wmin['tap']}")}, title="Коэффициент чувствительности по сопротивлению (п. 8.1.12)")
                st = Status.OK if wmin["k_ch"] >= need.value else (Status.CHECK if wmin["k_ch"] >= 1.0 else Status.FAIL)
                out.append(Check(f"21.sens@{side}", FID, f"Чувствительность 2-й ступени дистанционной защиты {ru}", "sensitivity", st, wmin["k_ch"], need.value, "", "≥",
                                 f"k_ч = {wmin['k_ch']:.2f} {'≥' if st == Status.OK else '<'} {need.value:g} — {wmin['zone']} (режим {wmin['mode']}, РПН {wmin['tap']})", tr_,
                                 {"mode": wmin["mode"], "tap": wmin["tap"], "zone": wmin["zone"], "ftype": "2ph"}, rows, [need.ref(ctx.reg.sources)], f"21.Z2@{side}"))
            # нагрузка
            if z2_upper is not None:
                st = Status.OK if z2 <= z2_upper + 1e-9 else Status.FAIL
                out.append(Check(f"21.load@{side}", FID, f"Отстройка 2-й ступени дистанционной защиты {ru} от нагрузки", "requirement", st, z2, z2_upper, "Ом", "≤",
                                 f"Z_с.з = {z2:.2f} Ом {'≤' if st == Status.OK else '>'} допустимого по нагрузке {z2_upper:.2f} Ом (8.5)/(8.6)", None, {}, [], [ctx.norm("K.LOAD.21").ref(ctx.reg.sources)], f"21.Z2@{side}"))
        z1 = vals.get(f"21.Z1@{side}")
        if z1 is not None and z1_upper is not None:
            st = Status.OK if z1 <= z1_upper + 1e-9 else Status.FAIL
            out.append(Check(f"21.coord@{side}", FID, f"Согласование 1-й ступени дистанционной защиты {ru} с 1-ми ступенями линий", "coordination", st, z1, z1_upper, "Ом", "≤",
                             f"Z_с.з = {z1:.2f} Ом {'≤' if st == Status.OK else '>'} {z1_upper:.2f} Ом ((8.3)/(8.4))", None, {}, [], [ctx.norm("ALPHA.21").ref(ctx.reg.sources)], f"21.Z1@{side}"))
        return out

    def recheck(self, ctx: CalcContext, accepted: dict, term: TerminalContext | None = None) -> list[Check]:
        out = []
        r = self.calculate(ctx)      # верхние границы (условия согласования и нагрузки) не зависят от принятых уставок
        for side in self.sides_used(ctx):
            z1p = r.param(f"21.Z1@{side}")
            z2p = r.param(f"21.Z2@{side}")
            out += self._checks(ctx, side, accepted, z1p.upper if z1p else None, z2p.upper if z2p else None, term, "принятые (округлённые)")
        return out
