"""
Curriculum Ingestion Module

Implements document parsing, table-aware text extraction, semantic chunking,
embedding generation, and vector store retrieval using PyMuPDF and LangChain.
"""

from collections import defaultdict
import json
from pathlib import Path
import re
from typing import Any

import chromadb
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
import pymupdf


def parse_toc(doc: pymupdf.Document) -> tuple[dict[int, str], dict[str, str]]:
    """
    Parses table of contents from the PDF document.

    Returns:
        chapters: dict mapping chapter_id (int) -> chapter_title (str)
        lessons: dict mapping lesson_id (str, e.g. '1-1') -> lesson_title (str)
    """
    contents_page = None
    for page in doc:
        lines = [line.strip() for line in page.get_text().splitlines() if line.strip()]
        if lines and lines[0] == "Contents":
            contents_page = page
            break

    if contents_page is None:
        raise ValueError("Contents page not found in document.")

    lines = [line.strip() for line in contents_page.get_text().splitlines() if line.strip()]
    tokens = lines[1:]  # skip 'Contents' header

    chapters: dict[int, str] = {}
    lessons: dict[str, str] = {}

    idx = 0
    while idx < len(tokens):
        tok = tokens[idx]
        if re.match(r"^\d+$", tok) and idx + 2 < len(tokens):
            chap_num = int(tok)
            title = tokens[idx + 1]
            chapters[chap_num] = title
            idx += 3
        elif re.match(r"^\d+-\d+$", tok) and idx + 2 < len(tokens):
            lesson_id = tok
            title = tokens[idx + 1]
            lessons[lesson_id] = title
            idx += 3
        else:
            idx += 1

    return chapters, lessons


def is_inside_table(block: tuple, table_bboxes: list[tuple[float, float, float, float]]) -> bool:
    """
    Determines whether a text block is located inside any detected table bounding box.
    Uses the center coordinate of the text block to prevent false positives.
    """
    bx_mid = (block[0] + block[2]) / 2
    by_mid = (block[1] + block[3]) / 2
    for tb in table_bboxes:
        if (tb[0] - 5 <= bx_mid <= tb[2] + 5) and (tb[1] - 5 <= by_mid <= tb[3] + 5):
            return True
    return False


def is_markdown_table(text: str) -> bool:
    """Checks if a given text block represents a Markdown table."""
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    return (
        len(lines) >= 2
        and lines[0].startswith("|")
        and lines[0].endswith("|")
        and lines[1].startswith("|")
        and "---" in lines[1]
    )


def split_table_by_rows(table_md: str, max_size: int = 800) -> list[str]:
    """
    Splits a large Markdown table by rows when it exceeds max_size,
    repeating the header and separator rows in every resulting sub-table chunk.
    """
    lines = [l for l in table_md.strip().splitlines() if l.strip()]
    if len(lines) < 3:
        return [table_md]

    header = lines[0]
    separator = lines[1]
    header_block = f"{header}\n{separator}"

    sub_tables: list[str] = []
    current_rows: list[str] = []
    current_len = len(header_block)

    for row in lines[2:]:
        row_len = len(row) + 1
        if current_rows and (current_len + row_len > max_size):
            sub_tables.append(f"{header_block}\n" + "\n".join(current_rows))
            current_rows = [row]
            current_len = len(header_block) + row_len
        else:
            current_rows.append(row)
            current_len += row_len

    if current_rows:
        sub_tables.append(f"{header_block}\n" + "\n".join(current_rows))

    return sub_tables


