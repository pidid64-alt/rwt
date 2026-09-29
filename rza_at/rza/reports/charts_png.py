"""Графики для отчётов (PNG, matplotlib): времятоковые характеристики и характеристика 87T."""
from __future__ import annotations

import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from ..calc import charts  # noqa: E402

for _f in ("DejaVu Sans",):
    plt.rcParams["font.family"] = _f
plt.rcParams["axes.unicode_minus"] = False


def tcc_png(project, run, side: str, terminal_id: str | None = None) -> bytes | None:
    d = charts.tcc(project, run, side, terminal_id)
    if not d.get("available"):
        return None
    fig, ax = plt.subplots(figsize=(8.2, 4.6), dpi=130)
    colors = {"own": "#0b5cad", "upstream": "#c2410c", "downstream": "#15803d"}
    for s in d["series"]:
        pts = [(p["i"], p["t"]) for p in s["points"] if p["t"] is not None]
        if pts:
            ax.step([p[0] for p in pts], [p[1] for p in pts], where="post", label=s["name"], color=colors.get(s["role"], "#444"), lw=2 if s["role"] == "own" else 1.5,
                    ls="-" if s["role"] == "own" else "--")
    zone = [z for z in d["zone"] if z["ok"]]
    if zone:
        ax.axvspan(min(z["i"] for z in zone), max(z["i"] for z in zone), color="#22c55e", alpha=0.10, label="зона селективности (запас ≥ Δt)")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("Ток на стороне защиты, А (первичный)"); ax.set_ylabel("Время, с")
    ax.set_title(f"Времятоковые характеристики, сторона {side} (Δt = {d['dt']:.2f} с)")
    ax.grid(True, which="both", alpha=0.3); ax.legend(fontsize=7, loc="upper right")
    buf = io.BytesIO(); fig.tight_layout(); fig.savefig(buf, format="png"); plt.close(fig)
    return buf.getvalue()


def char87t_png(project, run, terminal_id: str | None = None) -> bytes | None:
    d = charts.char87t(project, run, terminal_id)
    if not d.get("available"):
        return None
    fig, ax = plt.subplots(figsize=(8.2, 4.6), dpi=130)
    ax.plot([c[0] for c in d["curve"]], [c[1] for c in d["curve"]], color="#0b5cad", lw=2, label="порог срабатывания")
    ax.scatter([p["x"] for p in d["ext"]], [p["y"] for p in d["ext"]], s=14, color="#15803d", label="внешние КЗ: расчётный небаланс")
    ax.scatter([p["x"] for p in d["int"]], [p["y"] for p in d["int"]], s=14, color="#b91c1c", label="КЗ в зоне: I_диф")
    ax.set_xlabel("I_торм = ½Σ|I|, о.е. I_nO"); ax.set_ylabel("I_диф, о.е. I_nO")
    ax.set_title("Характеристика 87T (универсальная конвенция)"); ax.grid(True, alpha=0.3); ax.legend(fontsize=8)
    buf = io.BytesIO(); fig.tight_layout(); fig.savefig(buf, format="png"); plt.close(fig)
    return buf.getvalue()
