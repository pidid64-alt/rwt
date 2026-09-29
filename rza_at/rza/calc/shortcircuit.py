"""Расчёт токов КЗ методом симметричных составляющих (отдельный расчётный модуль).

Сеть каждой последовательности (прямой, обратной, нулевой) собирается как узловая модель (Y-матрица) в единой
ступени напряжения (приведение к ВН). Автотрансформатор/трансформатор моделируется трёхлучевой схемой замещения
с вненоминальными коэффициентами трансформации (положение РПН) и фазосдвигающими элементами (группа соединения);
нулевая последовательность строится по схемам соединения обмоток и режиму нейтрали (для АТ — с учётом
сопротивления в нейтрали общей обмотки: луч ВН 3Z_n(1−n), луч СН 3Z_n·n(n−1), ветвь на землю 3Z_n·n).

Виды КЗ: трёхфазное, двухфазное, двухфазное на землю, однофазное на землю.
Точки КЗ: шины сторон (внешние КЗ), выводы АТ внутри зоны дифзащиты (между ТТ и АТ), концы смежных линий.
Токи выводятся в действительных амперах на напряжении соответствующей стороны; положительное направление тока
ТТ — в защищаемый объект (АТ).
"""
from __future__ import annotations

import cmath
import math
from dataclasses import dataclass, field

import numpy as np

from ..errors import DataError
from ..model.autotransformer import SIDES, TapState, tap_state, tap_keys
from ..model.project import Project

A120 = cmath.exp(2j * math.pi / 3)
A240 = A120 ** 2
SQRT3 = math.sqrt(3.0)
TINY_Z = 1e-6        # Ом, «нулевое» сопротивление связи ТТ–вывод
G_REG = 1e-9         # См, регуляризация узлов без пути на землю

FAULT_TYPES = {"3ph": "Трёхфазное КЗ", "2ph": "Двухфазное КЗ", "2ph_g": "Двухфазное КЗ на землю", "1ph": "Однофазное КЗ на землю"}


def to_abc(i0: complex, i1: complex, i2: complex) -> tuple[complex, complex, complex]:
    return (i0 + i1 + i2, i0 + A240 * i1 + A120 * i2, i0 + A120 * i1 + A240 * i2)


def to_seq(a: complex, b: complex, c: complex) -> tuple[complex, complex, complex]:
    """Возвращает (I0, I1, I2)."""
    return ((a + b + c) / 3, (a + A120 * b + A240 * c) / 3, (a + A240 * b + A120 * c) / 3)


class SeqNet:
    """Узловая схема одной последовательности."""

    def __init__(self, seq: int):
        self.seq = seq
        self.nodes: list[str] = []
        self.idx: dict[str, int] = {}
        self.branches: list[dict] = []
        self.shunts: list[tuple[str, complex]] = []
        self.inj: list[tuple[str, complex]] = []
        self.Y = None
        self.Z = None

    def node(self, name: str) -> int:
        if name not in self.idx:
            self.idx[name] = len(self.nodes)
            self.nodes.append(name)
        return self.idx[name]

    def branch(self, name: str, p: str, q: str, z: complex, a: complex = 1.0 + 0j):
        """Ветвь p—q с сопротивлением z и идеальным трансформатором на стороне p: V_p = a·V_p'."""
        self.node(p), self.node(q)
        if abs(z) < 1e-12:
            z = TINY_Z
        self.branches.append({"name": name, "p": p, "q": q, "y": 1.0 / z, "a": a})

    def shunt(self, node: str, z: complex):
        self.node(node)
        self.shunts.append((node, 1.0 / z))

    def source(self, node: str, e: complex, z: complex):
        self.node(node)
        if abs(z) < 1e-9:
            z = 1e-6
        self.shunts.append((node, 1.0 / z))
        if self.seq == 1:
            self.inj.append((node, e / z))

    def build(self):
        n = len(self.nodes)
        Y = np.zeros((n, n), dtype=complex)
        for b in self.branches:
            p, q, y, a = self.idx[b["p"]], self.idx[b["q"]], b["y"], b["a"]
            Y[p, p] += y / (a * a.conjugate())
            Y[p, q] += -y / a.conjugate()
            Y[q, p] += -y / a
            Y[q, q] += y
        for node, y in self.shunts:
            Y[self.idx[node], self.idx[node]] += y
        Y += np.eye(n) * G_REG
        self.Y = Y
        self.Z = np.linalg.inv(Y)
        self.I = np.zeros(n, dtype=complex)
        for node, i in self.inj:
            self.I[self.idx[node]] += i

    def branch_currents(self, V: np.ndarray, b: dict) -> tuple[complex, complex]:
        """Токи ветви (в узел p и в узел q, положительные — в ветвь) при вектор-напряжениях V."""
        p, q, y, a = self.idx[b["p"]], self.idx[b["q"]], b["y"], b["a"]
        ip = (y / (a * a.conjugate())) * V[p] - (y / a.conjugate()) * V[q]
        iq = -(y / a) * V[p] + y * V[q]
        return ip, iq


