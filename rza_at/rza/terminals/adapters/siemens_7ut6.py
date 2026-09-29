"""Siemens 7UT6 Adapter: Protection Function Model → параметры 7UT6x.

Особенности устройства (по руководству SIPROTEC 7UT6x V4.6, C53000-G1176-C230-2):
  • тормозной ток I_stab = |I1| + |I2| + … (разд. 2.2.1) → пересчёт наклонов и опорных точек (k_conv = 2);
  • для регулируемой обмотки в UN-PRI SIDE вводится напряжение, соответствующее среднему току диапазона (разд. 2.1.4);
  • номинальная мощность объекта — мощность наиболее мощной обмотки (разд. 2.1.4, с. 67): I/InO относится к ней;
  • уставки I/InS относятся к номинальному току обмотки стороны (SN SIDE, UN-PRI SIDE);
  • защита обратной последовательности и тепловая модель назначаются ОДНОЙ стороне (адреса 440, 442);
  • три функции МТЗ фаз и три функции 3I0 — только 7UT613/63x (разд. 1.3); функции 21/67/67N в 7UT6x нет;
  • 3-я ступень ТЗНП реализуется зависимой характеристикой 3I0p (независимой выдержки у этой ступени нет).
"""
from __future__ import annotations

from ...errors import Status
from ..adapter import GenericAdapter, Row, register_adapter, snap
from ...pfm import split_key

GROUP_LIMITS = {"7UT612": {"oc_groups": 1, "znp_groups": 1, "sides": 2}, "7UT613": {"oc_groups": 3, "znp_groups": 3, "sides": 3},
                "7UT633": {"oc_groups": 3, "znp_groups": 3, "sides": 3}, "7UT635": {"oc_groups": 3, "znp_groups": 3, "sides": 5}}
SIDE_NAME = {"HV": "Side 1", "MV": "Side 2", "LV": "Side 3"}


