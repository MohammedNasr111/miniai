"""Manual test for Stage 4's memory layer. No LLM involved - this
proves the storage + permission-gate plumbing works before it's ever
exposed to the model.

Expect: the three save_memory calls each prompt once (CONFIRM). The
search/list calls should NOT prompt at all.
"""

from tools.memory.memory_tools import list_memories, save_memory, search_memory


def main() -> None:
    from memory.database.db import DB_PATH
    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"Reset: removed existing test database at {DB_PATH}\n")

    print("=== save_memory x3 (each SHOULD prompt - answer yes) ===")
    print(save_memory("James teaches Grade 4 ICT and mathematics.", "fact"))
    print(save_memory("Prefers concise responses without unnecessary preamble.", "preference"))
    print(save_memory("MiniAI Stage 4 uses SQLite for structured long-term memory.", "project"))

    print("\n=== list_memories, all categories (should NOT prompt) ===")
    for m in list_memories():
        print(f"  #{m['id']} [{m['category']}] {m['content']}")

    print("\n=== list_memories, category='fact' only (should NOT prompt) ===")
    for m in list_memories(category="fact"):
        print(f"  #{m['id']} [{m['category']}] {m['content']}")

    print("\n=== search_memory('Grade 4') (should NOT prompt) ===")
    for m in search_memory("Grade 4"):
        print(f"  #{m['id']} [{m['category']}] {m['content']}")

    print("\n=== search_memory('nonexistent xyz') - expect empty list ===")
    print(search_memory("nonexistent xyz"))

    print("\n=== save_memory with invalid category (should NOT prompt - raises immediately) ===")
    try:
        save_memory("This should never be saved.", "not_a_real_category")
        print("ERROR: should have raised ValueError")
    except ValueError as e:
        print(f"Correctly rejected: {e}")

    print("\n=== wildcard-safe search ===")
    print(save_memory("Battery reported at 100% charge during the test.", "fact"))
    print("Searching literal '100%' (should match only the exact substring):")
    for m in search_memory("100%"):
        print(f"  #{m['id']} [{m['category']}] {m['content']}")

    print("\n=== category fallback: query matches nothing, category given ===")
    print("Searching 'totally unrelated phrase' in category='fact' (should fall back to listing facts, not return empty):")
    for m in search_memory("totally unrelated phrase xyz", category="fact"):
        print(f"  #{m['id']} [{m['category']}] {m['content']}")


if __name__ == "__main__":
    main()
