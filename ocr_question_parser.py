import argparse
import hashlib
import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
PDF_SUFFIX = ".pdf"

SECTION_RE = re.compile(r"^\s*([一二三四五六七八九十]+)\s*[、.．]")
SECTION_QUESTION_RE = re.compile(
    r"^\s*([一二三四五六七八九十]+)\s*[、.．]\s*(\d{1,3})\s*[、.．]"
)
QUESTION_RE = re.compile(r"^\s*(\d{1,3})\s*[、.．]")
GROUP_SECTION_KEYWORDS = ("阅读", "短文", "看图写话", "写话", "习作", "作文")


@dataclass
class OcrLine:
    text: str
    bbox: list[int]
    page: int
    score: float = 0.0


@dataclass
class QuestionChunk:
    text: str
    lines: list[OcrLine]
    bbox: list[int]
    page_start: int
    page_end: int
    chunk_type: str
    section_title: str | None = None
    question_no: str | None = None
    crop_image: str | None = None
    page_image: str | None = None


def file_md5(file_path: str | Path) -> str:
    md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            md5.update(chunk)
    return md5.hexdigest()


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.strip() for line in text.split("\n") if line.strip())


def bbox_from_points(points) -> list[int] | None:
    if points is None:
        return None

    values = to_plain_data(points)
    if not values:
        return None

    if isinstance(values, Sequence) and len(values) == 4 and all(is_number(v) for v in values):
        left, top, right, bottom = values
        return [int(left), int(top), int(right), int(bottom)]

    xs = []
    ys = []
    for point in values:
        if isinstance(point, Sequence) and len(point) >= 2:
            xs.append(float(point[0]))
            ys.append(float(point[1]))

    if not xs or not ys:
        return None

    return [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]


def merge_bboxes(bboxes: Iterable[Sequence[int]]) -> list[int]:
    usable = [bbox for bbox in bboxes if bbox]
    if not usable:
        return [0, 0, 0, 0]
    return [
        int(min(bbox[0] for bbox in usable)),
        int(min(bbox[1] for bbox in usable)),
        int(max(bbox[2] for bbox in usable)),
        int(max(bbox[3] for bbox in usable)),
    ]


def sort_ocr_lines(lines: Iterable[OcrLine]) -> list[OcrLine]:
    return sorted(lines, key=lambda line: (line.page, line.bbox[1], line.bbox[0]))


def is_section_heading(text: str) -> bool:
    return bool(SECTION_RE.match(text.strip()))


def is_question_heading(text: str) -> bool:
    return bool(QUESTION_RE.match(text.strip()))


def get_question_no(text: str) -> str | None:
    match = QUESTION_RE.match(text.strip())
    return match.group(1) if match else None


def is_group_section(text: str) -> bool:
    return any(keyword in text for keyword in GROUP_SECTION_KEYWORDS)


def build_chunk(
    lines: list[OcrLine],
    page_number: int,
    chunk_type: str,
    section_title: str | None = None,
    question_no: str | None = None,
) -> QuestionChunk | None:
    if not lines:
        return None

    content = clean_text("\n".join(line.text for line in lines))
    if section_title and section_title not in content:
        content = clean_text(f"{section_title}\n{content}")

    return QuestionChunk(
        text=content,
        lines=lines[:],
        bbox=merge_bboxes(line.bbox for line in lines),
        page_start=min(line.page for line in lines) if lines else page_number,
        page_end=max(line.page for line in lines) if lines else page_number,
        chunk_type=chunk_type,
        section_title=section_title,
        question_no=question_no,
    )


