from app.services.kb_core import build_kb_index

if __name__ == "__main__":
    build_kb_index(
        jsonl_path="data/kb_output/canonical_kb.jsonl",
        persist_dir="data/chroma_db"
    )
