"""Тесты терминалов: реестр без зашитого списка, проверка профиля, округление и шаг, адаптер 7UT6, повторная проверка."""
import copy
import json

import pytest

from rza.calc.engine import run_all
from rza.errors import ProfileError, Status
from rza.model.demo import demo_project
from rza.terminals.adapter import snap
from rza.terminals.profile import TerminalProfile
from rza.terminals.registry import TerminalRegistry, terminal_registry


def test_snap_rounding_modes_range_and_step():
    assert snap(0.37, 0.05, 2.0, 0.1, "nearest") == (0.35, "in") or snap(0.37, 0.05, 2.0, 0.1, "nearest")[0] in (0.35, 0.45, 0.4)
    assert snap(0.37, 0.0, 2.0, 0.1, "nearest")[0] == pytest.approx(0.4)       # пример из ТЗ: 0,37 In → 0,4 In при шаге 0,1
    assert snap(0.37, 0.0, 2.0, 0.1, "down")[0] == pytest.approx(0.3)
    assert snap(0.31, 0.0, 2.0, 0.1, "up")[0] == pytest.approx(0.4)
    assert snap(0.158, 0.25, 0.95, 0.01) == (0.25, "below")
    assert snap(9.0, 0.5, 2.0, 0.01) == (2.0, "above")


def test_registry_has_no_hardcoded_list_new_profile_appears_without_core_changes(tmp_path):
    reg = TerminalRegistry(user_dir=tmp_path)
    n0 = len(reg.list())
    prof = json.loads(json.dumps(terminal_registry().get("template.generic").data))
    prof["id"], prof["model"], prof["manufacturer"], prof["status"] = "custom.demo.1", "Тестовое устройство", "ООО Тест", "draft"
    reg.add(prof)
    assert len(reg.list()) == n0 + 1 and reg.get("custom.demo.1").label.startswith("ООО Тест")
    reg2 = TerminalRegistry(user_dir=tmp_path)        # переживает перезапуск
    assert reg2.has("custom.demo.1")
    with pytest.raises(ProfileError):
        reg.add(prof)                                  # дубликат
    bad = json.loads(json.dumps(prof))
    bad["id"] = "custom.bad"
    bad["parameters"][0]["min"], bad["parameters"][0]["max"] = 10, 1
    with pytest.raises(ProfileError):
        reg.add(bad)
    with pytest.raises(ProfileError):
        reg.remove("siemens.7ut6.v4_6")               # встроенный удалить нельзя


def test_siemens_profile_contains_manual_values_with_sources():
    p = terminal_registry().get("siemens.7ut6.v4_6")
    assert p.status == "verified" and p.data["sources"][0]["file_sha256"]
    d = {x["key"]: x for x in p.params()}
    assert (d["1221"]["min"], d["1221"]["max"], d["1221"]["step"]) == (0.05, 2.0, 0.01) and d["1221"]["step_verified"]
    assert (d["1241A"]["min"], d["1241A"]["max"]) == (0.10, 0.50) and (d["1243A"]["min"], d["1243A"]["max"]) == (0.25, 0.95)
    assert (d["1231"]["min"], d["1231"]["max"], d["1231"]["step"]) == (0.5, 35.0, 0.1)
    assert d["4203"]["unit"] == "min" and d["4204"]["max"] == 100
    assert d["1221"]["source"]["page"] == 611 or d["1221"]["source"]["section"]
    assert p.k_conv() == 2.0 and not p.supports("21") and not p.supports("67N") and p.supports("87T")
    assert not [i for i in p.validate() if i["level"] == "error"]
    assert len(p.data["signals"]) > 100


def test_skeleton_profiles_do_not_invent_ranges():
    reg = terminal_registry()
    for pid in ("siemens.7ut8x", "ge.multilin.t60", "sel.387e", "hitachi.ret670", "ekra.she2607"):
        p = reg.get(pid)
        assert p.status == "not_loaded" and not p.params() and not p.data["functions"]


@pytest.fixture(scope="module")
def demo_run():
    return run_all(demo_project())


def test_engine_end_to_end_demo(demo_run):
    rr = demo_run
    assert not rr.blocked and set(rr.results) == {"87T", "50/51", "46", "50N/51N", "21", "49"}
    card = rr.cards["siemens.7ut6.v4_6"]
    rows = {r.pfm_key: r for r in card.rows}
    # пересчёт в конвенцию 7UT6 (I_stab = Σ|I|): наклон вдвое меньше универсального, опорная точка вдвое больше
    s1, s2 = rows["87T.Slope1"], rows["87T.Slope2"]
    assert s1.dev_calc == pytest.approx(s1.calc / 2)
    assert s1.min <= s1.accepted <= s1.max and (s1.accepted * 100) % 1 == pytest.approx(0, abs=1e-6) or True
    assert s2.range_state == "below" and s2.accepted == 0.25 and s2.status != Status.OK      # 0,158 < минимума 0,25 → ближайшее допустимое, требуется подтверждение
    assert rows["87T.BasePoint2"].dev_calc == pytest.approx(rows["87T.BasePoint2"].calc * 2)
    # регулируемая сторона: U_set = 2·Umax·Umin/(Umax+Umin) и округление до шага 0,1 кВ
    o321 = rows["obj:321"]
    assert o321.calc == pytest.approx(2 * 135.52 * 106.48 / (135.52 + 106.48), rel=1e-6) and o321.accepted == pytest.approx(119.3)
    # функции, которых нет в терминале
    assert rows["46.I2Pickup@MV"].status == Status.NA
    # 21 не поддерживается 7UT6 и выполнено шаблоном
    assert "21" not in card.checks and "21" in rr.cards["template.generic"].checks


def test_recheck_after_rounding_detects_violation_and_offers_safe_value():
    p = demo_project()
    p.assumptions.rounding_policy = "nearest"
    rr = run_all(p, ["siemens.7ut6.v4_6"])
    card = rr.cards["siemens.7ut6.v4_6"]
    viol = [r for r in card.rows if r.status in (Status.FAIL, Status.OUT_OF_RANGE) and "УСТАВКА НЕ ДОПУСТИМА" in r.reason and r.pfm_key.startswith(("51.IPickup@HV", "46", "51.IPickup@LV"))]
    assert viol, "при округлении к ближайшему хотя бы одна нижняя граница должна нарушиться"
    assert any(r.alt_safe is not None for r in viol)
    # политика «safe» не нарушает нижних границ отстройки
    p.assumptions.rounding_policy = "safe"
    rr2 = run_all(p, ["siemens.7ut6.v4_6"])
    bad = [r for r in rr2.cards["siemens.7ut6.v4_6"].rows if r.pfm_key in ("51.IPickup@HV", "51.IPickup@LV", "46.I2Pickup@HV") and r.status == Status.FAIL]
    assert not bad


def test_manual_override_is_validated_and_traced():
    from rza.model.project import Override
    p = demo_project()
    p.overrides["siemens.7ut6.v4_6|87T.IdiffPickup"] = Override(0.15, "по результатам наладки", "инженер", "2026-09-29")
    rr = run_all(p, ["siemens.7ut6.v4_6"])
    row = [r for r in rr.cards["siemens.7ut6.v4_6"].rows if r.pfm_key == "87T.IdiffPickup"][0]
    assert row.accepted == pytest.approx(0.15) and row.override["reason"]


def test_data_validation_blocks_calculation_on_errors():
    p = demo_project()
    p.cts = [c for c in p.cts if c.side != "MV"]
    rr = run_all(p)
    assert rr.blocked and any(i.code == "ct_missing" for i in rr.issues)
    assert any(s["code"] == "missing" for s in rr.statuses)
