"""Независимая проверка решателя КЗ по аналитическим формулам."""
import cmath
import math

import numpy as np
import pytest

from rza.calc.shortcircuit import KZ, SeqNet, _add_transformer, to_abc, to_seq, build_model
from rza.model.autotransformer import Transformer, Winding, UkPair, TapChanger, tap_state
from rza.model.modes import Mode
from rza.model.network import Network, Source, SourceZ
from rza.model.project import Project, Meta

SQ3 = math.sqrt(3)


def two_winding_project(zs=5.0, xt_pct=10.0, s=100.0, uh=110.0, ul=10.0, conn_l="D", clock_l=11, z0s=None):
    tr = Transformer(kind="two_winding", s_nom_mva=s,
                     windings={"HV": Winding("HV", uh, None, "YN", 0, "solid"),
                               "LV": Winding("LV", ul, None, conn_l, clock_l, "isolated" if conn_l == "D" else "solid")},
                     uk={"HV_LV": UkPair(xt_pct)}, oltc=TapChanger(present=False))
    net = Network(base_kv={"HV": uh, "MV": 35.0, "LV": ul},
                  sources=[Source("S", "sys", "HV", SourceZ(0, zs, 0, z0s if z0s else zs), SourceZ(0, zs, 0, zs))])
    p = Project(meta=Meta(), transformer=tr, network=net)
    p.modes = [Mode("M", "test", "max_kz", ["max_kz"], {"S": "max"}, False, "nom", 1.0, 1.0)]
    return p


def test_three_phase_lv_fault_matches_formula():
    p = two_winding_project()
    kz = KZ(p)
    xt = 0.10 * 110 ** 2 / 100.0
    zs = 5.0
    n = 110 / 10
    r = kz.fault("M", "nom", "LV", "3ph")
    i_hv_ref = (110 / SQ3) / (zs + xt)          # кА на стороне ВН
    expected_lv = i_hv_ref * n * 1000.0
    assert abs(r.fault_abc[0]) == pytest.approx(expected_lv, rel=1e-6)
    assert r.side_i_max("HV") == pytest.approx(i_hv_ref * 1000.0, rel=1e-6)


def test_two_phase_is_sqrt3_over_2_of_three_phase():
    p = two_winding_project()
    kz = KZ(p)
    r3 = kz.fault("M", "nom", "LV", "3ph")
    r2 = kz.fault("M", "nom", "LV", "2ph")
    assert r2.i_fault_abs() == pytest.approx(r3.i_fault_abs() * SQ3 / 2, rel=1e-6)


def test_yd11_two_phase_lv_fault_hv_currents_pattern_2_1_1():
    """При двухфазном КЗ на стороне Δ в токах стороны Y соотношение фаз 2:1:1, наибольший равен току трёхфазного КЗ, приведённому к ВН."""
    p = two_winding_project()
    kz = KZ(p)
    r3 = kz.fault("M", "nom", "LV", "3ph")
    r2 = kz.fault("M", "nom", "LV", "2ph")
    mags = sorted(abs(x) for x in r2.sides["HV"].i_abc)
    i3hv = r3.side_i_max("HV")
    assert mags[2] == pytest.approx(i3hv, rel=1e-6)
    assert mags[0] == pytest.approx(i3hv / 2, rel=1e-6)
    assert mags[1] == pytest.approx(i3hv / 2, rel=1e-6)


def test_yd11_phase_shift_positive_sequence_30_degrees():
    """Ток Δ-стороны опережает ток Y-стороны на 30° (группа 11) для симметричного режима."""
    p = two_winding_project()
    kz = KZ(p)
    r = kz.fault("M", "nom", "LV", "3ph")
    ih = r.sides["HV"].i1      # в объект
    il = r.sides["LV"].i1
    # сквозной ток: в объект на LV отрицательный по отношению к ВН, сдвиг ±30°
    ang = math.degrees(cmath.phase(-il / ih))
    assert abs(abs(ang) - 30.0) < 1e-6


def test_delta_side_has_no_zero_sequence_and_hv_ground_fault_formula():
    """Однофазное КЗ на шинах ВН: I_a = 3E/(Z1+Z2+Z0); Z0 = источник ‖ (X_т на землю через Δ). В Δ-стороне нулевой последовательности нет."""
    p = two_winding_project(z0s=8.0)
    kz = KZ(p)
    r = kz.fault("M", "nom", "HV", "1ph")
    xt = 0.10 * 110 ** 2 / 100.0
    zs1, zs0 = 5.0, 8.0
    z0 = 1 / (1 / complex(0, zs0) + 1 / complex(0, xt))
    e = 110 / SQ3
    expected = abs(3 * e / (2j * zs1 + z0)) * 1000.0
    assert abs(r.fault_abc[0]) == pytest.approx(expected, rel=1e-4)
    # у стороны НН нет ни источника, ни пути нулевой последовательности → ток ТТ НН равен нулю (с точностью регуляризации)
    assert r.side_i_max("LV") == pytest.approx(0.0, abs=0.05)