def chunk_lines_by_question(lines: list[OcrLine], page_number: int) -> list[QuestionChunk]:
    sorted_lines = sort_ocr_lines(lines)
    chunks: list[QuestionChunk] = []
    current_lines: list[OcrLine] = []
    current_section: str | None = None
    current_question_no: str | None = None
    current_type = "question"
    pending_prefix: list[OcrLine] = []
    group_mode = False

    def flush_current():
        nonlocal current_lines, current_question_no, current_type
        chunk = build_chunk(
            current_lines,
            page_number=page_number,
            chunk_type=current_type,
            section_title=current_section,
            question_no=current_question_no,
        )
        if chunk:
            chunks.append(chunk)
        current_lines = []
        current_question_no = None
        current_type = "question"

    for line in sorted_lines:
        text = line.text.strip()
        if not text:
            continue

        if is_section_heading(text):
            flush_current()
            section_question = SECTION_QUESTION_RE.match(text)
            current_section = (
                f"{section_question.group(1)}、" if section_question else text
            )
            group_mode = is_group_section(text)
            pending_prefix = []
            if group_mode:
                current_lines = [line]
                current_type = "question_group"
            elif section_question:
                current_question_no = section_question.group(2)
                current_lines = [line]
                current_type = "question"
            else:
                pending_prefix = [line]
            continue

        if group_mode:
            current_lines.append(line)
            continue

        if is_question_heading(text):
            flush_current()
            current_question_no = get_question_no(text)
            current_lines = pending_prefix + [line]
            pending_prefix = []
            current_type = "question"
            continue

        if current_lines:
            current_lines.append(line)
        else:
            pending_prefix.append(line)

    flush_current()

    if not chunks and sorted_lines:
        fallback = build_chunk(sorted_lines, page_number=page_number, chunk_type="page")
        if fallback:
            chunks.append(fallback)

    if not chunks and pending_prefix:
        fallback = build_chunk(pending_prefix, page_number=page_number, chunk_type="page")
        if fallback:
            chunks.append(fallback)

    return chunks


