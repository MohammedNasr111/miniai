"""Manual test for Stage 3 permission gate + filesystem tools.
Run this and watch: the first three calls (list/search/read) should
NOT prompt you at all. The create call SHOULD prompt once. Answer
"yes". Then it deletes the same test file, which should ALSO prompt
(a separate, always-confirm prompt) - answer "yes" again to clean up.

Mutating create/delete run in a temp folder outside the project so
protected-path rules are not triggered.
"""

import os
import tempfile
from pathlib import Path

from tools.filesystem.fs_tools import (
    create_file,
    delete_file,
    list_directory,
    read_file,
    search_files,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    print("=== list_directory (should NOT prompt) ===")
    entries = list_directory(str(PROJECT_ROOT))
    print(f"{len(entries)} entries found")
    print("\n=== search_files (should NOT prompt) ===")
    matches = search_files(str(PROJECT_ROOT), "ARCHITECTURE")
    print(f"Matches: {matches}")
    print("\n=== read_file on ARCHITECTURE.md (should NOT prompt) ===")
    content = read_file(str(PROJECT_ROOT / "ARCHITECTURE.md"))
    print(f"Read {len(content)} characters")

    with tempfile.TemporaryDirectory(prefix="miniai_fs_tools_") as tmp:
        # Ensure temp dir is outside the repo.
        tmp_path = Path(tmp).resolve()
        assert PROJECT_ROOT.resolve() not in tmp_path.parents and tmp_path != PROJECT_ROOT.resolve()
        test_file = str(tmp_path / "_stage3_test_file.txt")
        print("\n=== create_file (SHOULD prompt - answer yes) ===")
        print(f"(temp path outside repo: {test_file})")
        create_file(test_file, "Stage 3 permission gate test.\n")
        print("File created.")
        print("\n=== delete_file (SHOULD prompt separately - answer yes) ===")
        delete_file(test_file)
        print("File moved to Recycle Bin.")


if __name__ == "__main__":
    main()