@register_adapter("siemens_7ut6")
class Siemens7UT6Adapter(GenericAdapter):

    def _variant_key(self) -> str:
        v = (self.x.variant or "7UT613").upper()
        for k in GROUP_LIMITS:
            if k in v:
                return k
        return "7UT613"

    def instance_available(self, pid: str, instance: str, m: dict | None):
        lim = GROUP_LIMITS[self._variant_key()]
        side = self.x.side_of(instance)
        order = [s for s in ("HV", "MV", "LV") if s in self.x.tr.sides()]
        if pid in ("51.IPickup", "51.Delay", "51.UMinPickup", "51.U2Pickup"):
            if pid.startswith("51.U"):
                return False, "Управление МТЗ по напряжению (пуск по U< / U2>) в 7UT6x штатно не предусмотрено (используются гибкие функции — не сопоставлены в MVP)"
            if order.index(side) >= lim["oc_groups"]:
                return False, f"У исполнения {self._variant_key()} только {lim['oc_groups']} функция(и) МТЗ фаз (разд. 1.3) — для стороны {side} параметров нет"
        if pid in ("51N.I0Pickup", "51N.Delay"):
            if order.index(side) >= lim["znp_groups"]:
                return False, f"У исполнения {self._variant_key()} только {lim['znp_groups']} функция(и) 3I0 (разд. 1.3)"
        if pid == "59N.U0Pickup":
            return False, "Защита по 3U0 на стороне НН в 7UT6x не сопоставлена (используйте функции напряжения 5xxx / гибкие функции)"
        if m and m.get("single_instance"):
            # единственный экземпляр: первая сторона из имеющихся расчётов
            first = self._first_instance(pid)
            if instance != first:
                fname = {"46": "защита обратной последовательности (адрес 440)", "49": "тепловая модель (адрес 442)"}.get(pid.split(".")[0], "функция")
                return False, f"В 7UT6x {fname} назначается одной стороне — реализована для стороны {first}; для {instance} нужен другой терминал/функция"
        if pid == "49.AlarmDelay":
            return False, "У токовой ступени сигнала перегрузки 7UT6x нет отдельной выдержки времени (адрес 4205 — только порог)"
        return True, ""

    def _first_instance(self, pid: str) -> str:
        fid = pid.split(".")[0]
        cands = []
        for fr in self.x.results.values():
            for p in fr.params:
                if p.pfm_id == pid:
                    cands.append(p.instance)
        order = {"HV": 0, "MV": 1, "LV": 2}
        return sorted(cands, key=lambda i: order.get(i.split(":")[0], 9))[0] if cands else ""

    # ── данные объекта, ТТ и назначения функций ──
    def object_rows(self) -> list[Row]:
        tr, prof = self.x.tr, self.profile
        out: list[Row] = []
        op = prof.data.get("object_params", {})

        def mk(addr: str, title: str, value, note: str = "", group="Данные объекта и ТТ (Power System Data 1)") -> Row:
            p = prof.param(addr)
            row = Row(function="Объект", pfm_key=f"obj:{addr}", pfm_id="obj", instance=addr, title=title, group=group, param_key=addr,
                      param_name=f"{addr} {p.get('name', '')}" if p else addr)
            row.calc = value
            row.calc_unit = p.get("unit", "") if p else ""
            if not p:
                row.status, row.reason, row.supported = Status.NA, "Параметр отсутствует в профиле", False
                return row
            row.unit, row.min, row.max, row.step = p.get("unit", ""), p.get("min"), p.get("max"), p.get("step")
            row.options, row.source, row.step_verified, row.comment = p.get("options", []), p.get("source", {}), p.get("step_verified"), p.get("comment", "")
            if p.get("kind") == "enum":
                row.accepted, row.accepted_univ = value, value
                row.dev_calc = value
                if row.options and value not in row.options:
                    row.status, row.reason = Status.OUT_OF_RANGE, f"«{value}» не входит в {row.options}"
                else:
                    row.reason = note or "Данные объекта"
            else:
                acc, st = snap(float(value), row.min, row.max, row.step, "nearest")
                row.dev_calc, row.accepted, row.accepted_univ = float(value), acc, acc
                row.range_state = st
                row.deviation_abs = acc - float(value)
                row.deviation_rel = (acc - float(value)) / float(value) if value else None
                row.status = Status.OK if st == "in" else Status.OUT_OF_RANGE
                row.reason = note or ("Округление до шага терминала" if abs(acc - float(value)) > 1e-9 else "Данные объекта")
            row.fixed = True
            return row

        sd = op.get("side", {})
        for s in tr.sides():
            a = sd.get(s)
            if not a:
                continue
            w = tr.w(s)
            u_set = self.x.bal_calc["u_set"][s]
            reg = tr.oltc.present and tr.oltc.side == s
            r = mk(a["un"], f"Номинальное напряжение стороны {s} (UN-PRI)", u_set,
                   "Для регулируемой обмотки — напряжение выравнивания U = 2·Umax·Umin/(Umax+Umin) (разд. 2.1.4)" if reg else "Номинальное напряжение обмотки")
            out.append(r)
            if r.accepted is not None and isinstance(r.accepted, (int, float)):
                self.x.u_set_dev[s] = float(r.accepted)
            out.append(mk(a["sn"], f"Номинальная мощность обмотки стороны {s} (SN)", tr.s_winding(s), "Мощность обмотки; I/InO относится к наиболее мощной обмотке"))
            out.append(mk(a["starpoint"], f"Нейтраль стороны {s}", "Earthed" if (w.neutral != "isolated" and w.connection.upper().startswith("Y")) else "Isolated"))
            conn = "Y" if (tr.is_auto() and s in ("HV", "MV")) else ("Y" if w.connection.upper().startswith("Y") else ("D" if w.connection.upper().startswith("D") else "Z"))
            out.append(mk(a["connection"], f"Схема соединения обмотки стороны {s}", conn, "Для АТ и однофазных трансформаторов разрешено только Y (разд. 2.1.4)" if tr.is_auto() and s in ("HV", "MV") else ""))
            if "vector_group" in a:
                out.append(mk(a["vector_group"], f"Группа соединения стороны {s} относительно ВН", str(w.clock % 12), "Кратное 30°"))
        for i, s in enumerate(tr.sides()):
            ct = self.x.ctx.ct(s, "87T")
            ck = op.get("ct", {}).get(f"M{i + 1}")
            if ct is None or not ck:
                continue
            out.append(mk(ck["starpoint"], f"ТТ {ct.id}: начало в сторону объекта", "YES" if ct.polarity == "to_object" else "NO", "Место установки: " + ct.name, "Данные ТТ (Power System Data 1)"))
            out.append(mk(ck["primary"], f"ТТ {ct.id}: первичный ток", ct.i1_a, "", "Данные ТТ (Power System Data 1)"))
            out.append(mk(ck["secondary"], f"ТТ {ct.id}: вторичный ток", f"{ct.i2_a:g}A", "", "Данные ТТ (Power System Data 1)"))
        # назначения функций сторонам
        assign = prof.data.get("assignments", {})
        used = {}
        for fr in self.x.results.values():
            for p in fr.params:
                if p.side:
                    used.setdefault(p.pfm_id.split(".")[0], set()).add(p.side)
        gmap = {"51": "Phase O/C", "51N": "3I0 O/C", "46": "Unbalance Load", "49": "Therm. Overload"}
        for pfx, grp in gmap.items():
            for s in sorted(used.get(pfx, []), key=lambda x: ["HV", "MV", "LV"].index(x)):
                a = (assign.get(grp) or {}).get(s)
                if not a:
                    continue
                if pfx in ("46", "49") and s != self._first_instance(f"{pfx}.{'I2Pickup' if pfx == '46' else 'KFactor'}"):
                    continue
                if pfx == "49" and s != self._first_instance("49.KFactor"):
                    continue
                out.append(mk(a["address"], f"Назначение функции «{grp}» стороне {s}", a["value"], "Структурный параметр (назначение функции стороне/точке измерения)", "Назначение функций сторонам"))
        return out

    # ── переопределение: округлённые U для I_ns / I_no учитываются только после object_rows ──
    def apply(self, results, policy, overrides):
        obj = self.object_rows()
        rows, accepted = super().apply(results, policy, overrides)
        self.obj_rows = obj
        # ступени ТЗНП — параметр характеристики зависимой ступени
        extra = []
        for r in rows:
            m = self.profile.mapping(r.pfm_id) or {}
            idm = (m.get("idmt_stage") or {}).get(r.instance)
            if idm and idm.get("curve_param") and r.supported and r.status != Status.NA:
                extra.append(self._curve_row(r, idm))
        return obj + rows + extra, accepted

    def _curve_row(self, owner: Row, idm: dict) -> Row:
        p = self.profile.param(idm["curve_param"])
        row = Row(function="50N/51N", pfm_key=f"curve:{owner.pfm_key}", pfm_id="curve", instance=owner.instance, title=f"Характеристика зависимой ступени (для {owner.title})",
                  group=owner.group, param_key=idm["curve_param"], param_name=f"{idm['curve_param']} {p.get('name', '') if p else ''}".strip())
        row.calc, row.accepted, row.dev_calc, row.accepted_univ = idm.get("curve_option"), idm.get("curve_option"), idm.get("curve_option"), idm.get("curve_option")
        row.options = p.get("options", []) if p else []
        row.status = Status.CHECK
        row.reason = "Сопутствующая уставка: тип характеристики, для которой рассчитан временной множитель"
        row.fixed = True
        row.source = p.get("source", {}) if p else {}
        return row
