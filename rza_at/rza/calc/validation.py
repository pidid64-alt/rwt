"""Автоматическая проверка исходных данных до расчёта (ТЗ, разд. 25).

Контролируются: заполненность, единицы и диапазоны, коэффициенты ТТ, напряжения, мощности, группа соединения, положения РПН,
токи КЗ (упорядоченность режимов), схема заземления. При ошибке расчёт не запускается (либо результат помечается как неполный).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from ..model.autotransformer import PAIRS, SIDE_RU
from ..model.project import Project

SQRT3 = math.sqrt(3.0)


@dataclass
class Issue:
    level: str          # error | warning | info
    code: str
    path: str
    message: str
    hint: str = ""

    def to_dict(self):
        return {"level": self.level, "code": self.code, "path": self.path, "message": self.message, "hint": self.hint}


def validate(p: Project, deep: bool = True) -> list[Issue]:
    out: list[Issue] = []
    E = lambda code, path, msg, hint="": out.append(Issue("error", code, path, msg, hint))
    W = lambda code, path, msg, hint="": out.append(Issue("warning", code, path, msg, hint))
    I = lambda code, path, msg, hint="": out.append(Issue("info", code, path, msg, hint))
    tr, net = p.transformer, p.network
    sides = tr.sides()
    # ── паспорт ──
    if tr.s_nom_mva <= 0:
        E("s_nom", "transformer.s_nom_mva", "Номинальная мощность должна быть положительной")
    if tr.frequency_hz not in (50.0, 60.0, 16.7):
        W("freq", "transformer.frequency_hz", f"Частота {tr.frequency_hz} Гц необычна (50/60/16,7)")
    if "HV" not in sides:
        E("hv", "transformer.windings", "Не задана обмотка ВН")
    if len(sides) < 2:
        E("windings", "transformer.windings", "Необходимо не менее двух обмоток")
    volts = [(s, tr.u_nom(s)) for s in sides]
    for s, u in volts:
        if not (0.4 <= u <= 800):
            E("u_nom", f"transformer.windings.{s}.u_nom_kv", f"Напряжение стороны {s} = {u} кВ вне диапазона 0,4…800 кВ", "Проверьте единицы (кВ, междуфазное)")
    if all(u > 0 for _, u in volts) and any(volts[i][1] <= volts[i + 1][1] for i in range(len(volts) - 1)):
        E("u_order", "transformer.windings", "Напряжения обмоток должны убывать в порядке ВН > СН > НН")
    if tr.is_auto() and "MV" not in sides:
        W("auto_mv", "transformer.kind", "Автотрансформатор задан без обмотки СН — обмотка ВН/СН считается двухобмоточным АТ")
    if tr.is_auto() and "HV" in sides and "MV" in sides:
        n = tr.u_nom("HV") / tr.u_nom("MV")
        if n > 3.5:
            W("auto_ratio", "transformer.windings", f"Отношение напряжений ВН/СН = {n:.2f} велико для АТ (коэффициент выгодности мал)")
    for s in sides:
        w = tr.w(s)
        if not (0 <= w.clock <= 11):
            E("clock", f"transformer.windings.{s}.clock", f"Группа соединения (часы) стороны {s} должна быть 0…11")
        if w.connection not in ("YN", "Y", "D", "Z"):
            E("conn", f"transformer.windings.{s}.connection", f"Неизвестная схема соединения «{w.connection}»")
        if w.neutral == "impedance" and w.neutral_z_ohm <= 0:
            E("zn", f"transformer.windings.{s}.neutral_z_ohm", "Для нейтрали через сопротивление задайте Z_n > 0")
    # допустимость группы: Y/D — нечётные, Y/Y и D/D — чётные (для двухобмоточных/третичной)
    if "LV" in sides and "HV" in sides:
        hv, lv = tr.w("HV").connection.upper()[0], tr.w("LV").connection.upper()[0]
        c = tr.w("LV").clock % 12
        if (hv != lv) and (c % 2 == 0):
            W("clock_parity", "transformer.windings.LV.clock", f"Для соединения {hv}/{lv} группа {c} невозможна (допустимы нечётные)")
        if (hv == lv) and (c % 2 == 1):
            W("clock_parity", "transformer.windings.LV.clock", f"Для соединения {hv}/{lv} группа {c} невозможна (допустимы чётные)")
    if tr.is_auto() and "HV" in sides:
        if tr.w("HV").neutral == "isolated":
            E("at_neutral", "transformer.windings.HV.neutral", "АТ с изолированной нейтралью общей обмотки в модели КЗ не поддерживается")
        if tr.w("HV").neutral == "impedance" and not ("LV" in sides and tr.w("LV").connection.upper().startswith("D")):
            E("at_zn", "transformer.windings.HV.neutral", "Сопротивление в нейтрали АТ учитывается только при наличии третичной обмотки в треугольник")
        if "MV" in sides and tr.w("MV").connection.upper() not in ("YN", "Y"):
            W("at_mv_conn", "transformer.windings.MV.connection", "Для автотрансформатора обмотка СН — Y (авто-соединённая)")
    # u_к
    need_pairs = [f"HV_{s}" for s in sides if s != "HV"] + (["MV_LV"] if len(sides) == 3 else [])
    for pair in need_pairs:
        if pair not in tr.uk:
            E("uk_missing", f"transformer.uk.{pair}", f"Не задано u_к пары обмоток {pair}", "Введите из паспорта/протокола испытаний")
        else:
            u = tr.uk[pair]
            for label, v in (("nom", u.nom), ("min", u.min), ("max", u.max)):
                if v is not None and not (1.0 <= v <= 60.0):
                    E("uk_range", f"transformer.uk.{pair}.{label}", f"u_к({pair}, {label}) = {v} % вне диапазона 1…60 %", "Проверьте, что значение в процентах, а не в о.е.")
    if len(sides) == 3 and all(k in tr.uk for k in PAIRS):
        try:
            for key in ("min", "nom", "max"):
                x = tr.star_x_ohm(tr.oltc.key_position(key))
                if x["H"] < 0 or x["L"] < 0:
                    W("star_neg", "transformer.uk", f"В схеме замещения луч ВН или НН имеет отрицательное сопротивление ({key}) — проверьте u_к пар и базовую мощность (S_ref)",
                      "Для АТ u_к пар с обмоткой НН часто приведены к типовой мощности — укажите S_ref")
                    break
        except Exception as e:  # noqa
            E("star", "transformer.uk", f"Не удаётся построить схему замещения: {e}")
    # РПН
    o = tr.oltc
    if o.present:
        if o.side not in sides:
            E("oltc_side", "transformer.oltc.side", f"Сторона регулирования {o.side} отсутствует")
        if o.step_pct <= 0:
            E("oltc_step", "transformer.oltc.step_pct", "Ступень регулирования должна быть > 0")
        if not (1 <= o.nominal_position <= o.n_positions):
            E("oltc_nom", "transformer.oltc.nominal_position", f"Номинальное положение {o.nominal_position} вне диапазона 1…{o.n_positions}")
        for label, v in (("min", o.used_min_position), ("max", o.used_max_position)):
            if v is not None and not (1 <= v <= o.n_positions):
                E("oltc_used", f"transformer.oltc.used_{label}_position", f"Используемое положение {label} = {v} вне диапазона 1…{o.n_positions}")
        if o.pos_min() > o.nominal_position or o.pos_max() < o.nominal_position:
            W("oltc_range", "transformer.oltc", "Номинальное положение вне используемого диапазона РПН")
        if o.n_steps_plus + o.n_steps_minus > 0 and (o.step_pct * max(o.n_steps_plus, o.n_steps_minus)) > 25:
            W("oltc_wide", "transformer.oltc", "Диапазон регулирования превышает ±25 % — проверьте ввод")
    # ТТ
    used_fn = {"HV": {"87T"}, "MV": {"87T"}, "LV": {"87T"}}
    for s in sides:
        cts = [c for c in p.cts if c.side == s]
        if not cts:
            E("ct_missing", f"cts.{s}", f"Нет ТТ на стороне {s} ({SIDE_RU[s]})", "Добавьте ТТ в разделе «ТТ/ТН»")
            continue
        i_nom = tr.i_nom(s, tr.s_winding(s))
        for c in cts:
            if c.i2_a not in (1.0, 5.0):
                E("ct_i2", f"cts.{c.id}.i2_a", f"ТТ {c.id}: вторичный ток {c.i2_a:g} А — допустимы 1 или 5 А")
            if c.i1_a <= 0:
                E("ct_i1", f"cts.{c.id}.i1_a", f"ТТ {c.id}: первичный ток должен быть > 0")
                continue
            if c.side in sides:
                if i_nom > 1.2 * c.i1_a:
                    W("ct_low", f"cts.{c.id}.i1_a", f"ТТ {c.id}: номинальный ток стороны {i_nom:.0f} А превышает 1,2·I_1н ({c.i1_a:g} А) — длительная перегрузка ТТ")
                if i_nom < 0.2 * c.i1_a:
                    W("ct_high", f"cts.{c.id}.i1_a", f"ТТ {c.id}: I_1н = {c.i1_a:g} А намного больше номинального тока стороны {i_nom:.0f} А — низкая точность приведения токов")
            if c.s_fact_va > c.s_nom_va:
                W("ct_burden", f"cts.{c.id}.s_fact_va", f"ТТ {c.id}: фактическая нагрузка {c.s_fact_va:g} ВА превышает номинальную {c.s_nom_va:g} ВА — погрешность выше класса")
            if c.alf <= 0:
                E("ct_alf", f"cts.{c.id}.alf", f"ТТ {c.id}: предельная кратность должна быть > 0")
    # сеть
    for s in sides:
        if net.base_kv.get(s, 0) <= 0:
            E("base_kv", f"network.base_kv.{s}", f"Не задано среднее номинальное напряжение сети стороны {s}")
    if not net.sources:
        E("sources", "network.sources", "Не задан ни один эквивалентный источник", "Задайте эквивалент сети (режимы макс/мин)")
    for src in net.sources:
        if src.side not in sides:
            E("src_side", f"network.sources.{src.id}", f"Источник {src.id} подключён к отсутствующей стороне {src.side}")
        for label, z in (("max", src.max), ("min", src.min)):
            if z.x1 <= 0 or z.x0 <= 0:
                E("src_z", f"network.sources.{src.id}.{label}", f"Источник {src.id} ({label}): реактивные сопротивления X1, X0 должны быть > 0")
        if src.min.z1().imag + 1e-9 < src.max.z1().imag:
            W("src_order", f"network.sources.{src.id}", f"Источник {src.id}: сопротивление в режиме «мин» меньше, чем в режиме «макс» — режимы перепутаны?",
              "В режиме минимальной мощности КЗ сопротивление системы больше")
    for ln in net.lines:
        if ln.length_km <= 0 or ln.x1 <= 0 or ln.x0 <= 0:
            E("line", f"network.lines.{ln.id}", f"Линия «{ln.name}»: длина и сопротивления должны быть > 0")
        if ln.side not in sides:
            E("line_side", f"network.lines.{ln.id}", f"Линия «{ln.name}» подключена к отсутствующей стороне {ln.side}")
        if not (ln.prot.dist or ln.prot.i0 or ln.prot.mtz):
            W("line_prot", f"network.lines.{ln.id}.prot", f"Линия «{ln.name}»: не заданы уставки защит для согласования", "Согласование по чувствительности/времени будет неполным")
    # режимы
    ids = [m.id for m in p.modes]
    if len(ids) != len(set(ids)):
        E("modes_dup", "modes", "Идентификаторы режимов должны быть уникальны")
    for role in ("max_kz", "min_kz"):
        if not p.modes_with_role(role):
            E("modes_role", "modes", f"Нет расчётных режимов с ролью «{role}»")
    src_ids = {s.id for s in net.sources}
    for m in p.modes:
        for sid in m.sources:
            if sid not in src_ids:
                W("mode_src", f"modes.{m.id}", f"Режим {m.id}: источник {sid} не найден")
    # заземление
    if "LV" in sides and tr.w("LV").connection.upper().startswith("Y") and tr.w("LV").neutral == "isolated":
        W("lv_neutral", "transformer.windings.LV", "Обмотка НН — звезда с изолированной нейтралью: нулевая последовательность не циркулирует")
    # терминалы
    if not p.terminals:
        W("terminals", "terminals", "Не выбран ни один терминал: будет выполнен только универсальный расчёт (уровень 1)")
    # токи КЗ
    if deep and not any(i.level == "error" for i in out):
        try:
            from .shortcircuit import KZ
            kz = KZ(p)
            for s in sides:
                mx = [m for m in p.modes_with_role("max_kz")]
                mn = [m for m in p.modes_with_role("min_kz") if "energization" not in m.roles]
                imax = max(kz.fault(m.id, kz.tap_keys_for(m)[0], s, "3ph").i_fault_abs() for m in mx)
                imin = min(kz.fault(m.id, kz.tap_keys_for(m)[0], s, "3ph").i_fault_abs() for m in mn)
                if imax < imin * 1.0001:
                    W("kz_order", f"network", f"На шинах {s} ток КЗ в режимах «макс» не превышает ток в режимах «мин»", "Проверьте задание режимов и источников")
                if imax > 100_000:
                    W("kz_high", f"network", f"Ток трёхфазного КЗ на шинах {s} = {imax / 1000:.0f} кА — проверьте эквиваленты сети")
        except Exception as e:  # noqa
            E("kz", "network", f"Не удалось выполнить контрольный расчёт КЗ: {e}")
    return out


def has_errors(issues: list[Issue]) -> bool:
    return any(i.level == "error" for i in issues)
