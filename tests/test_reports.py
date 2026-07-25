import os
from pathlib import Path
from uuid import uuid4

from reports.generate_pdf import generate_pdf_report


ROOT = Path(__file__).resolve().parents[1]


def test_generate_pdf_report_creates_pdf():
    output_dir = ROOT / ".runtime" / "report-tests" / uuid4().hex
    output_path = generate_pdf_report("Line 1\nLine 2", output_dir=str(output_dir))

    assert os.path.exists(output_path)
    assert output_path.startswith(str(output_dir))
    assert output_path.endswith(".pdf")
