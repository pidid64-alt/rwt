"""87T — дифференциальная защита трансформатора / автотрансформатора (современная реализация).

Физические критерии Выпуска 13Б (гл. 2–3) реализуются не буквально (числа витков НТТ, МДС срабатывания),
а через универсальную функцию 87T с торможением:

    13Б (2.1)  I_с.з ≥ k_отс·I_нб.расч          → порог ветви a и наклоны s1, s2 (отстройка от небаланса при внешних КЗ);
    13Б (2.3)–(2.6) I_нб = I' + I'' + I'''      → I' = k_апер·k_одн·ε·I_к (погрешность ТТ), I'' = регулирование напряжения (РПН),
                                                   I''' = погрешность выравнивания токов сторон;
    13Б (2.2)  I_с.з ≥ k·k_выг·I_ном            → блокировка по 2-й гармонике (либо, по выбору проекта, отстройка порогом);
    13Б п. 2.1.4 (2.7)–(2.11) «оптимальное напряжение» → расчётное напряжение выравнивания U_set (среднее по току диапазона РПН);
    13Б (2.22)–(2.26) k_ч ≥ 2                   → проверка чувствительности по характеристике (при КЗ на выводах, ПУЭ РК п. 999).

Универсальная характеристика:  I_хар(x) = max(I_диф>, s1·(x − b1), s2·(x − b2)),  x = ½·Σ|I_i| (о.е. I_nO).
Эквивалентность старой методики и современной функции НЕ утверждается автоматически: соответствие физических
критериев показано в режиме «13Б vs современная РЗА» (rza.calc.b13).
"""
from __future__ import annotations

import cmath
import math

from ...errors import Status
from ...trace import Var
from ..context import CalcContext, TerminalContext
from ..results import Check, Criterion, FunctionResult, ParamResult
from ..shortcircuit import to_abc, to_seq
from . import register
from .base import FunctionCalc

FID = "87T"
INF = float("inf")


def char_value(x: float, P: float, s1: float, b1: float, s2: float, b2: float) -> float:
    """Порог срабатывания (о.е. I_nO) при среднем тормозном токе x."""
    return max(P, s1 * (x - b1), s2 * (x - b2))


def eps_at(x: float, x_l: float, x_max: float, eps_lin: float, eps_ct: float) -> float:
    """Полная погрешность ТТ при сквозном токе x (о.е.): ε_лин при x ≤ x_лин, линейно растёт до ε при наибольшем внешнем КЗ
    (Вып. 13Б (2.4) принимает ε при I_к.макс; при меньших токах насыщение ТТ меньше)."""
    if x_max <= x_l + 1e-9:
        return eps_lin if x <= x_l else eps_ct
    f = min(1.0, max(0.0, (x - x_l) / (x_max - x_l)))
    return eps_lin + (eps_ct - eps_lin) * f


def x_max_ext(ext: list[dict]) -> float:
    return max((max(c["res"]) for c in ext), default=0.0)


def grounded(tr, side: str) -> bool:
    w = tr.w(side)
    return w.connection.upper().startswith("Y") and w.neutral != "isolated"


def balancing(ctx: CalcContext, trace=None, override: dict | None = None) -> dict:
    """Расчётные напряжения выравнивания сторон и номинальные токи объекта (I_nO по сторонам)."""
    tr, a = ctx.tr, ctx.a
    sides = tr.sides()
    s_ref = max(tr.s_winding(s) for s in sides)
    u_set = {s: tr.u_nom(s) for s in sides}
    out = {"s_ref": s_ref, "u_set": u_set, "regulated": None, "dU": 0.0, "u_min": None, "u_max": None}
    if tr.oltc.present:
        R = tr.oltc.side
        u_min = tr.u_side_at(R, tr.oltc.pos_min())
        u_max = tr.u_side_at(R, tr.oltc.pos_max())
        if a.ref_tap == "opt":
            if trace is not None:
                u_set[R] = trace.calc("MOD.87T.USET", {"U_max": Var("U_max", u_max, "кВ", "напряжение регулируемой обмотки в положении max"),
                                                        "U_min": Var("U_min", u_min, "кВ", "напряжение в положении min")},
                                      title=f"Расчётное напряжение выравнивания стороны {R}").value
            else:
                u_set[R] = 2 * u_max * u_min / (u_max + u_min)
        elif a.ref_tap == "mid":
            u_set[R] = 0.5 * (u_min + u_max)
        out.update(regulated=R, u_min=u_min, u_max=u_max,
                   dU=max(2 * abs(u_set[R] / u_max - 1) / (u_set[R] / u_max + 1), 2 * abs(u_set[R] / u_min - 1) / (u_set[R] / u_min + 1)))
    if override:
        for k, v in (override.get("u_set") or {}).items():
            if k in u_set:
                u_set[k] = v
        if out["regulated"]:
            R = out["regulated"]
            u_min, u_max = out["u_min"], out["u_max"]
            out["dU"] = max(2 * abs(u_set[R] / u_max - 1) / (u_set[R] / u_max + 1), 2 * abs(u_set[R] / u_min - 1) / (u_set[R] / u_min + 1))
    out["i_n"] = {s: tr.i_nom(s, s_ref, u_set[s]) for s in sides}
    return out


