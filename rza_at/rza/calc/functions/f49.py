"""49 — защита от перегрузки трансформатора / автотрансформатора.

Два физических критерия, реализуемых современной функцией «тепловая защита + токовая ступень сигнала»:

1. Токовый сигнал перегрузки (Вып. 13Б, гл. 15, ссылка на (10.1)):
       I_с.з = k_отс·I_ном/k_в,  k_отс = 1,05,
   где I_ном — номинальный ток обмотки с учётом регулирования напряжения (для стороны с РПН — не более чем на 5 % выше
   номинального тока среднего ответвления, п. 10.2); k_в — коэффициент возврата (0,8 для РТ-40; 0,95–0,97 цифрового терминала).
   ПУЭ РК п. 1047: защита от перегрузки — токовая, действует на сигнал (на ПС без постоянного дежурства — на разгрузку/отключение).
   Выдержка времени сигнала отстраивается от самозапуска двигателей (СТО ДИВГ-056-2015 п. 3.8.4: не менее 10 с).

2. Тепловая модель (IEC 60255-8, в терминах терминалов SIPROTEC — руководство 7UT6x, разд. 2.9.2):
       dΘ/dt + Θ/τ = (I/(k·I_N))²/τ ,  Θ отнесена к превышению температуры при токе k·I_N;
       t_откл = τ·ln[(I² − I_пред²)/(I² − (k·I_N)²)]     (I, I_пред — в долях I_N)
   K-фактор — допустимый длительный ток / номинальный ток (по данным завода; при отсутствии данных руководство 7UT6x
   рекомендует 1,1). Постоянная времени τ — по данным завода, мин. Уровень предупреждения Θ_пред выбирается так, чтобы
   тепловая модель предупреждала при установившемся токе k_отс·I_ном (физический критерий сигнала гл. 15 Вып. 13Б):
       Θ_пред = 100·(k_отс/k)² %.
   Для трансформаторов с РПН тепловая модель подключается к НЕрегулируемой стороне (руководство 7UT6x, разд. 2.9.2).
   Допустимая длительность перегрузки (перегрузочная характеристика по паспорту/ГОСТ 14209-85) вводится пользователем;
   проверяется, что модель отключает/предупреждает не позже допустимого времени.
"""
from __future__ import annotations

import math

from ...errors import Status
from ...trace import Var
from ..context import CalcContext, TerminalContext
from ..results import Check, Criterion, FunctionResult, ParamResult
from . import register
from .base import FunctionCalc

FID = "49"


def assigned_side(ctx: CalcContext) -> str:
    """Сторона для тепловой модели: нерегулируемая (руководство 7UT6x, разд. 2.9.2)."""
    tr = ctx.tr
    if ctx.a.overload_side in tr.sides():
        return ctx.a.overload_side
    if tr.oltc.present:
        for s in tr.sides():
            if s != tr.oltc.side:
                return s
    return tr.sides()[0]


def replica_trip_time_min(m: float, p: float, k: float, tau_min: float) -> float:
    """Время отключения тепловой модели, мин (m = I/I_N, p = I_пред/I_N)."""
    if m <= k:
        return float("inf")
    return tau_min * math.log((m * m - p * p) / (m * m - k * k))


