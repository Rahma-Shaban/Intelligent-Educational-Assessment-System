"""
Run curriculum ingestion pipeline to extract, chunk, and index the textbook PDF.
"""
from pathlib import Path
from scripts.config import RAW_DATA_DIR, PROCESSED_DATA_DIR, VECTOR_DB_PATH
from scripts.ingestion import (
    extract_pages,
    chunk_pages,
    save_chunks_jsonl,
    get_embeddings,
    build_vectorstore,
    retrieve,
)


def main():
    pdf_path = RAW_DATA_DIR / "Programming-ArtificialIntelligence-En-EB-part1.pdf"
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found at {pdf_path}")

    print(f"Ingesting PDF: {pdf_path.name}...")
    pages = extract_pages(pdf_path)
    print(f"Extracted {len(pages)} lesson pages.")

    chunks = chunk_pages(pages)
    print(f"Generated {len(chunks)} semantic chunks.")

    chunks_file = PROCESSED_DATA_DIR / "chunks.jsonl"
    save_chunks_jsonl(chunks, chunks_file)
    print(f"Saved chunks to {chunks_file}")

    print(f"Generating embeddings and building vector store at {VECTOR_DB_PATH}...")
    embeddings = get_embeddings()
    store = build_vectorstore(chunks, embeddings, VECTOR_DB_PATH, collection_name="curriculum")
    count = store._collection.count()
    print(f"[SUCCESS] Vector store built with {count} chunks in collection 'curriculum'!")

    # Smoke test retrieval
    print("\nRunning smoke test retrieval...")
    query = "What is Moore's Law?"
    results = retrieve(store, query=query, k=2)
    for i, res in enumerate(results, 1):
        m = res.metadata
        print(f"  Result #{i}: Chunk {m.get('chunk_id')} (Lesson {m.get('lesson_id')}, pages {m.get('printed_page_start')}-{m.get('printed_page_end')})")
        clean_preview = res.page_content[:120].encode("ascii", errors="replace").decode("ascii")
        print(f"    Preview: {clean_preview}...\n")

    print("[DONE] Ingestion and retrieval verified successfully.")


if __name__ == "__main__":
    main()
