import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image

from ocr_question_parser import (
    OcrLine,
    chunk_lines_by_question,
    chunk_page_lines,
    merge_bboxes,
    parse_file,
    split_lines_into_columns,
)


class OcrQuestionParserTest(unittest.TestCase):
    def test_chunk_lines_by_question_splits_numbered_questions(self):
        lines = [
            OcrLine("一、看拼音，写词语。", [10, 10, 200, 30], 1, 0.99),
            OcrLine("1. 小鸟", [10, 50, 120, 70], 1, 0.98),
            OcrLine("朋友", [20, 80, 130, 100], 1, 0.97),
            OcrLine("2. 春天", [10, 130, 120, 150], 1, 0.98),
        ]

        chunks = chunk_lines_by_question(lines, page_number=1)

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].question_no, "1")
        self.assertEqual(chunks[0].section_title, "一、看拼音，写词语。")
        self.assertIn("朋友", chunks[0].text)
        self.assertEqual(chunks[0].bbox, [10, 10, 200, 100])
        self.assertEqual(chunks[1].question_no, "2")
        self.assertEqual(chunks[1].bbox, [10, 130, 120, 150])

    def test_section_heading_with_first_question_starts_question_one(self):
        lines = [
            OcrLine("三、1.xu shou reng", [10, 10, 200, 30], 1, 0.99),
            OcrLine("(1) zhuan zhuan", [20, 40, 160, 60], 1, 0.98),
            OcrLine("2.C", [10, 80, 80, 100], 1, 0.99),
        ]

        chunks = chunk_lines_by_question(lines, page_number=1)

        self.assertEqual([chunk.question_no for chunk in chunks], ["1", "2"])
        self.assertEqual(chunks[0].section_title, "三、")
        self.assertEqual(chunks[0].bbox, [10, 10, 200, 60])
        self.assertEqual(chunks[1].bbox, [10, 80, 80, 100])

    def test_chunk_lines_by_question_keeps_reading_section_together(self):
        lines = [
            OcrLine("二、阅读短文，完成练习。", [10, 10, 220, 30], 1, 0.99),
            OcrLine("春天来了。", [10, 50, 120, 70], 1, 0.98),
            OcrLine("1. 短文共有几句话？", [10, 90, 180, 110], 1, 0.98),
            OcrLine("2. 小草是什么颜色？", [10, 130, 180, 150], 1, 0.98),
        ]

        chunks = chunk_lines_by_question(lines, page_number=1)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].chunk_type, "question_group")
        self.assertEqual(chunks[0].section_title, "二、阅读短文，完成练习。")
        self.assertIn("1. 短文共有几句话？", chunks[0].text)
        self.assertIn("2. 小草是什么颜色？", chunks[0].text)

    def test_chunk_lines_by_question_falls_back_to_page_chunk(self):
        lines = [
            OcrLine("没有明显题号的一页内容", [10, 10, 220, 30], 1, 0.99),
            OcrLine("继续保留，避免丢失", [10, 50, 180, 70], 1, 0.98),
        ]

        chunks = chunk_lines_by_question(lines, page_number=1)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].chunk_type, "page")
        self.assertEqual(chunks[0].bbox, [10, 10, 220, 70])

    def test_merge_bboxes_uses_outer_bounds(self):
        self.assertEqual(
            merge_bboxes([[10, 20, 50, 60], [5, 30, 80, 90]]),
            [5, 20, 80, 90],
        )

    def test_chunk_page_lines_splits_columns_before_question_chunking(self):
        lines = [
            OcrLine("1. 左栏第一题", [10, 10, 160, 30], 1, 0.99),
            OcrLine("左栏内容", [10, 50, 160, 70], 1, 0.98),
            OcrLine("1. 右栏第一题", [500, 12, 680, 32], 1, 0.99),
            OcrLine("右栏内容", [500, 52, 680, 72], 1, 0.98),
        ]

        chunks = chunk_page_lines(lines, page_number=1)

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0].bbox, [10, 10, 160, 70])
        self.assertEqual(chunks[1].bbox, [500, 12, 680, 72])

    def test_split_columns_tolerates_footer_crossing_separator(self):
        lines = [
            OcrLine("left 1", [84, 160, 449, 187], 1, 0.99),
            OcrLine("left 2", [110, 290, 154, 322], 1, 0.99),
            OcrLine("left 3", [113, 340, 450, 364], 1, 0.99),
            OcrLine("left footer", [401, 1182, 508, 1202], 1, 0.99),
            OcrLine("middle title", [481, 73, 579, 97], 1, 0.99),
            OcrLine("middle 1", [512, 205, 838, 228], 1, 0.99),
            OcrLine("middle 2", [513, 248, 837, 272], 1, 0.99),
            OcrLine("middle 3", [514, 291, 839, 316], 1, 0.99),
            OcrLine("cover title", [956, 250, 1650, 360], 1, 0.99),
            OcrLine("cover label 1", [1017, 946, 1131, 1011], 1, 0.99),
            OcrLine("cover label 2", [1256, 129, 1336, 180], 1, 0.99),
        ]

        columns = split_lines_into_columns(lines)

        self.assertEqual(len(columns), 3)
        self.assertEqual({line.text for line in columns[0]}, {"left 1", "left 2", "left 3", "left footer"})
        self.assertEqual({line.text for line in columns[1]}, {"middle title", "middle 1", "middle 2", "middle 3"})
        self.assertEqual({line.text for line in columns[2]}, {"cover title", "cover label 1", "cover label 2"})

    def test_parse_image_saves_absolute_source_image_paths(self):
        with TemporaryDirectory(dir=Path.cwd()) as temp_dir:
            temp_path = Path(temp_dir)
            source = temp_path / "question.png"
            Image.new("RGB", (120, 80), "white").save(source)
            relative_output = Path(temp_path.name) / "result"
            lines = [OcrLine("1. image question", [10, 10, 100, 40], 1, 0.99)]

            with (
                patch("ocr_question_parser.create_ocr", return_value=object()),
                patch("ocr_question_parser.run_ocr_on_image", return_value=lines),
            ):
                result = parse_file(source, output_dir=relative_output)

            item = json.loads(Path(result["documents_file"]).read_text(encoding="utf-8"))
            self.assertTrue(Path(result["documents_file"]).is_absolute())
            self.assertTrue(Path(item["metadata"]["page_image"]).is_absolute())
            self.assertTrue(Path(item["metadata"]["crop_image"]).is_absolute())
            self.assertTrue(Path(item["metadata"]["crop_image"]).is_file())


if __name__ == "__main__":
    unittest.main()