@register
class F49(FunctionCalc):
    id = FID
    title = "Защита от перегрузки (49)"

    def sides_used(self, ctx: CalcContext) -> list[str]:
        return [s for s in ctx.tr.sides() if ctx.ct(s, "49", strict=True) is not None]

    def _preload(self, ctx: CalcContext) -> float:
        for m in ctx.p.modes:
            if m.kind == "normal":
                return m.load_factor
        return 0.7

    def calculate(self, ctx: CalcContext) -> FunctionResult:
        a, tr = ctx.a, ctx.tr
        res = FunctionResult(FID, self.title)
        sides = self.sides_used(ctx)
        if not sides:
            res.missing.append("Нет ТТ, назначенных защите от перегрузки (49)")
            return res
        aside = assigned_side(ctx)
        res.meta["assigned_side"] = aside
        if aside not in sides:
            res.warnings.append(f"Тепловая модель по правилу нерегулируемой стороны должна быть подключена к стороне {aside}, но ТТ этой стороны не назначены защите 49; назначьте ТТ или задайте сторону вручную.")
        for s in sides:
            self._alarm(ctx, res, s)
        if aside in sides:
            self._replica(ctx, res, aside)
        res.meta["scheme"] = "trip" if a.overload_trip_enabled else "signal"
        return res

    # ── токовый сигнал (Вып. 13Б, гл. 15) ──
    def _alarm(self, ctx: CalcContext, res: FunctionResult, side: str):
        a, tr = ctx.a, ctx.tr
        ru = ctx.side_ru(side)
        k_ots = ctx.norm("K.OTS.49")
        k_v, kv_src = ctx.k_reset()
        p = ParamResult("49.IAlarm", side, f"Ток срабатывания сигнала перегрузки {ru}", "А", "float", side=side, group=f"Перегрузка {ru}", rounding_dir="up")
        t = ctx.trace(f"Ток срабатывания сигнала перегрузки {ru}")
        ctx.note_norm(t, k_ots, "Коэффициент отстройки k_отс (Вып. 13Б, гл. 15)")
        i_nom = ctx.i_nom_winding(side)
        i_var = Var("I_ном", i_nom, "А", f"номинальный ток обмотки {side} при S = {tr.s_winding(side):g} МВА")
        if tr.oltc.present and tr.oltc.side == side:
            nrp = ctx.norm("K.RPN.NOM")
            i_var = t.calc("B13.10.2i", {"I_ном0": i_nom, "k_рпн": nrp.value}, title="Номинальный ток стороны с РПН (+5 % к среднему ответвлению, п. 10.2)")
            i_var = Var("I_ном", i_var.value, "А", "с учётом регулирования напряжения")
        v = t.calc("B13.15.1", {"k_отс": k_ots.value, "I_ном": i_var, "k_в": Var("k_в", k_v, "", "коэффициент возврата", kv_src)},
                   title="Ток срабатывания сигнала перегрузки (гл. 15 → (10.1))")
        p.calc = p.lower = v.value
        p.criteria = [Criterion("i_alarm", "lower", v.value, "Возврат токового органа при номинальном токе обмотки", k_ots.ref(ctx.reg.sources), "B13.15.1")]
        p.trace = t
        p.status = Status.OK
        p.reason = f"Не менее {v.value:.0f} А ({v.value / i_nom:.3f}·I_ном)"
        p.meta = {"b13": "гл. 15 (через п. 10.2, (10.1))", "i_nom_a": i_var.value, "pue_rk": "п. 1047"}
        res.params.append(p)
        # выдержка времени сигнала
        n_t = ctx.norm("T.SIGNAL.49")
        tset = a.signal_delay_s if a.signal_delay_s else n_t.value
        pt = ParamResult("49.AlarmDelay", side, f"Выдержка времени сигнала перегрузки {ru}", "с", "time", side=side, group=f"Перегрузка {ru}", rounding_dir="up")
        tt = ctx.trace(f"Выдержка времени сигнала перегрузки {ru}")
        if a.signal_delay_s:
            tt.input("t_сигн", a.signal_delay_s, "с", "принято проектом", "проект")
        else:
            ctx.note_norm(tt, n_t, "Минимальная выдержка сигнала (отстройка от самозапуска двигателей)")
        pt.calc = pt.lower = tset
        pt.trace = tt
        pt.criteria = [Criterion("t_signal", "lower", n_t.value, "Отстройка от самозапуска двигателей (не менее 10 с)", n_t.ref(ctx.reg.sources))]
        pt.status = Status.OK
        pt.reason = f"t ≥ {n_t.value:g} с"
        res.params.append(pt)
        res.checks += self._alarm_checks(ctx, side, {f"49.IAlarm@{side}": p.calc, f"49.AlarmDelay@{side}": pt.calc}, None, "расчётные", i_var.value)

    def _alarm_checks(self, ctx, side, vals, term, label, i_nom_eff) -> list[Check]:
        out = []
        k_ots = ctx.norm("K.OTS.49")
        kvr, kvsrc = ctx.k_reset(term, FID)
        ia = vals.get(f"49.IAlarm@{side}")
        if ia is not None:
            got = ia * kvr
            need = k_ots.value * i_nom_eff
            st = Status.OK if got >= need - 1e-9 else Status.FAIL
            out.append(Check(f"49.reset@{side}", FID, f"Возврат токовой ступени сигнала перегрузки {ctx.side_ru(side)} при номинальном токе (k_в = {kvr:g})", "requirement", st, got, need, "А", "≥",
                             f"I_возв = k_в·I_с.з = {got:.0f} А {'≥' if st == Status.OK else '<'} k_отс·I_ном = {need:.0f} А (k_в: {kvsrc})", None, {}, [], [k_ots.ref(ctx.reg.sources)], f"49.IAlarm@{side}"))
        td = vals.get(f"49.AlarmDelay@{side}")
        if td is not None:
            n_t = ctx.norm("T.SIGNAL.49")
            st = Status.OK if td >= n_t.value - 1e-9 else Status.CHECK
            out.append(Check(f"49.tsig@{side}", FID, f"Выдержка времени сигнала перегрузки {ctx.side_ru(side)}", "requirement", st, td, n_t.value, "с", "≥",
                             f"t = {td:g} с {'≥' if st == Status.OK else '<'} {n_t.value:g} с (отстройка от самозапуска двигателей)", None, {}, [], [n_t.ref(ctx.reg.sources)], f"49.AlarmDelay@{side}"))
        return out

    # ── тепловая модель ──
    def _replica(self, ctx: CalcContext, res: FunctionResult, side: str):
        a, tr = ctx.a, ctx.tr
        ru = ctx.side_ru(side)
        th = tr.thermal
        k_ots = ctx.norm("K.OTS.49")
        i_nom = ctx.i_nom_winding(side)
        # ── K-фактор ──
        pk = ParamResult("49.KFactor", side, f"K-фактор тепловой модели {ru}", "о.е.", "float", side=side, group=f"Тепловая модель {ru}", rounding_dir="nearest")
        tk = ctx.trace(f"K-фактор тепловой модели {ru}")
        if th.k_factor:
            k = th.k_factor
            tk.input("k", k, "о.е.", "допустимый длительный ток / номинальный ток обмотки (паспорт трансформатора / ГОСТ 14209-85)", "паспорт АТ")
            pk.status = Status.OK
            pk.reason = "Принят по паспортным данным (допустимый длительный ток / номинальный)"
        else:
            k = 1.1
            tk.note("Данные отсутствуют", "Допустимый длительный ток не задан. Руководство 7UT6x (разд. 2.9.2, «K-Factor»): при отсутствии данных K-FACTOR = 1,1 номинального тока стороны.", "Руководство Siemens 7UT6x V4.6, разд. 2.9.2 (с. 233)")
            pk.status = Status.CHECK
            pk.reason = "Данных завода нет — принято 1,1 (рекомендация руководства терминала); уточнить по паспорту"
            res.warnings.append("Тепловая модель: K-фактор принят 1,1 из-за отсутствия данных завода")
        pk.calc = k
        pk.criteria = [Criterion("k", "target", k, "Допустимый длительный ток / номинальный ток стороны", "паспорт / ГОСТ 14209-85 / руководство 7UT6x")]
        pk.trace = tk
        res.params.append(pk)
        # ── постоянная времени ──
        pt = ParamResult("49.TimeConstant", side, f"Тепловая постоянная времени τ {ru}", "мин", "float", side=side, group=f"Тепловая модель {ru}", rounding_dir="nearest")
        tt = ctx.trace(f"Тепловая постоянная времени {ru}")
        if th.tau_min:
            tt.input("τ", th.tau_min, "мин", f"постоянная времени нагрева (данные завода; охлаждение {th.cooling})", "паспорт АТ")
            pt.calc = th.tau_min
            pt.status = Status.OK
            pt.reason = "Принята по данным завода"
        else:
            pt.calc = None
            pt.status = Status.MISSING
            pt.reason = "Не задана постоянная времени нагрева — введите данные завода (мин)"
            res.missing.append("Не задана тепловая постоянная времени τ (данные завода) для тепловой модели 49")
        pt.criteria = [Criterion("tau", "target", pt.calc, "Тепловая постоянная времени по данным завода", "паспорт")]
        pt.trace = tt
        res.params.append(pt)
        # ── Θ_пред ──
        pa = ParamResult("49.ThetaAlarm", side, f"Уровень предупреждения Θ_пред {ru}", "% от Θ_откл", "float", side=side, group=f"Тепловая модель {ru}", rounding_dir="down")
        ta = ctx.trace(f"Уровень предупреждения Θ_пред {ru}")
        ctx.note_norm(ta, k_ots, "k_отс — уровень тока, соответствующий сигналу гл. 15 Вып. 13Б")
        thv = ta.calc("MOD.49.THETA_ALARM", {"k_отс": k_ots.value, "k": Var("k", k, "о.е.")}, title="Уровень предупреждения по температуре: установившийся ток k_отс·I_ном")
        theta = min(100.0, max(50.0, thv.value))
        if abs(theta - thv.value) > 1e-9:
            ta.note("Ограничение диапазоном терминала", f"Вычисленное значение {thv.value:.1f} % приведено к допустимому диапазону 50…100 % (руководство 7UT6x, разд. 4.9).", "Руководство 7UT6x V4.6, разд. 4.9")
        pa.calc = theta
        pa.criteria = [Criterion("theta", "target", theta, "Предупреждение при установившемся токе k_отс·I_ном", k_ots.ref(ctx.reg.sources), "MOD.49.THETA_ALARM")]
        pa.trace = ta
        pa.status = Status.OK if theta < 100.0 - 1e-9 else Status.CHECK
        pa.reason = (f"Θ_пред = {theta:.1f} %: предупреждение при установившемся токе {math.sqrt(theta / 100) * k:.3f}·I_ном"
                     if pa.status == Status.OK else "K-фактор не превышает k_отс: предупреждение совпадает с отключением — уточнить K-фактор или ввести токовую ступень сигнала")
        res.params.append(pa)
        # ── проверки ──
        res.meta["thermal"] = {"k": k, "tau_min": th.tau_min, "curve": th.overload_curve, "preload": self._preload(ctx), "i_nom_a": i_nom}
        vals = {f"49.KFactor@{side}": k, f"49.TimeConstant@{side}": pt.calc, f"49.ThetaAlarm@{side}": theta}
        res.checks += self._replica_checks(ctx, side, vals, None, "расчётные")

    def _replica_checks(self, ctx, side, vals, term, label) -> list[Check]:
        out = []
        tr = ctx.tr
        th = tr.thermal
        k = vals.get(f"49.KFactor@{side}")
        tau = vals.get(f"49.TimeConstant@{side}")
        theta = vals.get(f"49.ThetaAlarm@{side}")
        ru = ctx.side_ru(side)
        if k is None:
            return out
        # предупреждение раньше отключения
        if theta is not None:
            st = Status.OK if theta < 100.0 - 1e-9 else Status.CHECK
            out.append(Check(f"49.theta@{side}", FID, f"Предупреждение раньше отключения (Θ_пред < 100 %) {ru}", "requirement", st, theta, 100.0, "%", "<",
                             f"Θ_пред = {theta:g} % ({'ниже' if st == Status.OK else 'равен'} уровню отключения); эквивалентный установившийся ток предупреждения {math.sqrt(theta / 100) * k:.3f}·I_ном",
                             None, {}, [], ["Руководство Siemens 7UT6x V4.6, разд. 2.9.2"], f"49.ThetaAlarm@{side}"))
        # перегрузочная характеристика
        curve = th.overload_curve
        if not curve:
            out.append(Check(f"49.curve@{side}", FID, f"Допустимая длительность перегрузки {ru}: сопоставление с тепловой моделью", "requirement", Status.MISSING, None, None, "", "≤",
                             "Не задана перегрузочная характеристика трансформатора (допустимая длительность перегрузки, паспорт / ГОСТ 14209-85) — проверка не выполнена", None, {}, [], [ctx.reg.sources.get("GOST_14209").short], f"49.TimeConstant@{side}"))
            return out
        if not tau:
            out.append(Check(f"49.curve@{side}", FID, f"Допустимая длительность перегрузки {ru}", "requirement", Status.MISSING, None, None, "", "≤",
                             "Не задана тепловая постоянная времени τ — расчёт времени отключения невозможен", None, {}, [], [], f"49.TimeConstant@{side}"))
            return out
        p = self._preload(ctx)
        rows, worst = [], None
        t = ctx.trace(f"Время отключения тепловой модели и допустимая длительность перегрузки — {label} уставки")
        t.note("Исходные данные", f"Предварительная нагрузка I_пред = {p:g}·I_N (нормальный режим); k = {k:g}; τ = {tau:g} мин. Перегрузочная характеристика: {th.curve_source or 'задана пользователем'}.")
        for pt in curve:
            m, tp = float(pt["multiple"]), float(pt["minutes"])
            if m <= k:
                rows.append({"multiple": m, "t_perm_min": tp, "t_model_min": None, "margin": None, "note": "ток не превышает k·I_N — модель не отключает"})
                continue
            tm = replica_trip_time_min(m, p, k, tau)
            rows.append({"multiple": m, "t_perm_min": tp, "t_model_min": tm, "margin": tp / tm if tm else None})
            if worst is None or tp / tm < worst["margin"]:
                worst = rows[-1]
        if worst is not None:
            tv = t.calc("MOD.49.TRIP_TIME", {"tau": Var("τ", tau, "мин"), "m": Var("m", worst["multiple"], "о.е.", "кратность тока I/I_N"), "p": p, "k": k},
                        title=f"Время отключения тепловой модели при {worst['multiple']:g}·I_N")
            st = Status.OK if worst["t_model_min"] <= worst["t_perm_min"] + 1e-9 else Status.FAIL
            out.append(Check(f"49.curve@{side}", FID, f"Допустимая длительность перегрузки {ru}: время отключения тепловой модели не превышает допустимого", "requirement", st,
                             worst["t_model_min"], worst["t_perm_min"], "мин", "≤",
                             f"При {worst['multiple']:g}·I_N модель отключает через {worst['t_model_min']:.1f} мин {'≤' if st == Status.OK else '>'} допустимых {worst['t_perm_min']:g} мин", t,
                             {"multiple": worst["multiple"]}, rows, [ctx.reg.sources.get("VENDOR_7UT6").short + ", разд. 2.9.2", ctx.reg.sources.get("GOST_14209").short], f"49.TimeConstant@{side}"))
        # послеаварийный режим
        m_post = max((md.load_factor for md in ctx.p.modes if "post_accident" in md.roles), default=None)
        if m_post:
            if m_post > k:
                tm = replica_trip_time_min(m_post, p, k, tau)
                out.append(Check(f"49.post@{side}", FID, f"Послеаварийная перегрузка {m_post:g}·I_N {ru}: время до отключения тепловой моделью", "requirement", Status.OK, tm, None, "мин", "",
                                 f"Тепловая модель отключит АТ через {tm:.1f} мин при нагрузке {m_post:g}·I_N (предварительная нагрузка {p:g}·I_N) — время на разгрузку оперативным персоналом/автоматикой" + ("" if ctx.a.overload_trip_enabled else " (схема без отключения: действует только сигнал)"),
                                 None, {}, [], [ctx.reg.sources.get("PUE_RK").short + ", п. 1047"], f"49.KFactor@{side}"))
            else:
                out.append(Check(f"49.post@{side}", FID, f"Послеаварийная перегрузка {m_post:g}·I_N {ru}", "requirement", Status.OK, m_post, k, "", "≤",
                                 f"Послеаварийный ток {m_post:g}·I_N не превышает K-фактор {k:g} — тепловая модель не срабатывает", None, {}, [], [], f"49.KFactor@{side}"))
        return out

    def recheck(self, ctx: CalcContext, accepted: dict, term: TerminalContext | None = None) -> list[Check]:
        out = []
        aside = assigned_side(ctx)
        for s in self.sides_used(ctx):
            i_nom = ctx.i_nom_winding(s)
            if ctx.tr.oltc.present and ctx.tr.oltc.side == s:
                i_nom *= ctx.norm("K.RPN.NOM").value
            out += self._alarm_checks(ctx, s, accepted, term, "принятые (округлённые)", i_nom)
            if s == aside:
                out += self._replica_checks(ctx, s, accepted, term, "принятые (округлённые)")
        return out
