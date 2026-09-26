"""Maps tool names to their callables and their JSON-schema
descriptions for the LLM. Only the three AUTO_ALLOW filesystem tools
are registered for now - CONFIRM/ALWAYS_CONFIRM tools (create, write,
delete) get wired in once this loop is proven working.
"""

from tools.filesystem.fs_tools import list_directory, read_file, search_files

TOOL_FUNCTIONS = {
    "list_directory": list_directory,
    "search_files": search_files,
    "read_file": read_file,
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": "List the files and folders directly inside a given directory path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to the directory."},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Recursively search a directory tree for filenames containing a text pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "root": {"type": "string", "description": "Absolute path to start searching from."},
                    "pattern": {"type": "string", "description": "Substring to match in filenames, case-insensitive."},
                },
                "required": ["root", "pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read and return the full text contents of a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to the file to read."},
                },
                "required": ["path"],
            },
        },
    },
]