def compensate(tr, bal: dict, side: str, i_abc) -> tuple:
    """Компенсация группы соединения и нулевой последовательности (как в терминале), нормирование на I_nO стороны."""
    w = tr.w(side)
    i0, i1, i2 = to_seq(*i_abc)
    if grounded(tr, side) or w.connection.upper().startswith("D"):
        i0 = 0j      # исключение тока нулевой последовательности (заземлённая обмотка)
    th = math.radians(((12 - w.clock) % 12) * 30.0)
    i1 = i1 * cmath.exp(-1j * th)
    i2 = i2 * cmath.exp(1j * th)
    return tuple(x / bal["i_n"][side] for x in to_abc(i0, i1, i2))


def diff_res(tr, bal: dict, r) -> tuple[list, list]:
    comp = {s: compensate(tr, bal, s, r.sides[s].i_abc) for s in tr.sides()}
    diff = [abs(sum(comp[s][k] for s in comp)) for k in range(3)]
    res = [0.5 * sum(abs(comp[s][k]) for s in comp) for k in range(3)]
    return diff, res


def external_cases(ctx: CalcContext, bal: dict) -> list[dict]:
    key = ("87T.ext", tuple(sorted(bal["u_set"].items())))
    if key in ctx._cache:
        return ctx._cache[key]
    tr = ctx.tr
    cases = []
    for s in tr.sides():
        types = ["3ph", "2ph"] + (["1ph"] if grounded(tr, s) else [])
        for ft in types:
            for r in ctx.scan("max_kz", s, ft):
                diff, res = diff_res(tr, bal, r)
                cases.append({"r": r, "node": s, "ftype": ft, "diff": diff, "res": res})
    ctx._cache[key] = cases
    return cases


def internal_cases(ctx: CalcContext, bal: dict) -> list[dict]:
    key = ("87T.int", tuple(sorted(bal["u_set"].items())))
    if key in ctx._cache:
        return ctx._cache[key]
    tr = ctx.tr
    cases, seen = [], set()
    n_std, n_red = ctx.norm("KCH.87T"), ctx.norm("KCH.87T.REDUCED")
    for s in tr.sides():
        types = ["2ph"] + (["1ph"] if grounded(tr, s) else [])
        for ft in types:
            for role in ("min_kz", "energization"):
                for r in ctx.scan(role, f"T_{s}", ft):
                    k = (r.mode_id, r.tap_key, r.node, r.ftype)
                    if k in seen or r.i_fault_abs() < 1.0:
                        continue
                    seen.add(k)
                    mode = ctx.p.mode(r.mode_id)
                    energ = "energization" in mode.roles
                    reduced = energ or (s == "LV" and tr.s_nom_mva < 80.0)
                    nrm = n_red if reduced else n_std
                    diff, res = diff_res(tr, bal, r)
                    cases.append({"r": r, "node": f"T_{s}", "side": s, "ftype": ft, "diff": diff, "res": res, "k_req": nrm.value,
                                  "norm": nrm, "reduced_reason": ("режим опробования (включение под напряжение)" if energ else "КЗ на выводах НН, S < 80 МВА") if reduced else ""})
    ctx._cache[key] = cases
    return cases


def _params(accepted_or_calc: dict) -> tuple:
    g = accepted_or_calc.get
    return (g("87T.IdiffPickup"), g("87T.Slope1"), g("87T.BasePoint1"), g("87T.Slope2"), g("87T.BasePoint2"), g("87T.HighSet"))


