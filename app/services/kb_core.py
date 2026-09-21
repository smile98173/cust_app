import json
import re
import time
import gc
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import chromadb
    from chromadb.config import Settings
except Exception:  # pragma: no cover - optional runtime dependency
    chromadb = None
    Settings = None

try:
    from sentence_transformers import SentenceTransformer
except Exception:  # pragma: no cover - optional runtime dependency
    SentenceTransformer = None


DEFAULT_EMBED_MODEL = "BAAI/bge-m3"
DEFAULT_COLLECTION_NAME = "company_kb"


def clear_chroma_system_cache() -> None:
    """Release cached Chroma systems before replacing a persistent store."""
    if chromadb is None:
        return
    try:
        from chromadb.api.shared_system_client import SharedSystemClient

        systems = list(
            {
                id(system): system
                for system in getattr(
                    SharedSystemClient,
                    "_identifier_to_system",
                    {},
                ).values()
            }.values()
        )
        for system in systems:
            try:
                system.stop()
            except Exception:
                pass
        SharedSystemClient.clear_system_cache()
    except Exception:
        # Chroma versions differ here. The subsequent directory operation will
        # still surface a useful error if a handle remains open.
        pass
    gc.collect()


def normalize_text(text: str) -> str:
    if text is None:
        return ""
    text = str(text).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_preserve_lines(text: str) -> str:
    if text is None:
        return ""
    text = str(text).replace("\ufeff", "")
    text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", text)
    lines = [re.sub(r"[ \t　]+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    docs: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            docs.append(json.loads(line))
    return docs


def build_document_text(doc: Dict[str, Any]) -> str:
    question = normalize_text(doc.get("question", ""))
    answer = normalize_text(doc.get("answer", ""))
    company = normalize_text(doc.get("company", ""))
    category = normalize_text(doc.get("category", ""))
    title = normalize_text(doc.get("title", ""))
    record_type = normalize_text(doc.get("record_type", ""))
    document_type = normalize_text(doc.get("document_type", ""))
    campaign_name = normalize_text(doc.get("campaign_name", ""))
    campaign_aliases = normalize_text(doc.get("campaign_aliases", ""))
    campaign_sections = normalize_text(doc.get("campaign_sections", ""))
    service_types = normalize_text(doc.get("service_types", ""))
    speeds = normalize_text(doc.get("speeds", ""))
    contract_months = normalize_text(doc.get("contract_months", ""))
    payment_terms = normalize_text(doc.get("payment_terms", ""))
    customer_types = normalize_text(doc.get("customer_types", ""))
    valid_period = normalize_text(doc.get("valid_period", ""))
    product_catalog = normalize_text(doc.get("product_catalog", ""))
    product_name = normalize_text(doc.get("product_name", ""))
    product_aliases = normalize_text(doc.get("product_aliases", ""))
    product_parent = normalize_text(doc.get("product_parent", ""))

    return (
        f"問題：{question}\n"
        f"回答：{answer}\n"
        f"標題：{title}\n"
        f"公司：{company}\n"
        f"分類：{category}\n"
        f"紀錄類型：{record_type}\n"
        f"文件類型：{document_type}\n"
        f"方案名稱：{campaign_name}\n"
        f"方案別名：{campaign_aliases}\n"
        f"方案欄位：{campaign_sections}\n"
        f"服務類型：{service_types}\n"
        f"速率：{speeds}\n"
        f"綁約月數：{contract_months}\n"
        f"繳別：{payment_terms}\n"
        f"適用對象：{customer_types}\n"
        f"活動期間：{valid_period}\n"
        f"加值服務目錄：{product_catalog}\n"
        f"產品名稱：{product_name}\n"
        f"產品別名：{product_aliases}\n"
        f"上層服務：{product_parent}"
    )


def format_retrieved_docs(docs: List[Dict[str, Any]]) -> str:
    if not docs:
        return "無相關知識"

    blocks = []
    for i, doc in enumerate(docs, start=1):
        blocks.append(
            "\n".join([
                f"[知識 {i}]",
                f"id: {doc.get('id')}",
                f"company: {doc.get('company')}",
                f"category: {doc.get('category')}",
                f"question: {doc.get('question')}",
                f"answer: {doc.get('answer')}",
                f"distance: {doc.get('_distance')}",
            ])
        )
    return "\n\n".join(blocks)


class BGEEmbeddingFunction:
    """
    給 Chroma 用的 embedding function
    需相容:
    - __call__(input)
    - name()
    - embed_query(input=...)
    - embed_documents(input=...)
    """

    def __init__(self, model_name: str = DEFAULT_EMBED_MODEL, device: Optional[str] = None):
        if SentenceTransformer is None:
            raise RuntimeError(
                "尚未安裝 sentence-transformers，請先安裝 requirements.txt 的本地 RAG 依賴。"
            )
        self.model_name = model_name
        self.device = device
        self.model = SentenceTransformer(model_name, device=device)

    def _encode(self, texts: List[str]) -> List[List[float]]:
        t0 = time.perf_counter()
        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        t1 = time.perf_counter()
        print(f"[KB] model.encode count={len(texts)} time={t1 - t0:.3f}s")
        return embeddings.tolist()

    def __call__(self, input):
        if isinstance(input, str):
            input = [input]
        return self._encode(list(input))

    def embed_documents(self, input):
        if isinstance(input, str):
            input = [input]
        return self._encode(list(input))

    def embed_query(self, input):
        if isinstance(input, str):
            input = [input]
        return self._encode(list(input))

    def name(self) -> str:
        return f"bge_embedding::{self.model_name}"


class KBSearcher:
    def __init__(
        self,
        persist_dir: str,
        collection_name: str = DEFAULT_COLLECTION_NAME,
        model_name: str = DEFAULT_EMBED_MODEL,
        device: Optional[str] = None,
    ):
        self.persist_dir = persist_dir
        self.collection_name = collection_name
        self.model_name = model_name
        self.device = device

        if chromadb is None or Settings is None:
            raise RuntimeError("尚未安裝 chromadb，請先安裝 requirements.txt 的本地 RAG 依賴。")

        t0 = time.perf_counter()
        self.embedding_fn = BGEEmbeddingFunction(model_name=model_name, device=device)
        print(f"[KB] embedding_fn init: {time.perf_counter() - t0:.3f}s")

        self.client = chromadb.PersistentClient(
            path=persist_dir,
            settings=Settings(anonymized_telemetry=False)
        )

        self.collection = None

    def create_or_load_collection(self):
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=self.embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )
        return self.collection

    @staticmethod
    def _is_collection_not_found_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return (
            exc.__class__.__name__ == "NotFoundError"
            or "does not exist" in message
            or "not found" in message
        )

    def delete_collection(self) -> bool:
        """Delete and verify the collection instead of hiding storage errors."""
        self.collection = None
        try:
            self.client.delete_collection(self.collection_name)
        except Exception as exc:
            if self._is_collection_not_found_error(exc):
                return False
            raise RuntimeError(
                f"無法刪除 Chroma collection {self.collection_name!r}: {exc}"
            ) from exc

        try:
            self.client.get_collection(self.collection_name)
        except Exception as exc:
            if self._is_collection_not_found_error(exc):
                return True
            raise RuntimeError(
                f"無法確認 Chroma collection {self.collection_name!r} 是否已刪除: {exc}"
            ) from exc

        raise RuntimeError(
            f"Chroma collection {self.collection_name!r} 回報刪除成功，但仍可被讀取。"
        )

    def close(self) -> None:
        """Release Chroma's SQLite/HNSW handles held by this searcher."""
        self.collection = None
        client = getattr(self, "client", None)
        self.client = None
        if client is not None:
            close = getattr(client, "close", None)
            if callable(close):
                close()
        gc.collect()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def build_from_jsonl(
        self,
        jsonl_path: str,
        reset_collection: bool = True,
        batch_size: int = 100,
    ):
        path = Path(jsonl_path)
        if not path.exists():
            raise FileNotFoundError(f"找不到知識庫檔案: {jsonl_path}")

        docs = load_jsonl(path)
        if not docs:
            raise ValueError("知識庫檔案是空的")

        if reset_collection:
            self.delete_collection()

        collection = self.create_or_load_collection()

        ids: List[str] = []
        documents: List[str] = []
        metadatas: List[Dict[str, Any]] = []

        for doc in docs:
            doc_id = str(doc.get("id"))
            if not doc_id:
                continue

            text = build_document_text(doc)

            metadata = {
                "id": doc.get("id", ""),
                "question": doc.get("question", ""),
                "answer": doc.get("answer", ""),
                "company": doc.get("company", ""),
                "category": doc.get("category", ""),
            }

            ids.append(doc_id)
            documents.append(text)
            metadatas.append(metadata)

        total = len(ids)
        if total == 0:
            raise ValueError("沒有有效文件可建立索引")

        for start in range(0, total, batch_size):
            end = start + batch_size
            collection.add(
                ids=ids[start:end],
                documents=documents[start:end],
                metadatas=metadatas[start:end],
            )

        self.collection = collection
        return total

    def upsert_records(
        self,
        records: List[Dict[str, Any]],
        batch_size: int = 100,
        delete_document_id: Optional[str] = None,
    ) -> int:
        collection = self.create_or_load_collection()

        if delete_document_id:
            self.delete_by_document_id(delete_document_id)

        ids: List[str] = []
        documents: List[str] = []
        metadatas: List[Dict[str, Any]] = []

        for record in records:
            doc_id = str(record.get("id") or "")
            content = normalize_preserve_lines(record.get("answer") or record.get("content") or "")
            embedding_content = normalize_text(content)
            if not doc_id or not content:
                continue

            metadata = {
                "id": doc_id,
                "document_id": str(record.get("document_id", "")),
                "chunk_index": int(record.get("chunk_index", 0) or 0),
                "question": str(record.get("question", "")),
                "answer": content,
                "company": str(record.get("company", "")),
                "knowledge_base": str(record.get("knowledge_base") or record.get("company") or ""),
                "category": str(record.get("category", "")),
                "title": str(record.get("title", "")),
                "source": str(record.get("source", "")),
                "page_no": str(record.get("page_no", "")),
                "section": str(record.get("section", "")),
                "record_type": str(record.get("record_type", "")),
                "document_type": str(record.get("document_type", "")),
                "campaign_name": str(record.get("campaign_name", "")),
                "campaign_aliases": str(record.get("campaign_aliases", "")),
                "campaign_sections": str(record.get("campaign_sections", "")),
                "service_types": str(record.get("service_types", "")),
                "speeds": str(record.get("speeds", "")),
                "contract_months": str(record.get("contract_months", "")),
                "payment_terms": str(record.get("payment_terms", "")),
                "customer_types": str(record.get("customer_types", "")),
                "valid_period": str(record.get("valid_period", "")),
                "product_catalog": str(record.get("product_catalog", "")),
                "product_name": str(record.get("product_name", "")),
                "product_aliases": str(record.get("product_aliases", "")),
                "product_parent": str(record.get("product_parent", "")),
            }

            ids.append(doc_id)
            documents.append(build_document_text({
                "question": metadata["question"],
                "answer": embedding_content,
                "company": metadata["knowledge_base"] or metadata["company"],
                "category": metadata["category"],
                "title": metadata["title"],
                "record_type": metadata["record_type"],
                "document_type": metadata["document_type"],
                "campaign_name": metadata["campaign_name"],
                "campaign_aliases": metadata["campaign_aliases"],
                "campaign_sections": metadata["campaign_sections"],
                "service_types": metadata["service_types"],
                "speeds": metadata["speeds"],
                "contract_months": metadata["contract_months"],
                "payment_terms": metadata["payment_terms"],
                "customer_types": metadata["customer_types"],
                "valid_period": metadata["valid_period"],
                "product_catalog": metadata["product_catalog"],
                "product_name": metadata["product_name"],
                "product_aliases": metadata["product_aliases"],
                "product_parent": metadata["product_parent"],
            }))
            metadatas.append(metadata)

        for start in range(0, len(ids), batch_size):
            end = start + batch_size
            collection.upsert(
                ids=ids[start:end],
                documents=documents[start:end],
                metadatas=metadatas[start:end],
            )

        self.collection = collection
        return len(ids)

    def delete_by_document_id(self, document_id: str) -> None:
        if self.collection is None:
            self.create_or_load_collection()
        try:
            self.collection.delete(where={"document_id": str(document_id)})
        except Exception as exc:
            raise RuntimeError(f"無法刪除文件 {document_id} 的 Chroma 向量: {exc}") from exc

    def _build_where_filter(
        self,
        company: Optional[str] = None,
        category: Optional[str] = None,
        knowledge_base: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        filters = []

        if knowledge_base:
            filters.append({"knowledge_base": knowledge_base})

        if company:
            filters.append({"company": company})

        if category:
            filters.append({"category": category})

        if not filters:
            return None

        if len(filters) == 1:
            return filters[0]

        return {"$and": filters}

    def search(
        self,
        query: str,
        top_k: int = 5,
        company: Optional[str] = None,
        category: Optional[str] = None,
        knowledge_base: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if self.collection is None:
            t0 = time.perf_counter()
            self.create_or_load_collection()
            print(f"[KB] create_or_load_collection: {time.perf_counter() - t0:.3f}s")

        query = normalize_text(query)
        if not query:
            return []

        where_filter = self._build_where_filter(
            company=company,
            category=category,
            knowledge_base=knowledge_base,
        )

        t1 = time.perf_counter()
        result = self.collection.query(
            query_texts=[query],
            n_results=top_k,
            where=where_filter,
        )
        t2 = time.perf_counter()

        print(f"[KB] query='{query}' where={where_filter}")
        print(f"[KB] collection.query total: {t2 - t1:.3f}s")

        ids = result.get("ids", [[]])[0]
        distances = result.get("distances", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        documents = result.get("documents", [[]])[0]

        output: List[Dict[str, Any]] = []

        for doc_id, distance, metadata, document_text in zip(ids, distances, metadatas, documents):
            item = {
                "id": metadata.get("id", doc_id),
                "document_id": metadata.get("document_id", ""),
                "chunk_index": metadata.get("chunk_index", 0),
                "question": metadata.get("question") or metadata.get("title") or metadata.get("source") or "",
                "answer": metadata.get("answer") or document_text or "",
                "company": metadata.get("knowledge_base") or metadata.get("company", ""),
                "category": metadata.get("category", ""),
                "source": metadata.get("source", ""),
                "title": metadata.get("title", ""),
                "page_no": metadata.get("page_no", ""),
                "section": metadata.get("section", ""),
                "record_type": metadata.get("record_type", ""),
                "document_type": metadata.get("document_type", ""),
                "campaign_name": metadata.get("campaign_name", ""),
                "campaign_aliases": metadata.get("campaign_aliases", ""),
                "campaign_sections": metadata.get("campaign_sections", ""),
                "service_types": metadata.get("service_types", ""),
                "speeds": metadata.get("speeds", ""),
                "contract_months": metadata.get("contract_months", ""),
                "payment_terms": metadata.get("payment_terms", ""),
                "customer_types": metadata.get("customer_types", ""),
                "valid_period": metadata.get("valid_period", ""),
                "product_catalog": metadata.get("product_catalog", ""),
                "product_name": metadata.get("product_name", ""),
                "product_aliases": metadata.get("product_aliases", ""),
                "product_parent": metadata.get("product_parent", ""),
                "_distance": round(float(distance), 6),
                "_score": round(1 - float(distance), 6),
            }
            output.append(item)

        return output


def build_kb_index(
    jsonl_path: str,
    persist_dir: str,
    collection_name: str = DEFAULT_COLLECTION_NAME,
    model_name: str = DEFAULT_EMBED_MODEL,
    device: Optional[str] = None,
    reset_collection: bool = True,
):
    searcher = KBSearcher(
        persist_dir=persist_dir,
        collection_name=collection_name,
        model_name=model_name,
        device=device,
    )
    total = searcher.build_from_jsonl(
        jsonl_path=jsonl_path,
        reset_collection=reset_collection,
    )
    print(f"[OK] 建立完成，共寫入 {total} 筆文件")
    print(f"[OK] persist_dir: {persist_dir}")
    print(f"[OK] collection: {collection_name}")


def load_kb_searcher(
    persist_dir: str,
    collection_name: str = DEFAULT_COLLECTION_NAME,
    model_name: str = DEFAULT_EMBED_MODEL,
    device: Optional[str] = None,
) -> KBSearcher:
    searcher = KBSearcher(
        persist_dir=persist_dir,
        collection_name=collection_name,
        model_name=model_name,
        device=device,
    )
    searcher.create_or_load_collection()
    return searcher