def extract_pages(pdf_path: str | Path) -> list[Document]:
    """
    Extracts lesson pages from PDF, detecting tables and rendering them as Markdown,
    removing headers/footers, preventing duplicate table text, and isolating side notes.

    Each page is returned as a LangChain Document with rich metadata:
    - source: PDF file name
    - pdf_page: 1-based page number in PDF
    - printed_page: page number printed in footer
    - chapter_id: chapter number (int)
    - chapter_title: title of the chapter
    - lesson_id: lesson identifier (e.g. '1-1')
    - lesson_title: title of the lesson
    - table_count: number of detected tables on the page
    - has_tables: boolean flag indicating presence of tables
    """
    path = Path(pdf_path)
    doc = pymupdf.open(str(path))
    chapters, lessons = parse_toc(doc)

    pages: list[Document] = []

    for pno in range(len(doc)):
        page = doc[pno]
        blocks = page.get_text("blocks")

        # Collect header and footer text
        header_text = ""
        footer_text = ""
        for b in blocks:
            # b: (x0, y0, x1, y1, text, block_no, block_type)
            if b[1] < 40:
                header_text += b[4].strip() + " "
            if b[1] > 800:
                footer_text += b[4].strip() + " "

        # Match lesson running header (e.g. '1-1 — Lesson Title')
        m = re.search(r"(\d+-\d+)\s*[—–-]\s*(.*)", header_text)
        if not m:
            continue  # Front matter, table of contents, or back matter

        lesson_id = m.group(1)
        lesson_title = lessons.get(lesson_id, m.group(2).strip())
        chap_id = int(lesson_id.split("-")[0])
        chap_title = chapters.get(chap_id, "")

        # Extract printed page number from footer
        first_footer_line = footer_text.strip().splitlines()[0].strip() if footer_text.strip() else ""
        p_match = re.match(r"^(\d+)", first_footer_line)
        printed_page = int(p_match.group(1)) if p_match else pno + 1

        # Detect tables on page
        tab_finder = page.find_tables()
        table_bboxes = [t.bbox for t in tab_finder.tables]

        # Collect main elements (non-table text blocks and markdown tables)
        main_elements = []

        # 1. Main text blocks (exclude blocks inside table bboxes to prevent duplicates)
        for b in blocks:
            if b[6] == 0 and 40 <= b[1] <= 800 and b[0] <= 420 and b[4].strip():
                if not is_inside_table(b, table_bboxes):
                    main_elements.append({
                        "type": "text",
                        "y0": b[1],
                        "x0": b[0],
                        "text": b[4].strip(),
                    })

        # 2. Detected tables converted to Markdown
        for t in tab_finder.tables:
            table_md = t.to_markdown().strip()
            if table_md:
                main_elements.append({
                    "type": "table",
                    "y0": t.bbox[1],
                    "x0": t.bbox[0],
                    "text": table_md,
                })

        # Sort main elements in reading order: (round(y0 / 5), x0)
        main_elements.sort(key=lambda e: (round(e["y0"] / 5), e["x0"]))
        main_text = "\n\n".join(e["text"] for e in main_elements)

        # 3. Side column blocks (x0 > 420)
        side_blocks = [
            b for b in blocks
            if b[6] == 0 and 40 <= b[1] <= 800 and b[0] > 420 and b[4].strip()
        ]
        side_blocks.sort(key=lambda b: (round(b[1] / 5), b[0]))
        side_text = "\n\n".join(b[4].strip() for b in side_blocks)

        full_text = main_text
        if side_text.strip():
            full_text += "\n\n[Side note]\n" + side_text

        pages.append(
            Document(
                page_content=full_text,
                metadata={
                    "source": path.name,
                    "pdf_page": pno + 1,
                    "printed_page": printed_page,
                    "chapter_id": chap_id,
                    "chapter_title": chap_title,
                    "lesson_id": lesson_id,
                    "lesson_title": lesson_title,
                    "table_count": len(tab_finder.tables),
                    "has_tables": len(tab_finder.tables) > 0,
                },
            )
        )

    return pages


