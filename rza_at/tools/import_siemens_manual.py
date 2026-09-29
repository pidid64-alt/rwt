"""Импорт параметров Siemens 7UT6x из PDF-руководства в профиль терминала.

    python tools/import_siemens_manual.py /путь/к/7UT6x_Manual_A2_V040101_en.pdf

Требуется PyMuPDF (pip install pymupdf). Результат — rza/terminals/profiles/siemens_7ut6_v4_6.json.
Для другой версии руководства обновите константы DOC/STEPS/MAPPING в rza/terminals/importers/siemens_siprotec4_manual.py
и сверьте сообщения о несопоставленных адресах.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rza.terminals.importers.siemens_siprotec4_manual import import_manual  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    out = Path(__file__).resolve().parents[1] / "rza" / "terminals" / "profiles"
    res = import_manual(sys.argv[1], out)
    print("Импорт выполнен:", res)
