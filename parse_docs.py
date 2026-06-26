import json
import hashlib
from pathlib import Path
from datetime import datetime

import pandas as pd

from langchain_core.documents import Document
from langchain_community.document_loaders import (
    PyPDFLoader,
    TextLoader,
    Docx2txtLoader,
    CSVLoader,
)


SUPPORTED_SUFFIXES = {
    ".pdf",
    ".docx",
    ".txt",
    ".md",
    ".csv",
    ".xlsx",
    ".xls",
}


def file_md5(file_path: str) -> str:
    """
    计算文件 MD5，后面可以用来判断重复文件。
    """
    md5 = hashlib.md5()

    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            md5.update(chunk)

    return md5.hexdigest()


def clean_text(text: str) -> str:
    """
    简单清洗文本。
    第一阶段不要清洗太狠，避免把有用内容删掉。
    """
    if not text:
        return ""

    text = text.replace("\x00", "")
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if line:
            lines.append(line)

    return "\n".join(lines)


def add_common_metadata(doc: Document, file_path: str, source_type: str) -> Document:
    """
    给每个 Document 补充统一 metadata。
    """
    path = Path(file_path)

    doc.page_content = clean_text(doc.page_content)

    doc.metadata.update({
        "source_type": source_type,
        "source_path": str(path),
        "file_name": path.name,
        "file_suffix": path.suffix.lower(),
        "file_md5": file_md5(file_path),
        "parsed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    return doc


def load_pdf(file_path: str):
    """
    解析 PDF。
    普通文字 PDF 可以解析。
    扫描版 PDF 需要 OCR，这里暂时不处理。
    """
    loader = PyPDFLoader(file_path)

    docs = []
    for doc in loader.load():
        doc = add_common_metadata(doc, file_path, "pdf")
        if doc.page_content:
            docs.append(doc)

    return docs


def load_docx(file_path: str):
    """
    解析 Word docx。
    注意：这里只支持 .docx，不支持老 .doc。
    """
    loader = Docx2txtLoader(file_path)

    docs = []
    for doc in loader.load():
        doc = add_common_metadata(doc, file_path, "word")
        if doc.page_content:
            docs.append(doc)

    return docs


def load_text(file_path: str):
    """
    解析 txt / markdown。
    """
    loader = TextLoader(file_path, encoding="utf-8", autodetect_encoding=True)

    docs = []
    for doc in loader.load():
        doc = add_common_metadata(doc, file_path, "text")
        if doc.page_content:
            docs.append(doc)

    return docs


def load_csv(file_path: str):
    """
    解析 CSV。
    CSVLoader 默认一行生成一个 Document。
    """
    loader = CSVLoader(
        file_path=file_path,
        encoding="utf-8",
        autodetect_encoding=True,
    )

    docs = []
    for doc in loader.load():
        doc = add_common_metadata(doc, file_path, "csv")
        if doc.page_content:
            docs.append(doc)

    return docs


def load_excel(file_path: str):
    """
    解析 Excel。
    每一行生成一个 Document。
    """
    path = Path(file_path)
    docs = []

    sheets = pd.read_excel(file_path, sheet_name=None)

    file_hash = file_md5(file_path)
    parsed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for sheet_name, df in sheets.items():
        if df.empty:
            continue

        for row_index, row in df.iterrows():
            lines = []

            for col in df.columns:
                value = row[col]

                if pd.isna(value):
                    continue

                lines.append(f"{col}: {value}")

            content = clean_text("\n".join(lines))

            if not content:
                continue

            doc = Document(
                page_content=content,
                metadata={
                    "source_type": "excel",
                    "source_path": str(path),
                    "file_name": path.name,
                    "file_suffix": path.suffix.lower(),
                    "sheet_name": sheet_name,
                    "row_index": int(row_index),
                    "file_md5": file_hash,
                    "parsed_at": parsed_at,
                }
            )

            docs.append(doc)

    return docs


def load_file(file_path: str):
    """
    根据文件后缀选择对应 Loader。
    """
    suffix = Path(file_path).suffix.lower()

    if suffix == ".pdf":
        return load_pdf(file_path)

    if suffix == ".docx":
        return load_docx(file_path)

    if suffix in [".txt", ".md"]:
        return load_text(file_path)

    if suffix == ".csv":
        return load_csv(file_path)

    if suffix in [".xlsx", ".xls"]:
        return load_excel(file_path)

    raise ValueError(f"暂不支持的文件类型: {suffix}")


def save_jsonl(docs, output_file: str):
    """
    保存为 JSONL。
    一行一个 Document。
    """
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        for i, doc in enumerate(docs):
            item = {
                "id": i,
                "page_content": doc.page_content,
                "metadata": doc.metadata,
            }

            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def save_preview(docs, output_file: str, limit: int = 20):
    """
    保存预览文件，方便你快速看解析效果。
    """
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        for i, doc in enumerate(docs[:limit]):
            f.write("=" * 80 + "\n")
            f.write(f"Document ID: {i}\n")
            f.write(f"Metadata: {json.dumps(doc.metadata, ensure_ascii=False)}\n")
            f.write("-" * 80 + "\n")
            f.write(doc.page_content[:2000])
            f.write("\n\n")


def scan_folder(input_dir: str):
    """
    扫描目录下所有支持的文档。
    """
    input_path = Path(input_dir)

    if not input_path.exists():
        raise FileNotFoundError(f"输入目录不存在: {input_dir}")

    all_docs = []

    success_files = []
    failed_files = []
    skipped_files = []

    for file_path in input_path.rglob("*"):
        if not file_path.is_file():
            continue

        suffix = file_path.suffix.lower()

        if suffix not in SUPPORTED_SUFFIXES:
            skipped_files.append(str(file_path))
            print(f"跳过不支持文件: {file_path}")
            continue

        try:
            docs = load_file(str(file_path))
            all_docs.extend(docs)
            success_files.append(str(file_path))

            print(f"解析成功: {file_path}，Document 数量: {len(docs)}")

        except Exception as e:
            failed_files.append({
                "file": str(file_path),
                "error": str(e),
            })

            print(f"解析失败: {file_path}，原因: {e}")

    print("\n========== 解析统计 ==========")
    print(f"成功文件数: {len(success_files)}")
    print(f"失败文件数: {len(failed_files)}")
    print(f"跳过文件数: {len(skipped_files)}")
    print(f"总 Document 数量: {len(all_docs)}")

    return all_docs, success_files, failed_files, skipped_files


def save_report(success_files, failed_files, skipped_files, output_file: str):
    """
    保存解析报告。
    """
    report = {
        "success_count": len(success_files),
        "failed_count": len(failed_files),
        "skipped_count": len(skipped_files),
        "success_files": success_files,
        "failed_files": failed_files,
        "skipped_files": skipped_files,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


def main():
    input_dir = "data/raw"
    output_dir = "output"

    documents_file = f"{output_dir}/documents.jsonl"
    preview_file = f"{output_dir}/preview.txt"
    report_file = f"{output_dir}/parse_report.json"

    docs, success_files, failed_files, skipped_files = scan_folder(input_dir)

    save_jsonl(docs, documents_file)
    save_preview(docs, preview_file)
    save_report(success_files, failed_files, skipped_files, report_file)

    print("\n========== 输出文件 ==========")
    print(f"Document JSONL: {documents_file}")
    print(f"预览文件: {preview_file}")
    print(f"解析报告: {report_file}")


if __name__ == "__main__":
    main()