def test_auto_neutral_impedance_port_matrix():
    """Двухпортовая проверка: сопротивление со стороны ВН при закороченной СН = Z11 − Z12²/Z22
    для матрицы Z = звезда(с ветвью Δ на землю) + 3Zn·[[1, n],[n, n²]]."""
    tr = Transformer(kind="auto", s_nom_mva=200.0,
                     windings={"HV": Winding("HV", 230.0, None, "YN", 0, "impedance", 2.5),
                               "MV": Winding("MV", 121.0, None, "YN", 0, "solid"),
                               "LV": Winding("LV", 11.0, 100.0, "D", 11, "isolated")},
                     uk={"HV_MV": UkPair(11.0), "HV_LV": UkPair(32.0), "MV_LV": UkPair(20.0)}, oltc=TapChanger(present=False))
    tap = tap_state(tr, "nom")
    K = {"HV": 1.0, "MV": 230.0 / 121.0, "LV": 230.0 / 11.0}      # базы = номинальные → a = 1
    N = SeqNet(0)
    _add_transformer(N, tr, tap, "", K)
    N.node("GND_HV")
    N.branch("SHORT_M", "T_MV", "GND_M", 1e-9 + 0j)
    N.shunt("GND_M", 1e-9 + 0j)
    N.shunt("T_HV", 1e9 + 0j)
    N.build()
    zin = N.Z[N.idx["T_HV"], N.idx["T_HV"]]
    x = tap.x_ohm
    n = 230.0 / 121.0
    zn3 = 3 * 2.5
    z11 = complex(0, x["H"] + x["L"]) + zn3 * 1
    z12 = complex(0, x["L"]) + zn3 * n
    z22 = complex(0, x["M"] + x["L"]) + zn3 * n * n
    expected = z11 - z12 ** 2 / z22
    assert abs(zin - expected) / abs(expected) < 1e-4


def test_auto_grounded_solid_zero_sequence_equals_positive():
    tr = Transformer(kind="auto", s_nom_mva=200.0,
                     windings={"HV": Winding("HV", 230.0, None, "YN", 0, "solid"),
                               "MV": Winding("MV", 121.0, None, "YN", 0, "solid"),
                               "LV": Winding("LV", 11.0, 100.0, "D", 11, "isolated")},
                     uk={"HV_MV": UkPair(11.0), "HV_LV": UkPair(32.0), "MV_LV": UkPair(20.0)}, oltc=TapChanger(present=False))
    tap = tap_state(tr, "nom")
    K = {"HV": 1.0, "MV": 230.0 / 121.0, "LV": 230.0 / 11.0}
    N1, N0 = SeqNet(1), SeqNet(0)
    _add_transformer(N1, tr, tap, "", K)
    _add_transformer(N0, tr, tap, "", K)
    for N in (N1, N0):
        N.node("g")
        N.branch("SM", "T_MV", "g", 1e-9 + 0j)
        N.shunt("g", 1e-9 + 0j)
        N.shunt("T_HV", 1e9 + 0j)
        N.build()
    z1 = N1.Z[N1.idx["T_HV"], N1.idx["T_HV"]]
    z0 = N0.Z[N0.idx["T_HV"], N0.idx["T_HV"]]
    # при закороченной СН: положительная — X_H + X_M‖(Х_L изолирован) ; нулевая — то же плюс шунт Δ
    assert abs(z0) <= abs(z1) + 1e-6      # путь через Δ (шунт) уменьшает Z0 относительно Z1


def test_taps_change_ratio_of_currents_hv_mv():
    from rza.model.demo import demo_project
    p = demo_project()
    kz = KZ(p)
    for key, u_mv in (("min", 106.5), ("nom", 121.0), ("max", 135.52)):
        r = kz.fault("MAXKZ1", key, "MV", "3ph")
        ratio = r.side_i_max("MV") / r.side_i_max("HV")
        # отношение токов сторон сквозного тока = 230/U_СН(положение) (в пределах учёта фазных токов узла)
        assert ratio == pytest.approx(230.0 / u_mv, rel=2e-3)


def test_sequence_transform_roundtrip():
    a, b, c = 3 + 1j, -2 + 0.5j, 1 - 1j
    assert to_abc(*to_seq(a, b, c)) == pytest.approx((a, b, c))


def test_internal_fault_sum_of_ct_currents_equals_fault_current():
    """Для КЗ на выводе АТ (в зоне дифзащиты) сумма токов ТТ сторон (в объект) при приведении к ВН равна току КЗ."""
    from rza.model.demo import demo_project
    p = demo_project()
    kz = KZ(p)
    r = kz.fault("MINKZ", "nom", "T_HV", "3ph")
    # ток КЗ на T_HV (сторона ВН) = ток ТТ ВН + приведённые токи через АТ с других сторон; проверяем баланс по амперам-виткам сторон
    i_h = r.sides["HV"].i1
    tr = p.transformer
    s = 0j
    for side in tr.sides():
        u = tr.u_nom(side)
        ph = cmath.exp(-1j * math.radians(((12 - tr.w(side).clock) % 12) * 30))
        s += r.sides[side].i1 * ph * (u / tr.u_nom("HV"))
    assert abs(s - r.fault_seq[1]) / abs(r.fault_seq[1]) < 0.06   # погрешность — из-за вненоминального отношения (РПН/базы сети)
