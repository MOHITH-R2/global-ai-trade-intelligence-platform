import os
from reports.generate_pdf import generate_pdf_report


def test_generate_pdf_report_creates_pdf(tmp_path):
    output_path = generate_pdf_report("Line 1\nLine 2", output_dir=str(tmp_path))
    assert os.path.exists(output_path)
    assert output_path.startswith(str(tmp_path))
    assert output_path.endswith(".pdf")
