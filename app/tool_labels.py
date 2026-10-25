"""Friendly tool names for the app activity line."""

from __future__ import annotations

# (in_progress label without ellipsis, completed label)
_LABELS: dict[str, tuple[str, str]] = {
    "web_research": ("Researching the web", "Researched the web"),
    "web_search": ("Searching the web", "Searched the web"),
    "fetch_url": ("Reading a page", "Read a page"),
    "browser_open": ("Opening a page", "Opened a page"),
    "browser_observe": ("Looking at the page", "Observed the page"),
    "browser_click": ("Clicking on the page", "Clicked on the page"),
    "browser_type": ("Typing on the page", "Typed on the page"),
    "create_file": ("Creating a file", "Created a file"),
    "write_file": ("Writing a file", "Wrote a file"),
    "delete_file": ("Deleting a file", "Deleted a file"),
    "read_file": ("Reading a file", "Read a file"),
    "list_directory": ("Listing a folder", "Listed a folder"),
    "search_files": ("Searching files", "Searched files"),
    "search_knowledge": ("Searching knowledge", "Searched knowledge"),
    "index_documents": ("Indexing documents", "Indexed documents"),
    "save_memory": ("Saving a memory", "Saved a memory"),
    "search_memory": ("Searching memory", "Searched memory"),
    "list_memories": ("Listing memories", "Listed memories"),
    "desktop_list_windows": ("Listing windows", "Listed windows"),
    "desktop_read_window": ("Reading a window", "Read a window"),
    "desktop_begin_task": ("Starting a desktop task", "Started a desktop task"),
    "desktop_set_text": ("Setting text", "Set text"),
    "desktop_insert_text": ("Inserting text", "Inserted text"),
    "desktop_press": ("Pressing keys", "Pressed keys"),
    "ws_write": ("Writing workspace file", "Wrote a workspace file"),
    "ws_edit": ("Editing workspace file", "Edited a workspace file"),
    "ws_read": ("Reading workspace file", "Read a workspace file"),
    "ws_list": ("Listing workspace", "Listed workspace"),
    "run_file": ("Running a file", "Ran a file"),
    "run_code": ("Running code", "Ran code"),
    "run_tests": ("Running tests", "Ran tests"),
    "calculate": ("Calculating", "Calculated"),
    "analyze_table": ("Analyzing a table", "Analyzed a table"),
    "ws_find_project": ("Finding a project", "Found a project"),
    "move_file": ("Moving a file", "Moved a file"),
    "move_files": ("Moving files", "Moved files"),
    "install_package": ("Installing a package", "Installed a package"),
    "workspace_import": ("Importing a project", "Imported a project"),
    "workspace_export": ("Exporting a project", "Exported a project"),
    "workspace_history": ("Checking history", "Checked history"),
    "workspace_restore": ("Restoring files", "Restored files"),
}


def label_for(tool_name: str, *, done: bool) -> str:
    pair = _LABELS.get(tool_name)
    if pair is None:
        return tool_name
    return pair[1] if done else pair[0]


def format_duration(seconds: float) -> str:
    s = max(0, int(round(seconds)))
    if s < 60:
        return f"{s}s"
    m, rem = divmod(s, 60)
    if m < 60:
        return f"{m}m {rem}s" if rem else f"{m}m"
    h, rem_m = divmod(m, 60)
    return f"{h}h {rem_m}m"
