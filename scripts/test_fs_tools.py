"""Manual test for Stage 3 permission gate + filesystem tools.
Run this and watch: the first three calls (list/search/read) should
NOT prompt you at all. The create call SHOULD prompt once. Answer
"yes". Then it deletes the same test file, which should ALSO prompt
(a separate, always-confirm prompt) - answer "yes" again to clean up.
"""

import os

from tools.filesystem.fs_tools import (
    create_file,
    delete_file,
    list_directory,
    read_file,
    search_files,
)


def main() -> None:
    test_dir = os.getcwd()
    test_file = os.path.join(test_dir, "_stage3_test_file.txt")
    print("=== list_directory (should NOT prompt) ===")
    entries = list_directory(test_dir)
    print(f"{len(entries)} entries found")
    print("\n=== search_files (should NOT prompt) ===")
    matches = search_files(test_dir, "ARCHITECTURE")
    print(f"Matches: {matches}")
    print("\n=== read_file on ARCHITECTURE.md (should NOT prompt) ===")
    content = read_file(os.path.join(test_dir, "ARCHITECTURE.md"))
    print(f"Read {len(content)} characters")
    print("\n=== create_file (SHOULD prompt - answer yes) ===")
    create_file(test_file, "Stage 3 permission gate test.\n")
    print("File created.")
    print("\n=== delete_file (SHOULD prompt separately - answer yes) ===")
    delete_file(test_file)
    print("File deleted.")


if __name__ == "__main__":
    main()
