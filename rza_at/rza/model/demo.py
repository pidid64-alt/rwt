"""Демонстрационный проект: АТДЦТН-200000/220/110 (условные данные подстанции).

ВНИМАНИЕ: данные сети, ТТ, уставок смежных защит — условные (для демонстрации программы), а не данные реального объекта.
Единственное «справочное» происхождение — u_к (ВН–СН) по положениям РПН: Вып. 13Б, табл. 8.1 (АТДЦТН-200: 19,4 / 11 / 6,7 %).
"""
from __future__ import annotations

from .autotransformer import Transformer, Winding, UkPair, TapChanger, Thermal
from .ct import CT, VT
from .modes import default_modes
from .network import Network, Source, SourceZ, Line, AdjProt, Stage, TccEntry, ParallelAT
from .project import Project, Meta, Assumptions, TerminalAssign, now_iso

DEMO_NOTE = "ДЕМО-ДАННЫЕ: условные значения, не относятся к реальному объекту"


def demo_project() -> Project:
    tr = Transformer(
        kind="auto", manufacturer="(демо)", type_name="АТДЦТН-200000/220/110-У1", serial_number="—", year=2012,
        frequency_hz=50.0, s_nom_mva=200.0, s_typ_mva=100.0,
        windings={
            "HV": Winding("HV", 230.0, None, "YN", 0, "solid", 0.0),
            "MV": Winding("MV", 121.0, None, "YN", 0, "solid", 0.0),
            "LV": Winding("LV", 11.0, 100.0, "D", 11, "isolated", 0.0),
        },
        uk={
            "HV_MV": UkPair(11.0, 19.4, 6.7, None, "Вып. 13Б, табл. 8.1 (АТДЦТН-200: −12 % / 0 / +12 % РПН СН)"),
            "HV_LV": UkPair(32.0, None, None, None, "Каталожное значение, принято постоянным по положениям РПН (демо)"),
            "MV_LV": UkPair(20.0, None, None, None, "Каталожное значение, принято постоянным по положениям РПН (демо)"),
        },
        pk_kw={"HV_MV": 430.0}, p0_kw=100.0, i0_pct=0.45, x0_over_x1=1.0,
        oltc=TapChanger(True, "MV", "line", 6, 6, 2.0, 7, 1, 13, "РПН в линии СН, ±6×2 %"),
        regulating_winding=False,
        series_z_ohm={},
        thermal=Thermal(1.10, 35.0,
                        [{"multiple": 1.3, "minutes": 120.0}, {"multiple": 1.6, "minutes": 45.0}, {"multiple": 2.0, "minutes": 10.0}],
                        "ДЕМО-значения допустимой длительности перегрузки — заменить данными завода/ГОСТ 14209-85", "ONAN"),
        builtin_protections=["Газовая защита (бак)", "Газовая защита РПН", "Реле давления", "Термосигнализаторы"],
        grounding_scheme="Общая нейтраль АТ глухо заземлена; обмотка НН — треугольник",
    )
    hv_l1_prot = AdjProt(
        dist=[Stage(z_ohm=29.0, t_s=0.0, note="I зона ≈ 0,85·Z_л"), Stage(z_ohm=41.0, t_s=0.4, note="II зона"), Stage(z_ohm=80.0, t_s=1.5, note="III зона")],
        i0=[Stage(i_a=2400.0, t_s=0.0), Stage(i_a=1200.0, t_s=0.5), Stage(i_a=600.0, t_s=1.0), Stage(i_a=300.0, t_s=2.0)],
        mtz=[], neg=[Stage(i_a=250.0, t_s=2.5)], source="условные уставки (демо)")
    def mv_prot(z1_ohm: float, i_mtz: float):
        return AdjProt(
            dist=[Stage(z_ohm=round(0.85 * z1_ohm, 2), t_s=0.0), Stage(z_ohm=round(1.2 * z1_ohm, 2), t_s=0.5), Stage(z_ohm=round(2.5 * z1_ohm, 2), t_s=1.2)],
            i0=[Stage(i_a=1500.0, t_s=0.0), Stage(i_a=800.0, t_s=0.5), Stage(i_a=400.0, t_s=1.0), Stage(i_a=200.0, t_s=1.5)],
            mtz=[Stage(i_a=i_mtz, t_s=1.2)], neg=[], source="условные уставки (демо)")
    net = Network(
        base_kv={"HV": 230.0, "MV": 115.0, "LV": 10.5},
        sources=[
            Source("SYS_HV", "Энергосистема 220 кВ", "HV",
                   SourceZ.from_sk(230.0, 8000.0, 12.0, 1.1), SourceZ.from_sk(230.0, 4500.0, 10.0, 1.3), DEMO_NOTE),
            Source("SYS_MV", "Сеть 110 кВ (подпитка)", "MV",
                   SourceZ.from_sk(115.0, 1800.0, 8.0, 1.3), SourceZ.from_sk(115.0, 900.0, 7.0, 1.5), DEMO_NOTE),
        ],
        lines=[
            Line("L1", "ВЛ 220 кВ Л-1", "HV", 80.0, 0.075, 0.42, 0.25, 1.27,
                 Source("REM_L1", "Подпитка с противоположного конца Л-1", "HV", SourceZ.from_sk(230.0, 6000.0, 12.0, 1.1), SourceZ.from_sk(230.0, 3000.0, 10.0, 1.3), DEMO_NOTE),
                 hv_l1_prot),
            Line("L11", "ВЛ 110 кВ Л-11", "MV", 30.0, 0.12, 0.40, 0.35, 1.20, None, mv_prot(12.5, 1000.0)),
            Line("L12", "ВЛ 110 кВ Л-12", "MV", 18.0, 0.12, 0.40, 0.35, 1.20, None, mv_prot(7.5, 1200.0)),
            Line("L13", "ВЛ 110 кВ Л-13", "MV", 40.0, 0.12, 0.40, 0.35, 1.20, None, mv_prot(16.7, 800.0)),
        ],
        tcc=[
            TccEntry("UP_HV", "Вышестоящая защита (резерв ВЛ 220 кВ на противоположном конце)", "upstream", "HV",
                     [Stage(i_a=900.0, t_s=2.5, curve="definite", note="МТЗ/III ступень (дальнее резервирование)")], "условно (демо)"),
            TccEntry("DN_MV", "Нижестоящая защита: МТЗ ВЛ 110 кВ (наибольшая выдержка)", "downstream", "MV",
                     [Stage(i_a=1200.0, t_s=1.2, curve="definite")], "условно (демо)"),
        ],
        parallel_at=ParallelAT(True, True),
        bus_protection={"HV": True, "MV": True, "LV": False},
    )
    cts = [
        CT("TA_HV", "ТТ ВН (выключатель 220 кВ)", "HV", "breaker", "Дифференциальная и резервные защиты", ["87T", "50/51", "46", "50N/51N", "21", "49"],
           600.0, 1.0, "5P", "5P20", 20.0, 30.0, 8.0, 3.0, None, "Y", "to_object"),
        CT("TA_MV", "ТТ СН (выключатель 110 кВ)", "MV", "breaker", "Дифференциальная и резервные защиты", ["87T", "50/51", "46", "50N/51N", "21"],
           1000.0, 1.0, "5P", "5P20", 20.0, 30.0, 8.0, 5.0, None, "Y", "to_object"),
        CT("TA_LV", "ТТ НН (ввод 10 кВ)", "LV", "bushing", "Дифференциальная и резервные защиты", ["87T", "50/51"],
           6000.0, 5.0, "5P", "5P20", 20.0, 30.0, 15.0, 0.3, None, "Y", "to_object"),
        CT("TA_N", "ТТ в нейтрали общей обмотки", "N", "neutral", "Защита от замыканий на землю (по току нейтрали)", ["50N/51N"],
           600.0, 1.0, "5P", "5P10", 10.0, 15.0, 5.0, 3.0, None, "Y", "to_object"),
    ]
    vts = [
        VT("TV_HV", "ТН 220 кВ", "HV", 220.0, 100.0, 100.0, "0,5/3P", "Y/Y/Δ"),
        VT("TV_MV", "ТН 110 кВ", "MV", 110.0, 100.0, 100.0, "0,5/3P", "Y/Y/Δ"),
        VT("TV_LV", "ТН 10 кВ", "LV", 10.0, 100.0, 100.0, "0,5/3P", "Y/Y/Δ"),
    ]
    p = Project(
        meta=Meta(id="demo-at-200", name="Демо: АТДЦТН-200000/220/110", substation="ПС 220/110/10 кВ «Демо»",
                  description="Учебный проект: расчёт уставок РЗА автотрансформатора 200 МВА. " + DEMO_NOTE,
                  author="Инженер РЗА", reviewer="", approver="", version="1.0", date=now_iso()[:10], status="draft",
                  reason="Первичный расчёт", demo=True),
        transformer=tr, cts=cts, vts=vts, network=net, modes=[],
        assumptions=Assumptions(),
        terminals=[
            TerminalAssign("siemens.7ut6.v4_6", "7UT613/63x", "V4.6", ["87T", "50/51", "46", "50N/51N", "49"],
                           {"HV": "Side 1", "MV": "Side 2", "LV": "Side 3"}, "Основной терминал: дифференциальная и резервные защиты"),
            TerminalAssign("template.generic", "шаблон", "—", ["21"], {"HV": "Сторона 1", "MV": "Сторона 2"}, "Дистанционная защита (7UT6 не содержит функции 21)"),
        ],
    )
    p.ensure_modes()
    return p


def blank_project() -> Project:
    """Пустой проект: паспорт АТ 3×обмотки с типовыми данными-заглушками, без сети (валидация потребует ввода исходных данных)."""
    p = demo_project()
    p.meta = Meta(id="blank", name="Новый проект", substation="", description="", author="", version="1.0", date=now_iso()[:10], status="draft", reason="Первичный расчёт", demo=False)
    p.transformer.manufacturer, p.transformer.type_name, p.transformer.serial_number, p.transformer.year = "", "", "", None
    p.network.sources, p.network.lines, p.network.tcc = [], [], []
    p.network.parallel_at.present = False
    p.modes = []
    p.terminals = []
    p.changelog, p.history, p.overrides = [], [], {}
    return p
