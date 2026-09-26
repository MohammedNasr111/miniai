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
from tools.memory.memory_tools import list_memories, save_memory, search_memory

TOOL_FUNCTIONS = {
    "list_directory": list_directory,
    "search_files": search_files,
    "read_file": read_file,
    "create_file": create_file,
    "write_file": write_file,
    "delete_file": delete_file,
    "save_memory": save_memory,
    "search_memory": search_memory,
    "list_memories": list_memories,
}

MEMORY_CATEGORIES = ["fact", "preference", "project", "research"]

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
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Save an important fact, preference, project detail, or research finding to long-term memory for future conversations. This will prompt the user for confirmation. Only use this for information worth remembering long-term - not for casual conversational context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "The information to remember, written as a self-contained statement."},
                    "category": {
                        "type": "string",
                        "enum": MEMORY_CATEGORIES,
                        "description": "Which kind of memory this is.",
                    },
                },
                "required": ["content", "category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_memory",
            "description": "Search long-term memory for previously saved information matching a text query. This is literal substring matching, not semantic search - it will not find conceptually related content phrased differently. If a category is specified and the exact query finds nothing, this automatically falls back to showing recent memories in that category instead of returning empty. If you get no results at all and no category was specified, try list_memories with a likely category, or retry with simpler/different keywords, before concluding nothing is remembered.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text to look for in saved memories."},
                    "category": {
                        "type": "string",
                        "enum": MEMORY_CATEGORIES,
                        "description": "Optional: restrict the search to one category.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_memories",
            "description": "List recently saved long-term memories, optionally filtered by category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": MEMORY_CATEGORIES,
                        "description": "Optional: only list memories in this category.",
                    },
                },
                "required": [],
            },
        },
    },
]
