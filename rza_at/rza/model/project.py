"""Проект расчёта: исходные данные, версионность, журнал изменений.

Требования ТЗ (разд. 21, 41):
  * номер версии, дата, автор, проверяющий, утверждающий, история изменений, предыдущая версия, причина;
  * нельзя бесследно изменять ранее выполненный расчёт: каждое изменение исходных данных, параметров ТТ/трансформатора,
    КЗ, уставок, профиля терминала фиксируется в журнале; прошлые версии хранятся неизменяемыми снимками;
  * утверждённый проект защищён от правок — для изменений создаётся новая версия.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from datetime import datetime

from .autotransformer import Transformer
from .base import Model
from .ct import CT, VT
from .modes import Mode, default_modes
from .network import Network


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class Meta(Model):
    id: str = "project"
    name: str = "Новый проект"
    substation: str = ""
    description: str = ""
    author: str = ""
    reviewer: str = ""
    approver: str = ""
    version: str = "1.0"
    date: str = ""
    status: str = "draft"            # draft | review | approved
    prev_version: str = ""
    reason: str = "Первичный расчёт"
    demo: bool = False


@dataclass
class Assumptions(Model):
    """Расчётные допущения и коэффициенты проекта (значения по умолчанию сопровождаются ссылкой на источник)."""
    # ── 87T ──
    k_aper: float = 1.0              # Вып. 13Б п. 2.1.3
    k_odn: float = 1.0
    eps_ct: float = 0.10             # ε при внешних КЗ (10 %), Вып. 13Б п. 1.3, ПУЭ РК п. 1007
    eps_lin: float = 0.05            # полная погрешность ТТ в области умеренных токов (наклон 1-го участка)
    eps_load: float = 0.03           # полная погрешность ТТ в нагрузочном режиме
    delta_f: float = 0.0             # погрешность выравнивания токов сторон (программная компенсация терминала)
    k_stab: float | None = None      # коэффициент отстройки дифзащиты (None → норма K.OTS.87T.UNB)
    inrush_strategy: str = "harmonic"  # harmonic (блокировка по 2-й гармонике) | pickup (отстройка током срабатывания, как в 13Б)
    inrush_2h_pct: float = 15.0      # уставка блокировки по 2-й гармонике (исходное значение — по умолчанию терминала)
    nth_harm_mode: str = "5"         # 5 | 3 | off — блокировка при перевозбуждении
    nth_harm_pct: float = 30.0
    inrush_peak_pu: float = 6.0      # ожидаемое действующее значение основной гармоники броска намагничивающего тока, о.е. I_ном (для высшей ступени)
    highset_k: float = 1.2           # коэффициент отстройки высшей ступени от сквозного тока (k_отс)
    ref_tap: str = "opt"             # положение РПН, по которому выравниваются токи (opt — оптимальное напряжение, nom, mid)
    bp1_pu: float = 0.0              # опорная точка 1 характеристики (универсальная, о.е. среднего тормозного тока)
    x_lin_pu: float = 2.5            # сквозной ток (о.е.), до которого ТТ работают в линейном режиме — излом характеристики (для 7UT6: излом 5,0 в конвенции Σ|I|)
    device_class: str = "microprocessor"   # microprocessor | electromechanical — выбор коэффициента возврата по умолчанию
    # ── МТЗ ──
    k_self_start: float = 1.5        # коэффициент самозапуска k_зап (Вып. 13Б п. 11.1, определяется расчётом)
    use_voltage_start: bool = True   # МТЗ с пуском по напряжению (гл. 10) или без пуска (гл. 11)
    dt_step_s: float | None = None   # ступень селективности Δt, с (None → норма DT.STEP)
    # ── обратная последовательность ──
    i2_asym_pu: float = 0.05         # I_2нс: ток обратной последовательности от несимметрии в системе, в долях I_ном
    limit_46_sens: bool = True       # ограничить чувствительность защиты ОП в зоне резервирования (k_ч ≤ 1,5, Вып. 13Б п. 9.2, (9.3))
    # ── нулевая последовательность ──
    i0_unb_extra_pu: float = 0.0     # дополнительный 3I0 в послеаварийном режиме (3I0_н.р), в долях I_ном
    i0_oapv_a: float | None = None   # 3I0 в неполнофазном режиме ОАПВ на смежных линиях, А (первичные)
    hv_class_330_plus: bool = False  # сторона 330–500 кВ (влияет на k_отс по (12.2))
    # ── дистанционная защита ──
    load_pf_deg: float = 25.0        # угол сопротивления нагрузки φ_нагр в расчётном режиме, град
    max_torque_deg: float = 75.0     # угол максимальной чувствительности реле сопротивления, град
    u_work_min_pu: float = 0.9       # минимальное рабочее напряжение в долях U_ном (для сопротивления нагрузки)
    z_offset_a: float = 0.0          # смещение характеристики 2-й ступени a (о.е.), Вып. 13Б п. 8.1.9
    # ── перегрузка ──
    overload_side: str = "auto"      # сторона тепловой модели: auto (нерегулируемая) | HV | MV | LV
    overload_curr_factor: float = 1.05
    signal_delay_s: float | None = None   # выдержка сигнала перегрузки, с (None → норма T.SIGNAL.49)
    overload_trip_enabled: bool = False   # отключение при перегрузке предусмотрено схемой (ПУЭ РК п. 1047)
    # ── общие ──
    rounding_policy: str = "safe"     # safe (ближайшее допустимое в безопасную сторону) | nearest | up | down
    norm_priority: list[str] = field(default_factory=lambda: ["KZ_LAW", "PUE_RK", "PTE_RK", "KEGOC", "OPERATOR", "PROJECT", "VENDOR", "METHOD", "B13"])
    norm_overrides: dict[str, dict] = field(default_factory=dict)   # {norm_id: {"value":…, "source":…, "clause":…}}
    display_units: dict[str, str] = field(default_factory=lambda: {"current": "А", "voltage": "кВ", "impedance": "Ом", "ratio": "о.е.", "power": "МВА"})
    formula_pins: dict[str, int] = field(default_factory=dict)
    load_i_max_pu: dict[str, float] = field(default_factory=dict)   # {"HV":1.0,…} I_раб.макс сторон в долях I_ном (если задано)


@dataclass
class TerminalAssign(Model):
    terminal_id: str = ""
    variant: str = ""
    firmware: str = ""
    functions: list[str] = field(default_factory=list)   # универсальные функции, реализуемые этим терминалом
    side_map: dict[str, str] = field(default_factory=dict)
    note: str = ""


@dataclass
class Override(Model):
    value: float | None = None
    reason: str = ""
    author: str = ""
    ts: str = ""


@dataclass
class ChangeRecord(Model):
    ts: str = ""
    user: str = ""
    kind: str = "edit"               # edit | version | status | formula | profile | export | calc | norm
    section: str = ""
    path: str = ""
    old: object = None
    new: object = None
    reason: str = ""
    version: str = ""


@dataclass
class Snapshot(Model):
    version: str = ""
    date: str = ""
    author: str = ""
    reason: str = ""
    data: dict = field(default_factory=dict)


@dataclass
class Project(Model):
    meta: Meta = field(default_factory=Meta)
    transformer: Transformer = field(default_factory=Transformer)
    cts: list[CT] = field(default_factory=list)
    vts: list[VT] = field(default_factory=list)
    network: Network = field(default_factory=Network)
    modes: list[Mode] = field(default_factory=list)
    assumptions: Assumptions = field(default_factory=Assumptions)
    terminals: list[TerminalAssign] = field(default_factory=list)
    overrides: dict[str, Override] = field(default_factory=dict)      # ключ: "terminal_id|pfm_id"
    changelog: list[ChangeRecord] = field(default_factory=list)
    history: list[Snapshot] = field(default_factory=list)

    # ── доступ ──
    def ct_for(self, side: str, purpose: str | None = None, strict: bool = False) -> CT | None:
        """ТТ стороны для защиты. strict=True — только ТТ, которому эта защита назначена (иначе допускается любой ТТ стороны)."""
        cands = [c for c in self.cts if c.side == side]
        if purpose:
            pc = [c for c in cands if purpose in c.protections]
            if pc:
                return pc[0]
            if strict:
                return None
        return cands[0] if cands else None

    def mode(self, mid: str) -> Mode:
        for m in self.modes:
            if m.id == mid:
                return m
        raise KeyError(mid)

    def modes_with_role(self, role: str) -> list[Mode]:
        return [m for m in self.modes if role in m.roles]

    def ensure_modes(self):
        if not self.modes:
            self.modes = default_modes([s.id for s in self.network.sources], self.network.parallel_at.present)

    # ── журнал ──
    def log(self, kind: str, section: str, path: str = "", old=None, new=None, reason: str = "", user: str = ""):
        self.changelog.append(ChangeRecord(now_iso(), user or self.meta.author or "—", kind, section, path,
                                           _jsonable(old), _jsonable(new), reason, self.meta.version))

    def editable(self) -> bool:
        return self.meta.status != "approved"

    def assert_editable(self):
        if not self.editable():
            raise PermissionError("Проект утверждён и защищён от изменений. Создайте новую версию (с указанием причины).")

    def patch(self, path: str, value, user: str = "", reason: str = ""):
        """Изменить значение по пути вида 'transformer.windings.HV.u_nom_kv' с записью в журнал."""
        self.assert_editable()
        d = self.to_dict()
        keys = path.split(".")
        cur = d
        for k in keys[:-1]:
            cur = cur[int(k)] if isinstance(cur, list) else cur[k]
        last = keys[-1]
        old = cur[int(last)] if isinstance(cur, list) else cur.get(last)
        if isinstance(cur, list):
            cur[int(last)] = value
        else:
            cur[last] = value
        new_p = Project.from_dict(d)
        # перенос состояния (без потери журнала)
        for f in self.__dataclass_fields__:
            setattr(self, f, getattr(new_p, f))
        self.log("edit", keys[0], path, old, value, reason, user)

    def replace_section(self, section: str, data, user: str = "", reason: str = ""):
        """Заменить раздел целиком (transformer, cts, vts, network, modes, assumptions, terminals) с журналом различий."""
        self.assert_editable()
        old = self.to_dict()[section]
        d = self.to_dict()
        d[section] = data
        new_p = Project.from_dict(d)
        diffs = diff_dicts(old, new_p.to_dict()[section], section)
        for f in self.__dataclass_fields__:
            setattr(self, f, getattr(new_p, f))
        for p, o, n in diffs[:80]:
            self.log("edit", section, p, o, n, reason, user)
        if len(diffs) > 80:
            self.log("edit", section, "…", None, f"ещё {len(diffs) - 80} изменений", reason, user)
        return len(diffs)

    # ── версии ──
    def new_version(self, author: str, reason: str):
        if not reason.strip():
            raise ValueError("Для новой версии требуется указать причину изменения")
        d = self.to_dict()
        d.pop("history", None)
        snap = Snapshot(self.meta.version, self.meta.date, self.meta.author, self.meta.reason, copy.deepcopy(d))
        self.history.append(snap)
        major, _, minor = self.meta.version.partition(".")
        newv = f"{major}.{int(minor or 0) + 1}"
        self.log("version", "meta", "version", self.meta.version, newv, reason, author)
        self.meta.prev_version = self.meta.version
        self.meta.version = newv
        self.meta.date = now_iso()[:10]
        self.meta.reason = reason
        self.meta.author = author or self.meta.author
        self.meta.status = "draft"
        return newv

    def set_status(self, status: str, by: str):
        order = ["draft", "review", "approved"]
        if status not in order:
            raise ValueError("Недопустимый статус")
        if status == "review" and not self.meta.reviewer:
            self.meta.reviewer = by
        if status == "approved":
            if self.meta.status != "review":
                raise ValueError("Утвердить можно только проект, прошедший проверку (статус «На проверке»)")
            self.meta.approver = by
        old = self.meta.status
        self.meta.status = status
        self.log("status", "meta", "status", old, status, "", by)

    def to_json(self, indent: int = 1) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_json(cls, s: str) -> "Project":
        return cls.from_dict(json.loads(s))


def _jsonable(v):
    try:
        json.dumps(v)
        return v
    except TypeError:
        return str(v)


def diff_dicts(a, b, prefix: str = "") -> list[tuple]:
    """Плоский список различий (путь, старое, новое) двух JSON-структур."""
    out: list[tuple] = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            p = f"{prefix}.{k}" if prefix else str(k)
            if k not in a:
                out.append((p, None, b[k]))
            elif k not in b:
                out.append((p, a[k], None))
            else:
                out.extend(diff_dicts(a[k], b[k], p))
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((prefix, f"[{len(a)} элем.]", f"[{len(b)} элем.]"))
            if len(a) == len(b):
                pass
        for i in range(min(len(a), len(b))):
            out.extend(diff_dicts(a[i], b[i], f"{prefix}.{i}"))
    else:
        if a != b:
            out.append((prefix, a, b))
    return out