@dataclass
class KZModel:
    mode_id: str
    tap: TapState
    nets: dict[int, SeqNet]
    K: dict[str, float]            # узел → множитель приведения к ВН сети (I_действ = I_привед·K)
    node_side: dict[str, str]
    e_phase_kv: float
    info: dict = field(default_factory=dict)


def _theta(tr, side: str) -> float:
    """Угол сдвига напряжения обмотки прямой последовательности относительно ВН, рад."""
    clock = tr.w(side).clock % 12
    return math.radians(((12 - clock) % 12) * 30.0)


def _add_transformer(N: SeqNet, tr, tap: TapState, prefix: str, K: dict[str, float]):
    sides = tr.sides()
    uH = tap.u_kv["HV"]
    n = {s: uH / tap.u_kv[s] for s in sides}
    T = lambda s: f"{prefix}T_{s}"
    O = f"{prefix}O"
    xmap = {"HV": tap.x_ohm["H"], "MV": tap.x_ohm.get("M"), "LV": tap.x_ohm.get("L")}
    if N.seq in (1, 2):
        for s in sides:
            x = xmap[s]
            if x is None:
                continue
            ph = _theta(tr, s) * (1 if N.seq == 1 else -1)
            a = (K[s] / n[s]) * cmath.exp(1j * ph)
            N.branch(f"{prefix}AT_{s}", T(s), O, complex(0.0, x), a)
        return
    # ── нулевая последовательность ──
    x0 = tr.x0_over_x1
    ratio = lambda s: K[s] / n[s]
    if tr.is_auto():
        hv = tr.w("HV")
        zn = hv.neutral_z_ohm if hv.neutral == "impedance" else 0.0
        if hv.neutral == "isolated":
            raise DataError("АТ с изолированной нейтралью общей обмотки в модели КЗ не поддерживается")
        lv = tr.windings.get("LV")
        has_d = lv is not None and lv.connection.upper().startswith("D")
        if zn != 0 and not has_d:
            raise DataError("Сопротивление в нейтрали АТ учитывается только при наличии третичной обмотки, соединённой в треугольник")
        if "MV" in sides:
            nM = n["MV"]
            zH = complex(0, xmap["HV"] * x0) + 3 * zn * (1 - nM)
            zM = complex(0, xmap["MV"] * x0) + 3 * zn * nM * (nM - 1)
            N.branch(f"{prefix}Z0_H", T("HV"), O, zH, complex(ratio("HV")))
            N.branch(f"{prefix}Z0_M", T("MV"), O, zM, complex(ratio("MV")))
            if has_d:
                N.shunt(O, complex(0, xmap["LV"] * x0) + 3 * zn * nM)
            elif lv is not None and lv.connection.upper().startswith("YN"):
                N.branch(f"{prefix}Z0_L", T("LV"), O, complex(0, xmap["LV"] * x0), complex(ratio("LV")))
        else:  # двухобмоточный АТ (ВН–НН)
            for s in sides:
                N.branch(f"{prefix}Z0_{s[0]}", T(s), O, complex(0, xmap[s] * x0), complex(ratio(s)))
        return
    for s in sides:
        w = tr.w(s)
        x = xmap[s]
        if x is None:
            continue
        zn = w.neutral_z_ohm if w.neutral == "impedance" else 0.0
        c = w.connection.upper()
        if c.startswith("YN"):
            # сопротивление нейтрали, отнесённое к ступени ВН
            zz = complex(0, x * x0) + 3 * zn * (n[s] ** 2)
            N.branch(f"{prefix}Z0_{s[0]}", T(s), O, zz, complex(ratio(s)))
        elif c.startswith("D"):
            N.shunt(O, complex(0, x * x0))
        # Y без заземления, Z — ветвь отсутствует