@register
class F87T(FunctionCalc):
    id = FID
    title = "Дифференциальная защита трансформатора (87T)"

    # ═════════════════════════ расчёт ═════════════════════════
    def calculate(self, ctx: CalcContext) -> FunctionResult:
        tr, a = ctx.tr, ctx.a
        res = FunctionResult(FID, self.title)
        missing = res.missing
        for s in tr.sides():
            if ctx.ct(s, "87T", strict=True) is None:
                missing.append(f"Нет ТТ дифференциальной защиты на стороне {s}")
        if missing:
            return res
        t0 = ctx.trace("Исходные данные и выравнивание токов сторон (87T)")
        bal = balancing(ctx, t0)
        res.meta["balancing"] = {"s_ref_mva": bal["s_ref"], "u_set_kv": bal["u_set"], "i_n_a": bal["i_n"], "regulated": bal["regulated"],
                                 "u_min_kv": bal["u_min"], "u_max_kv": bal["u_max"], "dU": bal["dU"]}
        # соответствие сторон ТТ
        ctm = {}
        for s in tr.sides():
            ct = ctx.ct(s, "87T")
            ctm[s] = {"ct_id": ct.id, "ratio": ct.ratio, "i2": ct.i2_a, "i_n_a": bal["i_n"][s], "matching": bal["i_n"][s] / ct.i1_a,
                      "clock": tr.w(s).clock, "grounded": grounded(tr, s), "connection": tr.w(s).connection}
        res.meta["sides"] = ctm
        for s, m in ctm.items():
            if not (0.25 <= m["matching"] <= 4.0):
                res.warnings.append(f"Сторона {s}: отношение I_nO/I_1н ТТ = {m['matching']:.2f} — вне рекомендуемого диапазона 0,25…4 (ухудшение точности приведения токов)")

        n_stab = ctx.norm("K.OTS.87T.UNB")
        k_stab = a.k_stab if a.k_stab else n_stab.value
        ext = external_cases(ctx, bal)
        inn = internal_cases(ctx, bal)
        if not ext or not inn:
            missing.append("Не получены расчёты КЗ для внешних/внутренних повреждений (проверьте режимы и схему)")
            return res

        # ── I_диф> ──
        P = self._pickup(ctx, res, bal, k_stab, n_stab, inn)
        # ── наклон 1 ──
        s1 = self._slope1(ctx, res, bal, k_stab, n_stab)
        b1 = ParamResult("87T.BasePoint1", "", PFM_TITLE("87T.BasePoint1"), "о.е. I_nO", "float", calc=a.bp1_pu, fixed=True, group="Характеристика")
        b1.trace = ctx.trace("Опорная точка 1")
        b1.trace.note("Инженерный выбор", "Принята 0 — начало наклона 1 в нуле оси торможения (значение по умолчанию терминала Siemens 7UT6 — 0,00 I/InO).")
        b1.reason = "Инженерный выбор; не вычисляется по данным сети"
        b1.status = Status.OK
        s2, b2 = self._slope2(ctx, res, bal, k_stab, n_stab, ext, s1.calc, a.bp1_pu)
        hs = self._highset(ctx, res, bal, ext, inn)
        res.params += [P, s1, b1, s2, b2, hs]
        res.params += self._fixed_params(ctx)
        # ── проверки для расчётных значений ──
        calc_vals = {"87T.IdiffPickup": P.calc, "87T.Slope1": s1.calc, "87T.BasePoint1": a.bp1_pu, "87T.Slope2": s2.calc,
                     "87T.BasePoint2": b2.calc, "87T.HighSet": hs.calc}
        res.checks += self._checks(ctx, bal, calc_vals, ext, inn, k_stab, n_stab, None, "расчётные")
        for p in res.params:
            if p.pfm_id in ("87T.IdiffPickup", "87T.Slope1", "87T.Slope2", "87T.HighSet") and p.status == Status.OK:
                # статус параметра по критериям определён внутри; здесь только сводка
                pass
        return res

    # ── параметры ──
    def _pickup(self, ctx, res, bal, k_stab, n_stab, inn) -> ParamResult:
        tr, a = ctx.tr, ctx.a
        pr = ParamResult("87T.IdiffPickup", "", PFM_TITLE("87T.IdiffPickup"), "о.е. I_nO", "float", group="Характеристика", rounding_dir="up")
        t = ctx.trace("Минимальный дифференциальный ток срабатывания I_диф>")
        ctx.note_norm(t, n_stab, "Коэффициент отстройки k_отс (Вып. 13Б (2.1))")
        i0 = (tr.i0_pct or 0.0) / 100.0
        if bal["regulated"]:
            dU = t.calc("MOD.87T.DU_EFF", {"U_set": Var("U_set", bal["u_set"][bal["regulated"]], "кВ"), "U_max": bal["u_max"], "U_min": bal["u_min"]},
                        title="Погрешность регулирования напряжения (эквивалент составляющей I″ в (2.5))")
        else:
            dU = Var("ΔU_рег", 0.0, "о.е.")
        low1 = t.calc("MOD.87T.PICKUP_LOAD", {"k_отс": k_stab, "dU": dU, "eps_нагр": a.eps_load, "df": a.delta_f, "i0": i0, "I_нагр": 1.0},
                      title="Отстройка от токов небаланса в нагрузочном режиме при номинальном токе")
        crit = [Criterion("load_unb", "lower", low1.value, "Отстройка от небаланса при номинальной нагрузке",
                          n_stab.ref(ctx.reg.sources), "MOD.87T.PICKUP_LOAD")]
        lowers = [low1.value]
        if a.inrush_strategy == "pickup":
            nk = ctx.norm("K.OTS.87T.INRUSH")
            ctx.note_norm(t, nk, "Коэффициент k при отстройке от броска намагничивающего тока")
            k_vyg = tr.alpha() if tr.is_auto() else 1.0
            low2 = t.calc("B13.2.2", {"k": nk.value, "k_выг": k_vyg, "I_ном": 1.0}, title="Отстройка от броска намагничивающего тока порогом (Вып. 13Б (2.2))")
            crit.append(Criterion("inrush", "lower", low2.value, "Отстройка от броска намагничивающего тока (без блокировки по гармоникам)", nk.ref(ctx.reg.sources), "B13.2.2"))
            lowers.append(low2.value)
        else:
            t.note("Бросок намагничивающего тока", "Отстройка обеспечивается блокировкой по 2-й гармонике (87T.Inrush2ndHarm), а не током срабатывания; критерий (2.2) Вып. 13Б порогом не применяется. "
                   "Физический критерий сохраняется: терминал не должен срабатывать при включении ненагруженного АТ под напряжение — проверяется при наладке.")
        uppers, ups = [], []
        s_typ_pu = tr.s_typ() / tr.s_nom_mva
        if tr.s_nom_mva >= 63.0:
            n1 = ctx.norm("I87T.PICKUP.AT")
            if tr.is_auto():
                up1 = t.calc("MOD.87T.PUE_TYP", {"S_тип": tr.s_typ(), "S_ном": tr.s_nom_mva}, title="Ток типовой мощности АТ в долях I_ном (ПУЭ РК п. 999, пп. 4))")
                crit.append(Criterion("pue_typ", "upper", up1.value * n1.value, "Ток срабатывания без торможения менее тока типовой мощности АТ",
                                      n1.ref(ctx.reg.sources), "MOD.87T.PUE_TYP", "строго менее"))
                uppers.append(up1.value * n1.value)
            else:
                crit.append(Criterion("pue_nom", "upper", 1.0, "Ток срабатывания без торможения менее номинального", n1.ref(ctx.reg.sources), "", "строго менее"))
                uppers.append(1.0)
        elif tr.s_nom_mva >= 25.0:
            n1 = ctx.norm("I87T.PICKUP.TR25")
            crit.append(Criterion("pue_1_5", "upper", n1.value, "Ток срабатывания без торможения не более 1,5 I_ном", n1.ref(ctx.reg.sources)))
            uppers.append(n1.value)
        # чувствительность (плоская часть характеристики)
        worst = None
        for c in inn:
            v = max(c["diff"]) / c["k_req"]
            if worst is None or v < worst[0]:
                worst = (v, c)
        if worst:
            c = worst[1]
            up2 = t.calc("MOD.87T.SENS_PICKUP", {"I_диф_min": max(c["diff"]), "k_ч": c["k_req"]},
                         title=f"Верхняя граница по чувствительности при КЗ на выводе {c['side']} ({c['ftype']}, режим {c['r'].mode_id}, РПН {c['r'].tap_key})")
            crit.append(Criterion("sens_flat", "upper", up2.value, "Чувствительность к КЗ на выводах (плоская часть характеристики)", c["norm"].ref(ctx.reg.sources), "MOD.87T.SENS_PICKUP",
                                  "наихудший случай: " + f"{c['r'].mode_id}/{c['r'].tap_key}/{c['node']}/{c['ftype']}"))
            uppers.append(up2.value)
        pr.criteria = crit
        pr.lower = max(lowers)
        pr.upper = min(uppers) if uppers else None
        pr.calc = pr.lower
        pr.trace = t
        if pr.upper is not None and pr.lower > pr.upper:
            pr.status = Status.FAIL
            pr.reason = f"Нижняя граница {pr.lower:.3f} превышает верхнюю {pr.upper:.3f}: чувствительность и отстройка несовместимы"
        else:
            pr.status = Status.OK
            pr.reason = f"Допустимый интервал {pr.lower:.3f} … {pr.upper:.3f} о.е." if pr.upper is not None else f"Не менее {pr.lower:.3f} о.е."
        pr.meta = {"b13": "п. 2.1.2.1 (2.1), п. 2.1.2.2 (2.2); для ДЗТ-11 — п. 3.1.2"}
        return pr

    def _slope1(self, ctx, res, bal, k_stab, n_stab) -> ParamResult:
        a = ctx.a
        pr = ParamResult("87T.Slope1", "", PFM_TITLE("87T.Slope1"), "о.е.", "float", group="Характеристика", rounding_dir="up")
        t = ctx.trace("Наклон 1-го участка характеристики")
        ctx.note_norm(t, n_stab, "Коэффициент отстройки k_отс")
        dU = t.calc("MOD.87T.DU_EFF", {"U_set": bal["u_set"][bal["regulated"]], "U_max": bal["u_max"], "U_min": bal["u_min"]},
                    title="Погрешность регулирования напряжения") if bal["regulated"] else Var("ΔU_рег", 0.0, "о.е.")
        low = t.calc("MOD.87T.SLOPE1", {"k_отс": k_stab, "eps_лин": a.eps_lin, "dU": dU, "df": a.delta_f},
                     title="Наклон по сумме токовых погрешностей в области умеренных токов")
        pr.calc = pr.lower = low.value
        pr.criteria = [Criterion("slope1", "lower", low.value, "Отстройка от погрешностей ТТ и РПН в области умеренных токов", n_stab.ref(ctx.reg.sources), "MOD.87T.SLOPE1")]
        pr.trace = t
        pr.reason = f"Не менее {low.value:.3f} (универсальная конвенция I_торм = ½Σ|I|)"
        pr.meta = {"b13": "п. 2.1.3, (2.3)–(2.5): составляющие небаланса от погрешности ТТ и РПН"}
        return pr

    def _slope2(self, ctx, res, bal, k_stab, n_stab, ext, s1, b1):
        a = ctx.a
        pr = ParamResult("87T.Slope2", "", PFM_TITLE("87T.Slope2"), "о.е.", "float", group="Характеристика", rounding_dir="up")
        pb = ParamResult("87T.BasePoint2", "", PFM_TITLE("87T.BasePoint2"), "о.е. I_nO", "float", group="Характеристика", rounding_dir="nearest")
        t = ctx.trace("Наклон 2-го участка характеристики")
        ctx.note_norm(t, n_stab, "Коэффициент отстройки k_отс")
        xm = x_max_ext(ext)
        xl = a.x_lin_pu
        t.note("Модель погрешности ТТ и излом характеристики", f"Излом характеристики принят при сквозном токе x_лин = {xl:g} о.е. (предел линейного режима ТТ; допущение проекта). Полная погрешность ТТ: ε_лин = {a.eps_lin:g} до x_лин, "
               f"далее растёт линейно до ε = {a.eps_ct:g} при наибольшем токе внешнего КЗ ({xm:.2f} о.е.) — как в Вып. 13Б (2.4) для I_к.макс.", "Вып. 13Б п. 2.1.3, (2.4); инженерное допущение")
        need, wc = 0.0, None
        for c in ext:
            for k in range(3):
                x, d = c["res"][k], c["diff"][k]
                if x <= xl + 1e-6:
                    continue
                e = a.k_aper * a.k_odn * eps_at(x, xl, xm, a.eps_lin, a.eps_ct) + a.delta_f
                unb = d + e * x
                req = (k_stab * unb - s1 * (xl - b1)) / (x - xl)
                if req > need:
                    need, wc = req, (c, k, x, d, unb, e)
        s2 = max(s1, need)
        if wc:
            c, k, x, d, unb, e = wc
            ev = t.calc("MOD.87T.EPS_X", {"eps_лин": a.eps_lin, "eps": a.eps_ct, "x": Var("x", x, "о.е.", "тормозной ток в расчётном случае"), "x_лин": xl, "x_max": xm}, title="Погрешность ТТ при сквозном токе расчётного случая")
            nb = t.calc("MOD.87T.UNB_CASE", {"I_диф": d, "k_апер": a.k_aper, "k_одн": a.k_odn, "eps": ev, "df": a.delta_f, "I_торм": x},
                        title=f"Расчётный ток небаланса в наихудшем случае ({c['r'].mode_id}, РПН {c['r'].tap_key}, КЗ {c['ftype']} на шинах {c['node']}) — аналог (2.3)")
            sv = t.calc("MOD.87T.SLOPE2", {"k_отс": k_stab, "I_нб": nb, "s1": s1, "x_лин": xl, "b1": b1, "I_торм": x}, title="Наклон 2-го участка по условию устойчивости при внешнем КЗ")
            pr.criteria = [Criterion("slope2", "lower", need, "Устойчивость при внешнем КЗ с насыщением ТТ (наихудший случай)", n_stab.ref(ctx.reg.sources), "MOD.87T.SLOPE2",
                                     f"{c['r'].mode_id}/{c['r'].tap_key}/{c['node']}/{c['ftype']}")]
        else:
            t.note("Ограничения по 2-му участку нет", "Во всех расчётных внешних КЗ устойчивость обеспечивается наклоном 1; принято s2 = s1.")
            pr.criteria = [Criterion("slope2", "lower", s1, "Не менее наклона 1", "", "")]
        t.note("Соотношение наклонов", "Наклон 2 принимается не менее наклона 1 (s2 ≥ s1).")
        pr.calc = pr.lower = s2
        pr.trace = t
        pr.reason = f"Не менее {s2:.3f}"
        pr.meta = {"b13": "п. 2.1.2.1 (2.1) и п. 2.1.3 (2.4): I' = k_апер·k_одн·ε·I_к.макс при наибольшем сквозном токе"}
        # опорная точка 2 из условия излома
        tb = ctx.trace("Опорная точка 2")
        bv = tb.calc("MOD.87T.BP2", {"x_лин": xl, "s1": s1, "b1": b1, "s2": s2}, title="Опорная точка 2 из условия излома характеристики")
        pb.calc = bv.value
        pb.criteria = [Criterion("bp2", "target", bv.value, "Излом характеристики при x_лин", "разд. 2.2.4 руководства 7UT6x, рис. 2-23", "MOD.87T.BP2")]
        pb.trace = tb
        pb.status = Status.OK
        pb.reason = f"Излом характеристики при сквозном токе {xl:g} о.е."
        return pr, pb

    def _highset(self, ctx, res, bal, ext, inn) -> ParamResult:
        a = ctx.a
        pr = ParamResult("87T.HighSet", "", PFM_TITLE("87T.HighSet"), "о.е. I_nO", "float", group="Высшая ступень", rounding_dir="up")
        t = ctx.trace("Ток срабатывания высшей (неторможённой) ступени I_диф>>")
        t.note("Основание", "Руководство Siemens 7UT6x, разд. 2.2.1 «Fast Unrestrained Trip»: для объектов с большим собственным сопротивлением (трансформаторы) можно найти "
               "порог, который сквозной ток КЗ превысить не может. Отстройка выполняется от максимального сквозного тока и от тока включения.", "Руководство Siemens 7UT6x V4.6, разд. 2.2.1")
        xm, wc = 0.0, None
        for c in ext:
            for k in range(3):
                if c["res"][k] > xm:
                    xm, wc = c["res"][k], c
        khs = a.highset_k
        low1 = t.calc("MOD.87T.HIGHSET", {"k_вс": khs, "I_торм_max": xm},
                      title=f"Отстройка от максимального сквозного тока внешнего КЗ ({wc['r'].mode_id}, РПН {wc['r'].tap_key}, {wc['ftype']} на {wc['node']})")
        low2 = t.calc("MOD.87T.HIGHSET", {"k_вс": khs, "I_торм_max": a.inrush_peak_pu}, title="Отстройка от броска намагничивающего тока (основная гармоника, заданное допущение)")
        low = max(low1.value, low2.value)
        wcs = min(inn, key=lambda c: max(c["diff"]))
        up = max(wcs["diff"]) / 1.2
        pr.criteria = [Criterion("thru", "lower", low1.value, "Отстройка от сквозного тока КЗ", "Руководство 7UT6x, разд. 2.2.1", "MOD.87T.HIGHSET"),
                       Criterion("inrush", "lower", low2.value, "Отстройка от броска намагничивающего тока", "допущение проекта (inrush_peak_pu)", "MOD.87T.HIGHSET"),
                       Criterion("sens", "upper", up, "Информативно: быстрое действие при наименьшем токе КЗ на выводах (запас 1,2)", "инженерный критерий", "",
                                 f"{wcs['r'].mode_id}/{wcs['r'].tap_key}/{wcs['node']}/{wcs['ftype']}")]
        pr.lower, pr.upper, pr.calc = low, up, low
        pr.trace = t
        pr.status = Status.OK
        pr.reason = (f"Не менее {low:.2f} о.е." + ("" if low <= up else f". Наименьший ток КЗ на выводах ({up * 1.2:.2f} о.е.) ниже порога — при таком КЗ защита действует по торможённой характеристике (быстродействие высшей ступени не используется)"))
        pr.meta = {"b13": "Выпуск 13Б специальной ступени не содержит (для ДЗТ-11 — отстройка токовой отсечкой не рассматривается)"}
        return pr

    def _fixed_params(self, ctx) -> list[ParamResult]:
        a = ctx.a
        out = []
        def fx(pid, val, unit, kind, note, group, status=Status.CHECK):
            p = ParamResult(pid, "", PFM_TITLE(pid), unit, kind, calc=val, fixed=True, group=group)
            p.trace = ctx.trace(PFM_TITLE(pid))
            p.trace.note("Инженерный выбор", note)
            p.status = status
            p.reason = "Инженерный выбор; уточняется по осциллограммам бросков тока при наладке" if status == Status.CHECK else "Инженерный выбор"
            return p
        out.append(fx("87T.Delay", 0.0, "с", "time", "Дифференциальная защита действует без выдержки времени.", "Времена", Status.OK))
        out.append(fx("87T.HighSetDelay", 0.0, "с", "time", "Высшая ступень действует без выдержки времени.", "Времена", Status.OK))
        out.append(fx("87T.InrushBlocking", a.inrush_strategy == "harmonic", "вкл/выкл", "bool",
                      "Блокировка по 2-й гармонике включена (современная реализация критерия отстройки от броска тока, Вып. 13Б (2.2)); при выбранной стратегии «pickup» отстройка выполняется порогом.", "Блокировки"))
        out.append(fx("87T.Inrush2ndHarm", a.inrush_2h_pct, "%", "float",
                      "Значение принято по умолчанию терминала (15 %); типовое значение 15–20 %. Не вычисляется по данным сети.", "Блокировки"))
        out.append(fx("87T.NthHarmMode", a.nth_harm_mode, "выбор", "enum",
                      "Блокировка при перевозбуждении по 5-й гармонике (при 3-й — учитывать её отсутствие в тока обмотки Δ).", "Блокировки"))
        out.append(fx("87T.NthHarm", a.nth_harm_pct, "%", "float", "Значение по умолчанию терминала Siemens 7UT6 (30 %).", "Блокировки"))
        out.append(fx("87T.AddOnStab", 2.0, "о.е. I_nO", "float", "Порог дополнительного торможения принят по умолчанию терминала (4,00 I/InO в конвенции Σ|I| = 2,0 о.е. среднего тока).", "Стабилизация при насыщении ТТ"))
        out.append(fx("87T.AddOnStabTime", 15.0, "периодов", "float", "Длительность дополнительного торможения по умолчанию терминала (15 периодов).", "Стабилизация при насыщении ТТ"))
        return out

    # ═════════════════════════ проверки ═════════════════════════
    def _checks(self, ctx, bal, vals: dict, ext, inn, k_stab, n_stab, term, label: str) -> list[Check]:
        a = ctx.a
        tr = ctx.tr
        tol = (term.tolerances.get("87T.char", 0.0) if term else 0.0)
        P, s1, b1, s2, b2, HS = _params(vals)
        xm = x_max_ext(ext)
        checks: list[Check] = []
        src = ctx.reg.sources
        # ── устойчивость при внешних КЗ ──
        rows, wmin = [], None
        for c in ext:
            best = None
            for k in range(3):
                x, d = c["res"][k], c["diff"][k]
                if x < 0.02:
                    continue
                e_ct = a.k_aper * a.k_odn * eps_at(x, a.x_lin_pu, xm, a.eps_lin, a.eps_ct) + a.delta_f
                unb = d + e_ct * x
                ch = char_value(x, P, s1, b1, s2, b2) * (1 - tol)
                mg = ch / unb if unb > 1e-9 else INF
                if best is None or mg < best[0]:
                    best = (mg, k, x, d, unb, ch)
            if best is None:
                continue
            mg, k, x, d, unb, ch = best
            rows.append({"mode": c["r"].mode_id, "tap": c["r"].tap_key, "node": c["node"], "ftype": c["ftype"], "phase": "ABC"[k],
                         "x_res": x, "i_diff": d, "i_unb": unb, "i_char": ch, "margin": mg, "high_set": HS is not None and unb >= HS})
            if wmin is None or mg < wmin["margin"]:
                wmin = rows[-1]
        if rows:
            mg = wmin["margin"]
            st = Status.OK if mg >= k_stab * (1 - 1e-3) else (Status.CHECK if mg >= 1.0 else Status.FAIL)
            tr_ = ctx.trace(f"Устойчивость при внешних КЗ — {label} уставки")
            ctx.note_norm(tr_, n_stab, "Требуемый запас k_отс")
            ev = tr_.calc("MOD.87T.EPS_X", {"eps_лин": a.eps_lin, "eps": a.eps_ct, "x": Var("x", wmin["x_res"], "о.е."), "x_лин": a.x_lin_pu, "x_max": xm}, title="Погрешность ТТ при сквозном токе наихудшего случая")
            nb = tr_.calc("MOD.87T.UNB_CASE", {"I_диф": wmin["i_diff"], "k_апер": a.k_aper, "k_одн": a.k_odn, "eps": ev, "df": a.delta_f, "I_торм": wmin["x_res"]},
                          title="Расчётный ток небаланса в наихудшем случае")
            ch = tr_.calc("MOD.87T.CHAR", {"I_диф_min": P, "s1": s1, "b1": b1, "s2": s2, "b2": b2, "I_торм": wmin["x_res"]}, title="Порог срабатывания характеристики при данном тормозном токе")
            if tol:
                tr_.note("Допуск терминала", f"Порог уменьшен на допуск {tol * 100:.0f} % (профиль терминала).")
            tr_.calc("MOD.87T.STAB_MARGIN", {"I_хар": Var("I_хар", wmin["i_char"], "о.е."), "I_нб": nb}, title="Запас по устойчивости = порог / расчётный небаланс")
            reason = (f"Наименьший запас {mg:.2f} при требуемом ≥ {k_stab:g}: режим {wmin['mode']}, РПН {wmin['tap']}, {wmin['ftype']} на {wmin['node']}"
                      if st != Status.OK else f"Наименьший запас {mg:.2f} ≥ {k_stab:g}; наихудшее: режим {wmin['mode']}, РПН {wmin['tap']}, {wmin['ftype']} на шинах {wmin['node']}")
            checks.append(Check("87T.stab", FID, "Устойчивость при внешних КЗ (все режимы и положения РПН)", "stability", st, mg, k_stab, "", "≥", reason, tr_,
                                {"mode": wmin["mode"], "tap": wmin["tap"], "node": wmin["node"], "ftype": wmin["ftype"]}, rows,
                                [n_stab.ref(src)], "87T.Slope2"))
        # ── чувствительность при КЗ в зоне ──
        rows, wmin = [], None
        for c in inn:
            best = None
            for k in range(3):
                x, d = c["res"][k], c["diff"][k]
                ch = char_value(x, P, s1, b1, s2, b2) * (1 + tol)
                kch = d / ch if ch > 1e-9 else INF
                if best is None or kch > best[0]:
                    best = (kch, k, x, d, ch)
            kch, k, x, d, ch = best
            rows.append({"mode": c["r"].mode_id, "tap": c["r"].tap_key, "node": c["node"], "ftype": c["ftype"], "phase": "ABC"[k],
                         "x_res": x, "i_diff": d, "i_char": ch, "kch": kch, "k_req": c["k_req"], "ratio": kch / c["k_req"],
                         "i_fault_a": c["r"].i_fault_abs(), "note": c["reduced_reason"], "trips_high_set": HS is not None and d >= HS})
            if wmin is None or rows[-1]["ratio"] < wmin["ratio"]:
                wmin = rows[-1]
        if rows:
            cw = next(c for c in inn if c["r"].mode_id == wmin["mode"] and c["r"].tap_key == wmin["tap"] and c["node"] == wmin["node"] and c["ftype"] == wmin["ftype"])
            tr_ = ctx.trace(f"Чувствительность при КЗ на выводах — {label} уставки")
            ctx.note_norm(tr_, cw["norm"], "Требуемый коэффициент чувствительности")
            chv = tr_.calc("MOD.87T.CHAR", {"I_диф_min": P, "s1": s1, "b1": b1, "s2": s2, "b2": b2, "I_торм": wmin["x_res"]},
                           title=f"Порог характеристики при тормозном токе наихудшего КЗ ({wmin['ftype']} на выводе {wmin['node']}, режим {wmin['mode']}, РПН {wmin['tap']})")
            if tol:
                tr_.note("Допуск терминала", f"Порог увеличен на допуск {tol * 100:.0f} % (профиль терминала).")
            kk = tr_.calc("MOD.87T.KCH", {"I_диф": wmin["i_diff"], "I_хар": Var("I_хар", wmin["i_char"], "о.е.")}, title="Коэффициент чувствительности = I_диф / порог характеристики")
            need = wmin["k_req"]
            st = Status.OK if wmin["kch"] >= need else (Status.CHECK if wmin["kch"] >= 1.0 else Status.FAIL)
            reason = (f"k_ч = {wmin['kch']:.2f} {'≥' if st == Status.OK else '<'} {need:g}: наихудший случай — режим {wmin['mode']}, РПН {wmin['tap']}, {wmin['ftype']} на выводе {wmin['node']}"
                      + (f" ({wmin['note']})" if wmin["note"] else ""))
            checks.append(Check("87T.sens", FID, "Чувствительность при КЗ на выводах АТ (все режимы и положения РПН)", "sensitivity", st, wmin["kch"], need, "", "≥", reason, tr_,
                                {"mode": wmin["mode"], "tap": wmin["tap"], "node": wmin["node"], "ftype": wmin["ftype"]}, rows,
                                [cw["norm"].ref(src)], "87T.IdiffPickup"))
        # ── ток срабатывания по ПУЭ (менее I_тип) ──
        if tr.s_nom_mva >= 63.0 and tr.is_auto():
            lim = tr.s_typ() / tr.s_nom_mva
            st = Status.OK if P < lim else Status.FAIL
            checks.append(Check("87T.pue_typ", FID, "Ток срабатывания без торможения менее тока типовой мощности АТ", "requirement", st, P, lim, "о.е.", "<",
                                f"I_диф> = {P:.3f} {'<' if P < lim else '≥'} {lim:.3f} о.е. (I_тип/I_ном)", None, {}, [], [ctx.norm("I87T.PICKUP.AT").ref(src)], "87T.IdiffPickup"))
        # ── соотношение параметров характеристики ──
        okc = (s2 >= s1 - 1e-9) and (b2 > b1)
        checks.append(Check("87T.char", FID, "Согласованность параметров характеристики (s2 ≥ s1, b2 > b1)", "requirement", Status.OK if okc else Status.CHECK, s2 - s1, 0.0, "", "≥",
                            "Соотношение параметров выдержано" if okc else "Наклон 2 меньше наклона 1 или опорная точка 2 не превышает опорную точку 1 — характеристика вырождена", None, {}, [], [], "87T.Slope2"))
        # ── ТТ: насыщение при внешних КЗ ──
        rows = []
        for s in tr.sides():
            ct = ctx.ct(s, "87T")
            if ct is None:
                continue
            imax = max((max(abs(x) for x in c["r"].sides[s].i_abc) for c in ext), default=0.0)
            lim = ct.i_no_saturation_a()
            rows.append({"side": s, "ct": ct.id, "i_max_ext_a": imax, "i_no_sat_a": lim, "ratio": lim / imax if imax else INF, "alf_actual": ct.alf_actual()})
        if rows:
            w = min(rows, key=lambda r: r["ratio"])
            st = Status.OK if w["ratio"] >= 1.0 else Status.CHECK
            checks.append(Check("87T.ct", FID, "ТТ: погрешность при внешних КЗ (ПУЭ РК п. 1007: не более 10 %)", "ct", st, w["ratio"], 1.0, "", "≥",
                                (f"Сторона {w['side']}: наибольший ток внешнего КЗ {w['i_max_ext_a']:.0f} А {'не превышает' if st == Status.OK else 'превышает'} предельный по действительной кратности {w['i_no_sat_a']:.0f} А"
                                 + ("" if st == Status.OK else " — возможна погрешность > класса; учтено ε = 0,1 и стабилизация при насыщении, требуется проверка ТТ по кривым намагничивания")),
                                None, {"side": w["side"]}, rows, [ctx.reg.sources.get("PUE_RK").short + ", п. 1007, пп. 1)", ctx.reg.sources.get("B13").short + ", п. 1.3"], ""))
        return checks

    def recheck(self, ctx: CalcContext, accepted: dict, term: TerminalContext | None = None) -> list[Check]:
        bal = balancing(ctx, override=(term.extra if term else None))
        ext, inn = external_cases(ctx, bal), internal_cases(ctx, bal)
        n_stab = ctx.norm("K.OTS.87T.UNB")
        k_stab = ctx.a.k_stab if ctx.a.k_stab else n_stab.value
        vals = dict(accepted)
        vals.setdefault("87T.BasePoint1", ctx.a.bp1_pu)
        return self._checks(ctx, bal, vals, ext, inn, k_stab, n_stab, term, "принятые (округлённые)")


def PFM_TITLE(pid: str) -> str:
    from ...pfm import PFM
    return PFM[pid].name
