"""The tutorial notebook is committed clean: it ships without outputs or execution counts.

Running it fills in real catalog names, table names and data rows. Those must never reach a
public repository, so this fails if someone commits a notebook they have executed.
"""

from __future__ import annotations

import json
from pathlib import Path

NOTEBOOK = Path(__file__).parent.parent / "notebooks" / "tutorial.ipynb"


def test_tutorial_notebook_has_no_outputs():
    cells = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    code_cells = [cell for cell in cells if cell["cell_type"] == "code"]

    assert code_cells
    assert all(cell["outputs"] == [] for cell in code_cells), "clear the notebook's outputs"
    assert all(cell["execution_count"] is None for cell in code_cells)