def split_lines_into_columns(
    lines: list[OcrLine],
    min_gap: int = 20,
    max_columns: int = 3,
) -> list[list[OcrLine]]:
    if len(lines) < 4:
        return [lines]

    groups = [lines[:]]

    while len(groups) < max_columns:
        best_group_index = None
        best_separator = None
        best_score = None

        for group_index, group in enumerate(groups):
            if len(group) < 4:
                continue

            right_edges = {line.bbox[2] for line in group}
            left_edges = {line.bbox[0] for line in group}
            candidate_separators = {
                (right_edge + left_edge) // 2
                for right_edge in right_edges
                for left_edge in left_edges
                if left_edge - right_edge >= min_gap
            }
            allowed_crossings = max(1, len(group) // 30)

            for separator in candidate_separators:
                crossing_count = sum(
                    line.bbox[0] < separator < line.bbox[2] for line in group
                )
                if crossing_count > allowed_crossings:
                    continue

                left_group = [
                    line
                    for line in group
                    if (line.bbox[0] + line.bbox[2]) / 2 < separator
                ]
                right_group = [line for line in group if line not in left_group]
                if len(left_group) < 2 or len(right_group) < 2:
                    continue

                left_of_separator = [line.bbox[2] for line in group if line.bbox[2] <= separator]
                right_of_separator = [line.bbox[0] for line in group if line.bbox[0] >= separator]
                if not left_of_separator or not right_of_separator:
                    continue

                visual_gap = min(right_of_separator) - max(left_of_separator)
                if visual_gap < min_gap:
                    continue

                score = (min(len(left_group), len(right_group)), visual_gap, -crossing_count)
                if best_score is None or score > best_score:
                    best_score = score
                    best_separator = separator
                    best_group_index = group_index

        if best_group_index is None or best_separator is None:
            break

        group = groups.pop(best_group_index)
        left_group = [
            line
            for line in group
            if (line.bbox[0] + line.bbox[2]) / 2 < best_separator
        ]
        right_group = [line for line in group if line not in left_group]

        groups.extend([left_group, right_group])

    return sorted(groups, key=lambda group: min(line.bbox[0] for line in group))


def chunk_page_lines(lines: list[OcrLine], page_number: int) -> list[QuestionChunk]:
    chunks: list[QuestionChunk] = []
    for column_lines in split_lines_into_columns(lines):
        chunks.extend(chunk_lines_by_question(column_lines, page_number=page_number))
    return chunks


def to_plain_data(value):
    if hasattr(value, "tolist"):
        return value.tolist()
    return value


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def normalize_paddle_results(results, page_number: int) -> list[OcrLine]:
    lines: list[OcrLine] = []

    for result in flatten_result_pages(results):
        if hasattr(result, "json"):
            lines.extend(lines_from_result_json(result.json, page_number))
        elif isinstance(result, dict):
            lines.extend(lines_from_result_json(result, page_number))
        elif is_v2_line(result):
            line = line_from_v2_result(result, page_number)
            if line:
                lines.append(line)

    return [line for line in lines if line.text and line.bbox != [0, 0, 0, 0]]


def flatten_result_pages(results):
    if results is None:
        return []
    if not isinstance(results, list):
        return [results]
    flattened = []
    for item in results:
        if is_v2_line(item) or hasattr(item, "json") or isinstance(item, dict):
            flattened.append(item)
        elif isinstance(item, list):
            flattened.extend(flatten_result_pages(item))
    return flattened


def is_v2_line(item) -> bool:
    return (
        isinstance(item, Sequence)
        and len(item) >= 2
        and isinstance(item[1], Sequence)
        and len(item[1]) >= 2
        and isinstance(item[1][0], str)
    )


def line_from_v2_result(item, page_number: int) -> OcrLine | None:
    bbox = bbox_from_points(item[0])
    if not bbox:
        return None
    text = str(item[1][0]).strip()
    score = float(item[1][1]) if is_number(item[1][1]) else 0.0
    return OcrLine(text=text, bbox=bbox, page=page_number, score=score)


def lines_from_result_json(payload: dict, page_number: int) -> list[OcrLine]:
    data = payload.get("res", payload)
    texts = data.get("rec_texts") or data.get("texts") or []
    scores = data.get("rec_scores") or data.get("scores") or [0.0] * len(texts)
    boxes = (
        data.get("rec_polys")
        or data.get("dt_polys")
        or data.get("rec_boxes")
        or data.get("boxes")
        or []
    )

    lines = []
    for index, text in enumerate(texts):
        bbox = bbox_from_points(boxes[index]) if index < len(boxes) else None
        if not bbox:
            continue
        score = scores[index] if index < len(scores) else 0.0
        lines.append(
            OcrLine(
                text=str(text).strip(),
                bbox=bbox,
                page=page_number,
                score=float(score) if is_number(score) else 0.0,
            )
        )
    return lines


def create_ocr():
    from paddleocr import PaddleOCR

    try:
        return PaddleOCR(
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=False,
        )
    except TypeError:
        return PaddleOCR(use_angle_cls=False, lang="ch", enable_mkldnn=False)


def run_ocr_on_image(ocr, image_path: Path, page_number: int) -> list[OcrLine]:
    if hasattr(ocr, "predict"):
        results = ocr.predict(str(image_path))
    else:
        results = ocr.ocr(str(image_path), cls=False)
    return normalize_paddle_results(results, page_number=page_number)


def render_pdf_pages(pdf_path: Path, page_dir: Path, dpi: int, max_pages: int | None = None) -> list[Path]:
    import fitz

    page_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)
    page_paths = []

    for index, page in enumerate(doc, start=1):
        if max_pages is not None and index > max_pages:
            break
        output = page_dir / f"page_{index:03d}.png"
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)
        pixmap.save(output)
        page_paths.append(output)

    return page_paths


def prepare_image_page(image_path: Path, page_dir: Path) -> list[Path]:
    from PIL import Image

    page_dir.mkdir(parents=True, exist_ok=True)
    output = page_dir / "page_001.png"
    try:
        with Image.open(image_path) as image:
            image.convert("RGB").save(output)
    except Exception:
        shutil.copyfile(image_path, output)
    return [output]


def crop_chunk_image(page_image: Path, chunk: QuestionChunk, crop_path: Path, margin: int) -> None:
    from PIL import Image

    crop_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(page_image) as image:
        width, height = image.size
        left = max(0, chunk.bbox[0] - margin)
        top = max(0, chunk.bbox[1] - margin)
        right = min(width, chunk.bbox[2] + margin)
        bottom = min(height, chunk.bbox[3] + margin)
        image.crop((left, top, right, bottom)).save(crop_path)


def supported_input(path: Path) -> bool:
    return path.suffix.lower() == PDF_SUFFIX or path.suffix.lower() in IMAGE_SUFFIXES