def chunk_pages(
    pages: list[Document],
    chunk_size: int = 800,
    chunk_overlap: int = 120,
) -> list[Document]:
    """
    Chunks curriculum pages grouped by lesson so chunks never cross lesson boundaries.
    Preserves tables intact whenever possible, keeps tables with explanatory text when fitting,
    splits oversized tables by rows while repeating headers, and assigns content_type metadata.
    """
    lesson_groups: dict[str, list[Document]] = defaultdict(list)
    for p in pages:
        lesson_groups[p.metadata["lesson_id"]].append(p)

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        add_start_index=True,
    )
    all_chunks: list[Document] = []

    for lid, lpages in lesson_groups.items():
        # Deconstruct lesson pages into sequential paragraph/table items
        items = []
        for p in lpages:
            paragraphs = [para.strip() for para in p.page_content.split("\n\n") if para.strip()]
            for para in paragraphs:
                items.append({
                    "content": para,
                    "is_table": is_markdown_table(para),
                    "pdf_page": p.metadata["pdf_page"],
                    "printed_page": p.metadata["printed_page"],
                })

        accumulated_text: list[dict[str, Any]] = []
        acc_len = 0

        def flush_acc() -> list[dict[str, Any]]:
            nonlocal accumulated_text, acc_len
            if not accumulated_text:
                return []

            combined = "\n\n".join(x["content"] for x in accumulated_text)
            p_start = accumulated_text[0]["pdf_page"]
            p_end = accumulated_text[-1]["pdf_page"]
            pr_start = accumulated_text[0]["printed_page"]
            pr_end = accumulated_text[-1]["printed_page"]

            res = []
            if len(combined) <= chunk_size:
                res.append({
                    "content": combined,
                    "content_type": "text",
                    "pdf_start": p_start,
                    "pdf_end": p_end,
                    "pr_start": pr_start,
                    "pr_end": pr_end,
                })
            else:
                sub_chunks = text_splitter.split_text(combined)
                for sc in sub_chunks:
                    res.append({
                        "content": sc,
                        "content_type": "text",
                        "pdf_start": p_start,
                        "pdf_end": p_end,
                        "pr_start": pr_start,
                        "pr_end": pr_end,
                    })
            accumulated_text = []
            acc_len = 0
            return res

        lesson_raw_chunks: list[dict[str, Any]] = []

        for it in items:
            if it["is_table"]:
                t_content = it["content"]
                if len(t_content) > chunk_size:
                    # Oversized table: flush prior text and split table by rows
                    lesson_raw_chunks.extend(flush_acc())
                    sub_tables = split_table_by_rows(t_content, max_size=chunk_size)
                    for st in sub_tables:
                        lesson_raw_chunks.append({
                            "content": st,
                            "content_type": "table",
                            "pdf_start": it["pdf_page"],
                            "pdf_end": it["pdf_page"],
                            "pr_start": it["printed_page"],
                            "pr_end": it["printed_page"],
                        })
                else:
                    # Small table: can it be combined with preceding explanatory text?
                    if accumulated_text and (acc_len + len(t_content) + 2 <= chunk_size):
                        accumulated_text.append(it)
                        combined = "\n\n".join(x["content"] for x in accumulated_text)
                        p_start = accumulated_text[0]["pdf_page"]
                        p_end = accumulated_text[-1]["pdf_page"]
                        pr_start = accumulated_text[0]["printed_page"]
                        pr_end = accumulated_text[-1]["printed_page"]
                        lesson_raw_chunks.append({
                            "content": combined,
                            "content_type": "mixed",
                            "pdf_start": p_start,
                            "pdf_end": p_end,
                            "pr_start": pr_start,
                            "pr_end": pr_end,
                        })
                        accumulated_text = []
                        acc_len = 0
                    else:
                        lesson_raw_chunks.extend(flush_acc())
                        lesson_raw_chunks.append({
                            "content": t_content,
                            "content_type": "table",
                            "pdf_start": it["pdf_page"],
                            "pdf_end": it["pdf_page"],
                            "pr_start": it["printed_page"],
                            "pr_end": it["printed_page"],
                        })
            else:
                block_len = len(it["content"])
                if acc_len + block_len + 2 > chunk_size and accumulated_text:
                    lesson_raw_chunks.extend(flush_acc())
                accumulated_text.append(it)
                acc_len += block_len + 2

        lesson_raw_chunks.extend(flush_acc())

        for idx, rc in enumerate(lesson_raw_chunks, start=1):
            all_chunks.append(
                Document(
                    page_content=rc["content"],
                    metadata={
                        "source": lpages[0].metadata["source"],
                        "chapter_id": lpages[0].metadata["chapter_id"],
                        "chapter_title": lpages[0].metadata["chapter_title"],
                        "lesson_id": lid,
                        "lesson_title": lpages[0].metadata["lesson_title"],
                        "chunk_id": f"{lid}-{idx:03d}",
                        "content_type": rc["content_type"],
                        "pdf_page_start": rc["pdf_start"],
                        "pdf_page_end": rc["pdf_end"],
                        "printed_page_start": rc["pr_start"],
                        "printed_page_end": rc["pr_end"],
                    },
                )
            )

    return all_chunks


