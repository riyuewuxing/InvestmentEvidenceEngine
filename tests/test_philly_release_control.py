"""Synthetic workbook structure control, not historical archive evidence."""
import importlib.util
import io
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture
def control(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("philly_control", SCRIPTS / "public_philly_employ_control.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "philly_control", module)
    spec.loader.exec_module(module)
    return module


def test_release_row_missing_not_latest(control):
    rows = [
        ("Nonfarm Payroll Employment (EMPLOY)", None, None, None, None),
        ("M/M Change, Thousands of Employees", None, None, None, None),
        ("Date", "First", "Second", "Third", "Most_Recent"),
        ("2025:M8", 22, None, -26, 999),
    ]
    assert control.row_fields(rows)["release_values"] == [22000, None, -26000]
    with pytest.raises(ValueError, match="TARGET_SCOPE"):
        control.row_fields(rows + [rows[-1]])


def test_bounded_workbook_values_and_no_formula(control):
    n = control.NS[1:-1]
    rel = control.REL[1:-1]
    pkg = control.PKG[1:-1]
    def workbook(formula=""):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("xl/workbook.xml", f'<workbook xmlns="{n}" xmlns:r="{rel}"><sheets><sheet name="EMPLOY" r:id="rId1"/></sheets></workbook>')
            z.writestr("xl/_rels/workbook.xml.rels", f'<Relationships xmlns="{pkg}"><Relationship Id="rId1" Type="{rel}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
            rows = [
                ["Nonfarm Employment (EMPLOY)"],
                ["M/M Change, Thousands of Employees"],
                ["Date", "First", "Second", "Third", "Most_Recent"],
                ["2025:M08", 22, -4, -26, 777],
            ]
            cells = []
            for i, row in enumerate(rows, 1):
                items = []
                for j, v in enumerate(row):
                    addr = chr(65 + j) + str(i)
                    if isinstance(v, str):
                        items.append(f'<c r="{addr}" t="inlineStr"><is><t>{v}</t></is></c>')
                    else:
                        items.append(f'<c r="{addr}">{formula if addr == "B4" else ""}<v>{v}</v></c>')
                cells.append(f'<row r="{i}">' + "".join(items) + "</row>")
            z.writestr("xl/worksheets/sheet1.xml", f'<worksheet xmlns="{n}"><sheetData>' + "".join(cells) + "</sheetData></worksheet>")
        return buf.getvalue()
    assert control.parse(workbook())["release_values"] == [22000, -4000, -26000]
    with pytest.raises(ValueError, match="FORMULA"):
        control.parse(workbook("<f>1+21</f>"))