def build_model(project: Project, mode, tap: TapState, cascade: bool = False) -> KZModel:
    tr, net = project.transformer, project.network
    sides = tr.sides()
    base = net.base_kv
    UbH = base["HV"]
    K = {s: UbH / base[s] for s in sides}
    e_ph = mode.c_factor * UbH / SQRT3
    nets = {1: SeqNet(1), 2: SeqNet(2), 0: SeqNet(0)}
    node_K: dict[str, float] = {}
    node_side: dict[str, str] = {}
    par = net.parallel_at.present and mode.parallel_at
    for seq, N in nets.items():
        for s in sides:
            N.node(s)
            node_K[s] = K[s]
            node_side[s] = s
        _add_transformer(N, tr, tap, "", K)
        for s in sides:
            zl = complex(TINY_Z, 0) + complex(tr.series_z_ohm.get(s, 0.0)) * (K[s] ** 2)
            N.branch(f"LINK_{s}", s, f"T_{s}", zl)
            node_K[f"T_{s}"] = K[s]
            node_side[f"T_{s}"] = s
        if par:
            ptap = tap if net.parallel_at.same_taps else tap_state(tr, "nom")
            _add_transformer(N, tr, ptap, "P_", K)
            for s in sides:
                # параллельный АТ подключён непосредственно к шинам через нулевое сопротивление
                N.branch(f"PLINK_{s}", s, f"P_T_{s}", complex(TINY_Z, 0))
        for src in net.sources:
            st = mode.sources.get(src.id, "max")
            if st == "off" or src.side not in sides:
                continue
            z = src.max if st == "max" else src.min
            zref = (z.z1() if seq in (1, 2) else z.z0()) * (K[src.side] ** 2)
            if seq == 1:
                N.source(src.side, e_ph, zref)
            else:
                N.shunt(src.side, zref)
        for ln in net.lines:
            if ln.side not in sides:
                continue
            end = f"E_{ln.id}"
            z = (ln.z1() if seq in (1, 2) else ln.z0()) * (K[ln.side] ** 2)
            N.branch(f"LINE_{ln.id}", ln.side, end, z)
            node_K[end] = K[ln.side]
            node_side[end] = ln.side
            rs = ln.remote_source
            if rs is not None and not cascade:
                st = mode.sources.get(rs.id) or _remote_state(mode, net, ln.side)
                if st != "off":
                    zz = rs.max if st == "max" else rs.min
                    zr = (zz.z1() if seq in (1, 2) else zz.z0()) * (K[ln.side] ** 2)
                    if seq == 1:
                        N.source(end, e_ph, zr)
                    else:
                        N.shunt(end, zr)
        N.build()
    return KZModel(mode.id, tap, nets, node_K, node_side, e_ph,
                   {"parallel_at": bool(par), "K": K, "cascade": cascade})


def _remote_state(mode, net, side: str) -> str:
    """Состояние источника на противоположном конце линии: повторяет состояние эквивалентного источника той же стороны."""
    for src in net.sources:
        if src.side == side and src.id in mode.sources:
            return mode.sources[src.id]
    vals = set(mode.sources.values()) - {"off"}
    return "min" if vals == {"min"} else "max"


@dataclass
class SideData:
    i_abc: tuple          # токи в защищаемый объект в месте установки ТТ, А
    i0: complex
    i1: complex
    i2: complex
    u_abc: tuple          # фазные напряжения на шинах стороны, кВ (фаза–нейтраль)
    u0: complex
    u1: complex
    u2: complex


@dataclass
class FaultResult:
    mode_id: str
    tap_key: str
    node: str
    ftype: str
    fault_abc: tuple            # токи в месте КЗ, А
    fault_seq: tuple            # (I0, I1, I2), А
    sides: dict
    neutral_3i0: complex        # ток в нейтрали общей обмотки (АТ) / заземлённой нейтрали, А
    z_seq: tuple                # (Z1, Z2, Z0) относительно точки КЗ, Ом (действительные, на ступени напряжения точки КЗ)
    branches: dict              # имя ветви → (I1, I2, I0) на стороне p (привед.), A
    flags: dict
    cascade: bool = False       # каскадное отключение: подпитка с противоположных концов смежных линий отключена (Вып. 13Б п. 8.1.12)

    def i_fault_abs(self) -> float:
        return max(abs(x) for x in self.fault_abc)

    def side_i_max(self, side: str) -> float:
        return max(abs(x) for x in self.sides[side].i_abc)

    def side_i_min(self, side: str) -> float:
        return min(abs(x) for x in self.sides[side].i_abc)