def save_chunks_jsonl(chunks: list[Document], out_path: str | Path) -> None:
    """Saves chunks and their metadata into a JSON Lines file."""
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for chunk in chunks:
            row = {
                "page_content": chunk.page_content,
                "metadata": chunk.metadata,
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def get_embeddings(
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
) -> Any:
    """Returns a local HuggingFace embeddings model instance."""
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(model_name=model_name)


def build_vectorstore(
    chunks: list[Document],
    embeddings: Any,
    persist_dir: str | Path,
    collection_name: str = "curriculum",
) -> Chroma:
    """
    Creates a new Chroma collection and persists the supplied chunks.
    Existing collections are preserved and cause an explicit error.
    """
    path = Path(persist_dir)
    path.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=str(path))
    if collection_name in {collection.name for collection in client.list_collections()}:
        raise FileExistsError(
            f"Collection '{collection_name}' already exists in {path}; refusing to overwrite it"
        )

    store = Chroma(
        client=client,
        collection_name=collection_name,
        embedding_function=embeddings,
    )
    ids = [c.metadata["chunk_id"] for c in chunks]
    store.add_documents(documents=chunks, ids=ids)
    return store


def load_vectorstore(
    embeddings: Any,
    persist_dir: str | Path,
    collection_name: str = "curriculum",
) -> Chroma:
    """Loads an existing Chroma vector store from disk."""
    path = Path(persist_dir)
    if not path.is_dir():
        raise FileNotFoundError(f"Vector store directory not found: {path}")
    client = chromadb.PersistentClient(path=str(path))
    if collection_name not in {collection.name for collection in client.list_collections()}:
        raise FileNotFoundError(
            f"Collection '{collection_name}' not found in vector store {path}"
        )
    return Chroma(
        client=client,
        collection_name=collection_name,
        embedding_function=embeddings,
    )


def retrieve(
    store: Chroma,
    query: str,
    k: int = 4,
    chapter_id: int | None = None,
    lesson_id: str | None = None,
) -> list[Document]:
    """
    Retrieves the top-k most similar chunks for a query with optional metadata filtering.
    Filters are combined using Chroma's $and operator if multiple criteria are specified.
    """
    filters = []
    if chapter_id is not None:
        filters.append({"chapter_id": {"$eq": int(chapter_id)}})
    if lesson_id is not None:
        filters.append({"lesson_id": {"$eq": str(lesson_id)}})

    filter_dict = None
    if len(filters) == 1:
        key = "chapter_id" if chapter_id is not None else "lesson_id"
        val = int(chapter_id) if chapter_id is not None else str(lesson_id)
        filter_dict = {key: val}
    elif len(filters) > 1:
        filter_dict = {"$and": filters}

    return store.similarity_search(query=query, k=k, filter=filter_dict)
