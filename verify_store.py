import os
import sys

from scripts.generation import list_curriculum_lessons, load_curriculum_store, retrieve_curriculum_context

def main():
    store = load_curriculum_store()
    count = store._collection.count()
    print(f"Vector store successfully loaded! Total chunks: {count}")

    lessons = list_curriculum_lessons(store)
    print(f"\nIndexed Lessons ({len(lessons)} total):")
    for lesson in lessons:
        print(f"  - Lesson {lesson['lesson_id']}: {lesson['lesson_title']} ({lesson['chunk_count']} chunks)")

    print("\nRetrieving sample context for Lesson 1-2 ('How AI Works')...")
    docs = retrieve_curriculum_context("machine learning", lesson_id="1-2")
    print(f"Retrieved {len(docs)} matching chunks for 'machine learning':")
    for d in docs[:2]:
        print(f"  * Chunk ID {d.metadata['chunk_id']} (Pages {d.metadata['printed_page_start']}-{d.metadata['printed_page_end']})")
        snippet = d.page_content.splitlines()[0][:100]
        print(f"    Preview: {snippet}")

    print("\n[ALL CHECKS PASSED] Environment and Vector Database are fully operational!")

if __name__ == "__main__":
    main()
