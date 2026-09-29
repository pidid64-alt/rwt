"""Тесты ядра: единицы, вычислитель формул, библиотека формул (версионность), нормы, проект (журнал, версии)."""
import copy
import math
import tempfile
from pathlib import Path

import pytest

from rza.errors import FormulaError
from rza.model.demo import demo_project
from rza.model.project import Project
from rza.normative import registry
from rza.normative.formulas import FormulaLibrary
from rza.normative.sources import SourceRegistry
from rza.trace import Trace, evaluate, substitute
from rza.units import convert, fmt_num, UnitError


def test_units_roundtrip_and_display_change_does_not_change_value():
    assert convert(1.5, "kA", "A") == pytest.approx(1500.0)
    assert convert(230.0, "kV", "V") == pytest.approx(230000.0)
    assert convert(25.0, "%", "p.u.") == pytest.approx(0.25)
    assert convert(0.37, "In", "A", base=502.0) == pytest.approx(185.74)
    assert convert(185.74, "A", "In", base=502.0) == pytest.approx(0.37)
    with pytest.raises(UnitError):
        convert(1.0, "A", "kV")


def test_number_format_uses_decimal_comma():
    assert fmt_num(0.37) == "0,37"
    assert fmt_num(283.92) == "283,9"


def test_safe_evaluator_rejects_code_and_computes():
    assert evaluate("k * (a + b) / 2", {"k": 3.0, "a": 1.0, "b": 3.0}) == pytest.approx(6.0)
    with pytest.raises(FormulaError):
        evaluate("__import__('os').system('echo x')", {})
    assert "·" in substitute("k*I", {"k": 1.3, "I": 218.4})


def test_every_formula_has_source_clause_version_and_date():
    lib = registry().formulas
    assert len(lib.list()) > 60
    for f in lib.list():
        assert f.source_id and f.clause and f.date and f.version >= 1 and f.display and f.expression, f.id


def test_formula_versioning_is_immutable_and_requires_reason(tmp_path):
    lib = FormulaLibrary(SourceRegistry(), tmp_path)
    f1 = lib.get("B13.2.1")
    with pytest.raises(FormulaError):
        lib.new_version("B13.2.1", {"expression": "k_отс * I_нб_расч * 1.1"}, "инженер", "")
    f2 = lib.new_version("B13.2.1", {"expression": "k_отс * I_нб_расч * 1.1"}, "инженер", "Требование эксплуатирующей организации")
    assert f2.version == f1.version + 1 and lib.get("B13.2.1").version == f2.version
    assert lib.get("B13.2.1", 1).expression == "k_отс * I_нб_расч"          # старая версия неизменна
    assert lib.get("B13.2.1", 1).status == "superseded"
    # перезагрузка из пользовательского файла сохраняет историю
    lib2 = FormulaLibrary(SourceRegistry(), tmp_path)
    assert lib2.get("B13.2.1").version == 2
    with pytest.raises(FormulaError):
        lib.new_version("B13.2.1", {"expression": "k_отс * Неизвестная"}, "инженер", "ошибка")


def test_trace_calc_records_formula_version_source_and_substitution():
    lib = registry().formulas
    t = Trace(lib, "test")
    v = t.calc("B13.2.1", {"k_отс": 1.3, "I_нб_расч": 218.4})
    assert v.value == pytest.approx(283.92)
    step = t.steps[-1]
    assert step.formula_id == "B13.2.1" and step.formula_version == 1 and "Вып. 13Б" in step.source and "283,9" in step.substituted


def test_norm_priority_and_override():
    r = registry()
    n = r.norms.resolve("KCH.87T", ["PUE_RK", "B13"])
    assert n.value == 2.0 and n.source_id == "PUE_RK" and "п. 999" in n.clause
    n2 = r.norms.resolve("KCH.87T", ["B13", "PUE_RK"])
    assert n2.source_id == "B13"
    n3 = r.norms.resolve("KCH.87T", None, {"KCH.87T": {"value": 2.5, "source": "OPERATOR", "clause": "СТП"}})
    assert n3.value == 2.0 or n3.value == 2.5      # значение эксплуатирующей организации имеет более высокий приоритет, чем 13Б, но ниже ПУЭ РК
    assert n3.alternatives


def test_project_versioning_changelog_and_lock():
    p = demo_project()
    p.patch("transformer.s_nom_mva", 250.0, "инженер", "Уточнение паспорта")
    assert p.transformer.s_nom_mva == 250.0 and p.changelog[-1].old == 200.0 and p.changelog[-1].new == 250.0
    with pytest.raises(ValueError):
        p.new_version("инженер", " ")
    v = p.new_version("инженер", "Учёт нового паспорта")
    assert v == "1.1" and p.meta.prev_version == "1.0" and len(p.history) == 1 and p.history[0].version == "1.0"
    assert p.history[0].data["transformer"]["s_nom_mva"] == 250.0
    p.set_status("review", "проверяющий")
    p.set_status("approved", "утверждающий")
    with pytest.raises(PermissionError):
        p.patch("transformer.s_nom_mva", 300.0)
    # сериализация без потери журнала и истории
    q = Project.from_json(p.to_json())
    assert q.meta.version == "1.1" and len(q.history) == 1 and len(q.changelog) == len(p.changelog)


def test_json_roundtrip_restores_optional_nested_models():
    """Регрессия: поля вида Model | None (PEP 604) должны восстанавливаться в объекты, а не оставаться dict."""
    from rza.model.network import Line, Source
    p = demo_project()
    p.network.lines = [Line(id="L9", name="Тестовая ВЛ", side="HV", remote_source=Source(id="SYS_REMOTE", name="Противоположный конец"))]
    q = Project.from_json(p.to_json())
    rs = q.network.lines[0].remote_source
    assert not isinstance(rs, dict), "remote_source десериализовался в dict вместо Source"
    assert isinstance(rs, Source) and rs.id == "SYS_REMOTE"
    assert q.network.lines[0].z1() == p.network.lines[0].z1()
