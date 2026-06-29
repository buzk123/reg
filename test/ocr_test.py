import argparse
from pathlib import Path

from paddleocr import PaddleOCR


DEFAULT_IMAGE = Path(__file__).resolve().parent / "raw" / "Snipaste_2026-06-29_23-06-52.png"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="使用 PaddleOCR 识别单张图片")
    parser.add_argument("image", nargs="?", help="图片路径（默认使用测试图片）")
    return parser, parser.parse_args(argv)


def create_ocr(ocr_class=PaddleOCR):
    return ocr_class(
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
        enable_mkldnn=False,
    )


def extract_text_rows(results):
    rows = []
    for result in results:
        payload = result.json
        data = payload.get("res", payload)
        rows.extend(zip(data.get("rec_texts", []), data.get("rec_scores", [])))
    return rows


def main(argv=None):
    parser, args = parse_args(argv)
    image_path = Path(args.image).expanduser().resolve() if args.image else DEFAULT_IMAGE

    if not image_path.is_file():
        parser.error(f"图片不存在: {image_path}")

    ocr = create_ocr()
    rows = extract_text_rows(ocr.predict(str(image_path)))

    for index, (text, score) in enumerate(rows, start=1):
        print(f"{index:03d}\t{float(score):.4f}\t{text}")

    print(f"\n识别完成，共 {len(rows)} 个文本块")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
