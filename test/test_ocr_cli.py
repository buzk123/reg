import importlib.util
import locale
import subprocess
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("ocr_test.py")


def load_ocr_module():
    spec = importlib.util.spec_from_file_location("ocr_test_module", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OcrCliTest(unittest.TestCase):
    def run_script(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            cwd=Path(__file__).parents[1],
            capture_output=True,
            text=True,
            encoding=locale.getpreferredencoding(False),
            errors="replace",
        )

    def test_help_does_not_load_ocr_model(self):
        completed = self.run_script("--help")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("图片路径", completed.stdout)
        self.assertNotIn("Creating model", completed.stdout + completed.stderr)

    def test_missing_image_reports_clear_error(self):
        completed = self.run_script("missing-image.png")

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("图片不存在", completed.stderr)
        self.assertNotIn("Creating model", completed.stdout + completed.stderr)

    def test_create_ocr_disables_mkldnn(self):
        module = load_ocr_module()
        received = {}

        class FakePaddleOcr:
            def __init__(self, **kwargs):
                received.update(kwargs)

        module.create_ocr(FakePaddleOcr)

        self.assertIs(received["enable_mkldnn"], False)

    def test_extract_text_rows_combines_pages(self):
        module = load_ocr_module()

        class FakeResult:
            def __init__(self, texts, scores):
                self.json = {"res": {"rec_texts": texts, "rec_scores": scores}}

        rows = module.extract_text_rows(
            [FakeResult(["第一行"], [0.91]), FakeResult(["第二行"], [0.82])]
        )

        self.assertEqual(rows, [("第一行", 0.91), ("第二行", 0.82)])


if __name__ == "__main__":
    unittest.main()