def solve_fault(model: KZModel, node: str, ftype: str, tr, tap_key: str, cascade: bool = False) -> FaultResult:
    n1, n2, n0 = model.nets[1], model.nets[2], model.nets[0]
    if node not in n1.idx:
        raise DataError(f"Точка КЗ «{node}» отсутствует в расчётной схеме")
    k = n1.idx[node]
    Vpre = n1.Z @ n1.I
    vk = Vpre[k]
    z1, z2, z0 = n1.Z[k, k], n2.Z[k, k], n0.Z[k, k]
    z0_inf = abs(z0) > 1e6
    flags = {"z0_inf": z0_inf}
    if ftype == "3ph":
        i1 = vk / z1; i2 = 0j; i0 = 0j
    elif ftype == "2ph":
        i1 = vk / (z1 + z2); i2 = -i1; i0 = 0j
    elif ftype == "2ph_g":
        if z0_inf:
            i1 = vk / (z1 + z2); i2 = -i1; i0 = 0j
            flags["note"] = "Нет пути тока нулевой последовательности — расчёт как двухфазное КЗ"
        else:
            zp = z2 * z0 / (z2 + z0)
            i1 = vk / (z1 + zp)
            i2 = -i1 * z0 / (z2 + z0)
            i0 = -i1 * z2 / (z2 + z0)
    elif ftype == "1ph":
        if z0_inf:
            i1 = i2 = i0 = 0j
            flags["note"] = "Нет пути тока нулевой последовательности (изолированная/компенсированная сеть): ток однофазного замыкания не определяется по схеме замещения"
        else:
            i1 = i2 = i0 = vk / (z1 + z2 + z0)
    else:
        raise DataError(f"Неизвестный вид КЗ: {ftype}")
    V1 = Vpre - n1.Z[:, k] * i1
    V2 = -n2.Z[:, k] * i2
    V0 = -n0.Z[:, k] * i0
    Vs = {1: V1, 2: V2, 0: V0}
    K = model.K
    Kn = K.get(node, 1.0)
    fabc = tuple(x * Kn * 1000.0 for x in to_abc(i0, i1, i2))
    # токи ветвей
    br: dict[str, tuple] = {}
    for b1 in n1.branches:
        name = b1["name"]
        cur = {}
        for seq, N in ((1, n1), (2, n2), (0, n0)):
            bb = next((x for x in N.branches if x["name"] == name), None)
            if bb is None:
                cur[seq] = (0j, 0j)
            else:
                cur[seq] = N.branch_currents(Vs[seq], bb)
        br[name] = (cur[1][0], cur[2][0], cur[0][0], cur[1][1], cur[2][1], cur[0][1])
    # zero-seq-only branches
    for b0 in n0.branches:
        if b0["name"] not in br:
            ip, iq = n0.branch_currents(V0, b0)
            br[b0["name"]] = (0j, 0j, ip, 0j, 0j, iq)
    sides: dict[str, SideData] = {}
    for s in tr.sides():
        lk = br[f"LINK_{s}"]
        ks = K[s]
        i1s, i2s, i0s = lk[0] * ks * 1000.0, lk[1] * ks * 1000.0, lk[2] * ks * 1000.0
        i_abc = to_abc(i0s, i1s, i2s)
        ib = n1.idx[s]
        v1, v2, v0 = V1[ib] / ks, V2[ib] / ks, V0[ib] / ks
        sides[s] = SideData(i_abc, i0s, i1s, i2s, to_abc(v0, v1, v2), v0, v1, v2)
    # ток в нейтрали (3I0 общей обмотки АТ; для трансформатора — заземлённой обмотки ВН)
    if tr.is_auto() and "MV" in tr.sides():
        neutral = sides["HV"].i0 * 3 + sides["MV"].i0 * 3
    else:
        neutral = sides["HV"].i0 * 3
    return FaultResult(model.mode_id, tap_key, node, ftype, fabc, (i0 * Kn * 1000.0, i1 * Kn * 1000.0, i2 * Kn * 1000.0),
                       sides, neutral, (z1 / Kn ** 2, z2 / Kn ** 2, z0 / Kn ** 2), br, flags, cascade)