def parse_file(
    input_file: str | Path,
    output_dir: str | Path = "output",
    dpi: int = 200,
    margin: int = 20,
    max_pages: int | None = None,
):
    source = Path(input_file).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"输入文件不存在: {source}")
    if not supported_input(source):
        raise ValueError(f"不支持的文件类型: {source.suffix}")

    output_path = Path(output_dir).expanduser().resolve()
    file_hash = file_md5(source)
    page_dir = output_path / "ocr_pages" / file_hash
    crop_dir = output_path / "question_images" / file_hash

    if source.suffix.lower() == PDF_SUFFIX:
        source_type = "pdf"
        page_images = render_pdf_pages(source, page_dir, dpi=dpi, max_pages=max_pages)
    else:
        source_type = "image"
        page_images = prepare_image_page(source, page_dir)

    ocr = create_ocr()
    all_chunks: list[QuestionChunk] = []

    for page_number, page_image in enumerate(page_images, start=1):
        lines = run_ocr_on_image(ocr, page_image, page_number=page_number)
        chunks = chunk_page_lines(lines, page_number=page_number)

        crop_dir.mkdir(parents=True, exist_ok=True)
        for stale_crop in crop_dir.glob(f"page_{page_number:03d}_q*.png"):
            stale_crop.unlink()

        for index, chunk in enumerate(chunks, start=1):
            crop_path = crop_dir / f"page_{page_number:03d}_q{index:03d}.png"
            crop_chunk_image(page_image, chunk, crop_path, margin=margin)
            chunk.page_image = str(page_image)
            chunk.crop_image = str(crop_path)
            all_chunks.append(chunk)

    documents_file = output_path / "ocr_questions.jsonl"
    report_file = output_path / "ocr_question_report.json"
    save_questions_jsonl(all_chunks, documents_file, source, source_type, file_hash)
    save_report(all_chunks, report_file, source, source_type, file_hash, page_images)

    return {
        "documents_file": str(documents_file),
        "report_file": str(report_file),
        "page_count": len(page_images),
        "question_count": len(all_chunks),
    }


def save_questions_jsonl(
    chunks: list[QuestionChunk],
    output_file: Path,
    source: Path,
    source_type: str,
    file_hash: str,
) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    parsed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(output_file, "w", encoding="utf-8") as f:
        for index, chunk in enumerate(chunks, start=1):
            item = {
                "id": index,
                "page_content": chunk.text,
                "metadata": {
                    "source_type": source_type,
                    "parse_method": "paddleocr",
                    "chunk_type": chunk.chunk_type,
                    "section_title": chunk.section_title,
                    "question_no": chunk.question_no,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "bbox": chunk.bbox,
                    "page_image": chunk.page_image,
                    "crop_image": chunk.crop_image,
                    "source_path": str(source),
                    "file_name": source.name,
                    "file_suffix": source.suffix.lower(),
                    "file_md5": file_hash,
                    "parsed_at": parsed_at,
                },
            }
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def save_report(
    chunks: list[QuestionChunk],
    output_file: Path,
    source: Path,
    source_type: str,
    file_hash: str,
    page_images: list[Path],
) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "source_path": str(source),
        "source_type": source_type,
        "file_md5": file_hash,
        "page_count": len(page_images),
        "question_count": len(chunks),
        "question_chunks": sum(1 for chunk in chunks if chunk.chunk_type == "question"),
        "group_chunks": sum(1 for chunk in chunks if chunk.chunk_type == "question_group"),
        "page_chunks": sum(1 for chunk in chunks if chunk.chunk_type == "page"),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="使用 PaddleOCR 解析图片 PDF/图片，并按题目裁剪保存")
    parser.add_argument("input", help="PDF 或图片路径")
    parser.add_argument("--output", default="output", help="输出目录，默认 output")
    parser.add_argument("--dpi", type=int, default=200, help="PDF 转图片 DPI，默认 200")
    parser.add_argument("--margin", type=int, default=20, help="题目裁剪边距像素，默认 20")
    parser.add_argument("--max-pages", type=int, help="最多解析 PDF 前 N 页，默认解析全部")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    result = parse_file(
        args.input,
        output_dir=args.output,
        dpi=args.dpi,
        margin=args.margin,
        max_pages=args.max_pages,
    )
    print("OCR 题目解析完成")
    print(f"页数: {result['page_count']}")
    print(f"题目块数量: {result['question_count']}")
    print(f"Document JSONL: {result['documents_file']}")
    print(f"解析报告: {result['report_file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
