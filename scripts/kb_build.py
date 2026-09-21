import csv
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple


# 來源檔名 -> category 映射
CATEGORY_MAP = {
    "帳務": "billing",
    "加值服務": "value_added_service",
    "機上盒": "set_top_box",
    "網路寬頻": "network_support",
}

REQUIRED_COLUMNS = {"question", "answer", "company"}


def normalize_question(text: str) -> str:
    """問題欄位：整理成單行，方便 embedding 查詢"""
    if text is None:
        return ""

    text = str(text).strip()
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_single_line(text: str) -> str:
    """單行欄位清洗，例如 company"""
    if text is None:
        return ""

    text = str(text).strip()
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_answer(text: str) -> str:
    """
    答案欄位：保留換行。

    注意：
    不可以用 re.sub(r"\\s+", " ", text)
    因為 \\s 會包含換行，會把原本整理好的條列格式壓成一整行。
    """
    if text is None:
        return ""

    text = str(text).strip()

    # 統一換行格式
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 每一行去除頭尾空白，但保留換行
    lines = [line.strip() for line in text.split("\n")]

    # 壓掉過多空白行，最多保留一個空白行
    cleaned_lines = []
    blank_count = 0

    for line in lines:
        if not line:
            blank_count += 1
            if blank_count <= 1:
                cleaned_lines.append("")
        else:
            blank_count = 0
            # 只壓縮同一行內連續空白，不動換行
            line = re.sub(r"[ \t]+", " ", line)
            cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()


def read_csv_rows(csv_path: Path) -> List[Dict[str, str]]:
    """讀單一 CSV，回傳標準化後的 rows"""
    rows: List[Dict[str, str]] = []

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        if reader.fieldnames is None:
            raise ValueError(f"{csv_path.name} 沒有表頭")

        fieldnames = {name.strip() for name in reader.fieldnames if name}
        missing = REQUIRED_COLUMNS - fieldnames
        if missing:
            raise ValueError(
                f"{csv_path.name} 缺少必要欄位: {', '.join(sorted(missing))}"
            )

        for row in reader:
            question = normalize_question(row.get("question", ""))
            answer = normalize_answer(row.get("answer", ""))
            company = normalize_single_line(row.get("company", ""))

            if not question or not answer:
                continue

            if not company:
                company = "共用"

            rows.append(
                {
                    "question": question,
                    "answer": answer,
                    "company": company,
                }
            )

    return rows


def deduplicate_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """同 category + question + answer + company 完全重複則去除"""
    seen = set()
    deduped: List[Dict[str, str]] = []

    for row in rows:
        key = (
            row["category"],
            row["question"],
            row["answer"],
            row["company"],
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    return deduped


def assign_ids(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """依 category 產生穩定 id"""
    counters: Dict[str, int] = {}
    output: List[Dict[str, str]] = []

    for row in rows:
        category = row["category"]
        prefix = category
        counters[prefix] = counters.get(prefix, 0) + 1
        row_id = f"{prefix}_{counters[prefix]:04d}"

        new_row = {
            "id": row_id,
            "question": row["question"],
            "answer": row["answer"],
            "company": row["company"],
            "category": row["category"],
        }
        output.append(new_row)

    return output


def load_source_folder(source_dir: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    """
    從資料夾讀取四類 CSV
    回傳:
      - 整理後資料
      - 實際讀到的檔名列表
    """
    all_rows: List[Dict[str, str]] = []
    loaded_files: List[str] = []

    for display_name, category in CATEGORY_MAP.items():
        csv_path = source_dir / f"{display_name}.csv"
        if not csv_path.exists():
            print(f"[WARN] 找不到檔案: {csv_path.name}")
            continue

        rows = read_csv_rows(csv_path)
        for row in rows:
            row["category"] = category

        all_rows.extend(rows)
        loaded_files.append(csv_path.name)

    all_rows = deduplicate_rows(all_rows)
    all_rows = assign_ids(all_rows)
    return all_rows, loaded_files


def write_jsonl(rows: List[Dict[str, str]], output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_json(rows: List[Dict[str, str]], output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def write_csv(rows: List[Dict[str, str]], output_path: Path) -> None:
    fieldnames = ["id", "question", "answer", "company", "category"]
    with output_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows: List[Dict[str, str]], loaded_files: List[str]) -> None:
    print("=== KB Build Summary ===")
    print(f"讀取檔案數: {len(loaded_files)}")
    for name in loaded_files:
        print(f" - {name}")

    print(f"總筆數: {len(rows)}")

    category_count: Dict[str, int] = {}
    for row in rows:
        category = row["category"]
        category_count[category] = category_count.get(category, 0) + 1

    print("分類統計:")
    for category, count in sorted(category_count.items()):
        print(f" - {category}: {count}")


def main():
    """
    用法:
      python kb_build.py ./knowledge_source ./kb_output

    若不提供參數:
      source_dir 預設為 ./data/knowledge_source
      output_dir 預設為 ./data/kb_output
    """
    base_dir = Path(__file__).resolve().parent.parent
    data_dir = base_dir / "data"

    source_dir = (
        Path(sys.argv[1]).resolve()
        if len(sys.argv) > 1
        else (data_dir / "knowledge_source").resolve()
    )
    output_dir = (
        Path(sys.argv[2]).resolve()
        if len(sys.argv) > 2
        else (data_dir / "kb_output").resolve()
    )

    if not source_dir.exists() or not source_dir.is_dir():
        raise FileNotFoundError(f"找不到來源資料夾: {source_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)

    rows, loaded_files = load_source_folder(source_dir)

    if not rows:
        raise ValueError("沒有讀到任何有效資料，請檢查來源 CSV 與欄位名稱")

    jsonl_path = output_dir / "canonical_kb.jsonl"
    json_path = output_dir / "canonical_kb.json"
    csv_path = output_dir / "canonical_kb.csv"

    write_jsonl(rows, jsonl_path)
    write_json(rows, json_path)
    write_csv(rows, csv_path)

    print_summary(rows, loaded_files)
    print()
    print("輸出完成:")
    print(f" - {jsonl_path}")
    print(f" - {json_path}")
    print(f" - {csv_path}")


if __name__ == "__main__":
    main()