def branch_phase_currents(model: KZModel, res: FaultResult, name: str, node_for_k: str, end: str = "p") -> tuple:
    """Фазные токи ветви (А действительные) на стороне p или q; node_for_k — узел, по которому берётся множитель приведения."""
    b = res.branches[name]
    if end == "p":
        i1, i2, i0 = b[0], b[1], b[2]
    else:
        i1, i2, i0 = b[3], b[4], b[5]
    k = model.K.get(node_for_k, 1.0)
    return tuple(x * k * 1000.0 for x in to_abc(i0, i1, i2))


class KZ:
    """Библиотека расчётов КЗ проекта с кэшированием по (режим, положение РПН, точка, вид КЗ)."""

    def __init__(self, project: Project):
        self.p = project
        self.project.ensure_modes()
        self._models: dict[tuple, KZModel] = {}
        self._res: dict[tuple, FaultResult] = {}

    @property
    def project(self) -> Project:
        return self.p

    def tap_keys_for(self, mode) -> list:
        return [mode.tap] if mode.tap else tap_keys(self.p.transformer)

    def model(self, mode_id: str, tap_key, cascade: bool = False) -> KZModel:
        key = (mode_id, str(tap_key), cascade)
        if key not in self._models:
            mode = self.p.mode(mode_id)
            self._models[key] = build_model(self.p, mode, tap_state(self.p.transformer, tap_key), cascade)
        return self._models[key]

    def fault(self, mode_id: str, tap_key, node: str, ftype: str, cascade: bool = False) -> FaultResult:
        key = (mode_id, str(tap_key), node, ftype, cascade)
        if key not in self._res:
            m = self.model(mode_id, tap_key, cascade)
            self._res[key] = solve_fault(m, node, ftype, self.p.transformer, str(tap_key), cascade)
        return self._res[key]

    def scan(self, role: str, node: str, ftype: str, cascade: bool = False) -> list[FaultResult]:
        """Все расчёты для режимов с указанной ролью × положения РПН (min → nom → max)."""
        out = []
        for m in self.p.modes_with_role(role):
            for tk in self.tap_keys_for(m):
                out.append(self.fault(m.id, tk, node, ftype, cascade))
        return out

    def fault_nodes(self) -> list[dict]:
        tr, net = self.p.transformer, self.p.network
        nodes = []
        for s in tr.sides():
            nodes.append({"node": s, "kind": "bus", "side": s, "label": f"Шины {tr.u_nom(s):g} кВ ({s})"})
        for s in tr.sides():
            nodes.append({"node": f"T_{s}", "kind": "terminal", "side": s, "label": f"Вывод {s} АТ (в зоне дифзащиты)"})
        for ln in net.lines:
            nodes.append({"node": f"E_{ln.id}", "kind": "line_end", "side": ln.side, "label": f"Конец линии «{ln.name}» ({ln.side})"})
        return nodes

    def table(self, mode_ids=None, nodes=None, ftypes=None) -> list[dict]:
        """Плоская таблица результатов КЗ для отображения/экспорта."""
        rows = []
        modes = [self.p.mode(m) for m in mode_ids] if mode_ids else self.p.modes
        nodes = nodes or [n["node"] for n in self.fault_nodes() if n["kind"] in ("bus", "terminal")]
        ftypes = ftypes or list(FAULT_TYPES)
        for m in modes:
            for tk in self.tap_keys_for(m):
                for nd in nodes:
                    for ft in ftypes:
                        try:
                            r = self.fault(m.id, tk, nd, ft)
                        except DataError:
                            continue
                        row = {"mode": m.id, "tap": str(tk), "position": self.model(m.id, tk).tap.position, "node": nd, "ftype": ft,
                               "i_fault_a": r.i_fault_abs(), "z1": abs(r.z_seq[0]), "z0": abs(r.z_seq[2]) if not r.flags["z0_inf"] else None}
                        for s in self.p.transformer.sides():
                            row[f"i_{s}_max_a"] = r.side_i_max(s)
                        row["i_neutral_a"] = abs(r.neutral_3i0)
                        rows.append(row)
        return rows
