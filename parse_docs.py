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


# 支持解析的文件类型
# 后面扫描 data/raw 目录时，只会处理这些后缀的文件
SUPPORTED_SUFFIXES = {
    ".pdf",
    ".docx",
    ".txt",
    ".md",
    ".csv",
    ".xlsx",
    ".xls",
}


# 计算文件的 MD5 值
# MD5 可以理解为文件的唯一指纹
# 后面可以用它判断文件是否重复、文件内容是否发生变化
def file_md5(file_path: str) -> str:
    md5 = hashlib.md5()

    # 使用 rb 二进制方式读取文件
    # 不能用普通文本方式读取，因为 PDF、Word、Excel 都不是普通文本
    with open(file_path, "rb") as f:

        # 每次读取 1MB
        # 这样即使文件很大，也不会一次性占用太多内存
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            md5.update(chunk)

    return md5.hexdigest()


# 清洗文本内容
# 这里只做轻量清洗，不做过度处理
# 因为第一阶段解析文档，重点是尽量保留原始信息
def clean_text(text: str) -> str:

    # 如果文本为空，直接返回空字符串
    if not text:
        return ""

    # 去掉空字符
    # 有些 PDF 或 Word 解析后可能会带这种无效字符
    text = text.replace("\x00", "")

    # 统一换行符
    # Windows 常见换行是 \r\n
    # Linux / Mac 常见换行是 \n
    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    lines = []

    # 按行处理文本
    for line in text.split("\n"):

        # 去掉每一行前后的空格
        line = line.strip()

        # 空行不要
        if line:
            lines.append(line)

    # 用换行符重新拼接
    return "\n".join(lines)


