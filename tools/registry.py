"""Maps tool names to their callables and their JSON-schema
descriptions for the LLM.
"""

from tools.filesystem.fs_tools import (
    create_file,
    delete_file,
    list_directory,
    read_file,
    search_files,
    write_file,
)

TOOL_FUNCTIONS = {
    "list_directory": list_directory,
    "search_files": search_files,
    "read_file": read_file,
    "create_file": create_file,
    "write_file": write_file,
    "delete_file": delete_file,
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
    {
        "type": "function",
        "function": {
            "name": "create_file",
            "description": "Create a new file with the given content at the given path. Fails if the file already exists. This will prompt the user for confirmation before proceeding.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to the file to create."},
                    "content": {"type": "string", "description": "Text content to write into the new file."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Overwrite an existing file's content at the given path, replacing whatever was there. This will prompt the user for confirmation before proceeding.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to the file to overwrite."},
                    "content": {"type": "string", "description": "Text content to replace the file's contents with."},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Permanently delete the file at the given path. This cannot be undone and will always prompt the user for confirmation, even if create_file or write_file was just confirmed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute path to the file to delete."},
                },
                "required": ["path"],
            },
        },
    },
]