# 给每个 Document 添加统一的 metadata
# metadata 是文档的附加信息
# 比如：文件名、文件路径、文件类型、MD5、解析时间等
def add_common_metadata(doc: Document, file_path: str, source_type: str) -> Document:
    path = Path(file_path)

    # 先清洗正文内容
    doc.page_content = clean_text(doc.page_content)

    # 在原有 metadata 基础上补充字段
    # update 不会清空原来的 metadata
    # 比如 PDF Loader 原本可能带 page 页码，这里会保留
    doc.metadata.update({
        "source_type": source_type,
        "source_path": str(path),
        "file_name": path.name,
        "file_suffix": path.suffix.lower(),
        "file_md5": file_md5(file_path),
        "parsed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })

    return doc


# 解析 PDF 文件
# 适合普通文字版 PDF
# 如果是扫描版 PDF，这个方法可能读不到文字，需要后续接 OCR
def load_pdf(file_path: str):
    loader = PyPDFLoader(file_path)

    docs = []

    # PyPDFLoader 通常是一页生成一个 Document
    for doc in loader.load():

        # 添加统一 metadata
        doc = add_common_metadata(doc, file_path, "pdf")

        # 过滤空内容
        if doc.page_content:
            docs.append(doc)

    return docs


# 解析 Word docx 文件
# 这里只支持 .docx，不支持老的 .doc
# 如果 Word 里面有复杂表格、图片、批注，格式可能不会完整保留
def load_docx(file_path: str):
    loader = Docx2txtLoader(file_path)

    docs = []

    for doc in loader.load():
        doc = add_common_metadata(doc, file_path, "word")

        if doc.page_content:
            docs.append(doc)

    return docs


# 解析 txt 和 markdown 文件
def load_text(file_path: str):

    # encoding="utf-8" 表示优先按 UTF-8 读取
    # autodetect_encoding=True 表示如果编码不匹配，会尝试自动识别
    loader = TextLoader(file_path, encoding="utf-8", autodetect_encoding=True)

    docs = []

    for doc in loader.load():
        doc = add_common_metadata(doc, file_path, "text")

        if doc.page_content:
            docs.append(doc)

    return docs


# 解析 CSV 文件
# CSVLoader 默认通常是一行生成一个 Document
def load_csv(file_path: str):
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


# 解析 Excel 文件
# 支持 .xlsx 和 .xls
# 当前设计：每一行生成一个 Document
# 一行里面的内容按 “列名: 值” 组合成文本
def load_excel(file_path: str):
    path = Path(file_path)

    docs = []

    # sheet_name=None 表示读取所有 sheet
    # 返回值是一个字典：
    # key 是 sheet 名称
    # value 是这个 sheet 对应的 DataFrame
    sheets = pd.read_excel(file_path, sheet_name=None)

    # 文件 MD5 只计算一次
    # 不要每一行都重复计算，避免浪费性能
    file_hash = file_md5(file_path)

    # 解析时间也只生成一次
    parsed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 遍历每一个 sheet
    for sheet_name, df in sheets.items():

        # 如果当前 sheet 是空表，直接跳过
        if df.empty:
            continue

        # 遍历 Excel 的每一行
        for row_index, row in df.iterrows():
            lines = []

            # 遍历当前行的每一列
            for col in df.columns:
                value = row[col]

                # 空单元格不加入文本
                if pd.isna(value):
                    continue

                # 拼成 “列名: 值”
                lines.append(f"{col}: {value}")

            # 把当前行的所有列拼成一个文本块
            content = clean_text("\n".join(lines))

            # 如果这一行没有有效内容，就跳过
            if not content:
                continue

            # 手动创建 Document
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


# 根据文件后缀选择对应的解析方法
def load_file(file_path: str):
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


# 保存完整解析结果为 JSONL
# JSONL 是一行一个 JSON
# 比普通 JSON 更适合保存大量文档数据
def save_jsonl(docs, output_file: str):
    output_path = Path(output_file)

    # 如果 output 目录不存在，就自动创建
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:

        for i, doc in enumerate(docs):
            item = {
                "id": i,
                "page_content": doc.page_content,
                "metadata": doc.metadata,
            }

            # ensure_ascii=False 表示中文正常保存
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


# 保存预览文件
# 方便你快速查看解析效果
# 默认只保存前 20 个 Document
def save_preview(docs, output_file: str, limit: int = 20):
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:

        for i, doc in enumerate(docs[:limit]):
            f.write("=" * 80 + "\n")
            f.write(f"Document ID: {i}\n")
            f.write(f"Metadata: {json.dumps(doc.metadata, ensure_ascii=False)}\n")
            f.write("-" * 80 + "\n")

            # 每个 Document 只预览前 2000 个字符
            # 防止单条内容太长，不方便看
            f.write(doc.page_content[:2000])
            f.write("\n\n")


# 扫描 input_dir 目录下的所有文件
# 支持的文件会解析
# 不支持的文件会跳过
# 解析失败的文件会记录错误原因，但不会中断整个程序
def scan_folder(input_dir: str):
    input_path = Path(input_dir)

    # 如果输入目录不存在，直接报错
    if not input_path.exists():
        raise FileNotFoundError(f"输入目录不存在: {input_dir}")

    all_docs = []

    success_files = []
    failed_files = []
    skipped_files = []

    # rglob("*") 表示递归扫描目录下所有内容
    # 包括子目录里面的文件
    for file_path in input_path.rglob("*"):

        # 如果不是文件，是目录，就跳过
        if not file_path.is_file():
            continue

        suffix = file_path.suffix.lower()

        # 不支持的文件类型跳过
        if suffix not in SUPPORTED_SUFFIXES:
            skipped_files.append(str(file_path))
            print(f"跳过不支持文件: {file_path}")
            continue

        try:
            # 根据文件后缀自动调用对应的解析方法
            docs = load_file(str(file_path))

            # 把当前文件解析出来的 Document 加入总列表
            all_docs.extend(docs)

            # 记录成功文件
            success_files.append(str(file_path))

            print(f"解析成功: {file_path}，Document 数量: {len(docs)}")

        except Exception as e:
            # 单个文件解析失败，不影响其他文件继续解析
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


# 保存解析报告
# 报告里包含：
# 成功文件数、失败文件数、跳过文件数、成功文件列表、失败原因等
def save_report(success_files, failed_files, skipped_files, output_file: str):
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


# 主函数
# 程序从这里开始执行
def main():

    # 原始文件目录
    # 你需要把 PDF、Word、Excel、txt、csv 等文件放到这里
    input_dir = "data/raw"

    # 输出目录
    output_dir = "output"

    # 完整 Document 数据输出文件
    documents_file = f"{output_dir}/documents.jsonl"

    # 预览文件
    preview_file = f"{output_dir}/preview.txt"

    # 解析报告文件
    report_file = f"{output_dir}/parse_report.json"

    # 扫描并解析文件
    docs, success_files, failed_files, skipped_files = scan_folder(input_dir)

    # 保存完整解析结果
    save_jsonl(docs, documents_file)

    # 保存预览结果
    save_preview(docs, preview_file)

    # 保存解析报告
    save_report(success_files, failed_files, skipped_files, report_file)

    print("\n========== 输出文件 ==========")
    print(f"Document JSONL: {documents_file}")
    print(f"预览文件: {preview_file}")
    print(f"解析报告: {report_file}")


# 只有直接运行这个文件时，才会执行 main()
# 例如：
# python parser.py
#
# 如果这个文件被其他 Python 文件 import，不会自动执行 main()
if __name__ == "__main__":
    main()