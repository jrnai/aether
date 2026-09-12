"""Unit tests for the Aider-style search/replace block parser and fuzzy patch engine."""
from pathlib import Path
import pytest

from src.servers.files_server import (
    parse_search_replace_blocks,
    parse_unified_diff_blocks,
    fuzzy_replace_block,
    patch_file_content,
)


def test_parse_search_replace_single_block() -> None:
    text = """
Here is the proposed change:
<<<<<<< SEARCH
def old_fn():
    return 1
=======
def new_fn():
    return 2
>>>>>>> REPLACE
Let me know what you think!
"""
    blocks = parse_search_replace_blocks(text)
    assert len(blocks) == 1
    assert "def old_fn():" in blocks[0][0]
    assert "return 1" in blocks[0][0]
    assert "def new_fn():" in blocks[0][1]
    assert "return 2" in blocks[0][1]


def test_parse_search_replace_multiple_blocks() -> None:
    text = """
<<<<<<< SEARCH
x = 10
=======
x = 20
>>>>>>> REPLACE

<<<<<<< SEARCH
y = "hello"
=======
y = "world"
>>>>>>> REPLACE
"""
    blocks = parse_search_replace_blocks(text)
    assert len(blocks) == 2
    assert blocks[0] == ("x = 10", "x = 20")
    assert blocks[1] == ('y = "hello"', 'y = "world"')


def test_parse_unified_diff_blocks() -> None:
    diff = """--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,3 @@
-val = 1
+val = 2
 unchanged
"""
    blocks = parse_unified_diff_blocks(diff)
    assert len(blocks) == 1
    assert "val = 1" in blocks[0][0]
    assert "val = 2" in blocks[0][1]
    assert "unchanged" in blocks[0][0]
    assert "unchanged" in blocks[0][1]


def test_fuzzy_replace_exact_match() -> None:
    content = "alpha = 1\nbeta = 2\ngamma = 3"
    updated, tier = fuzzy_replace_block(content, "beta = 2", "beta = 200")
    assert tier == "exact"
    assert updated == "alpha = 1\nbeta = 200\ngamma = 3"


def test_fuzzy_replace_line_ending_normalization() -> None:
    # Content has CRLF, search has LF
    content = "alpha = 1\r\nbeta = 2\r\ngamma = 3"
    search = "beta = 2\ngamma = 3"
    replace = "beta = 42\ngamma = 43"

    updated, tier = fuzzy_replace_block(content, search, replace)
    assert tier == "line_ending_normalized"
    assert "\r\n" in updated
    assert "beta = 42\r\ngamma = 43" in updated


def test_fuzzy_replace_trailing_whitespace_tolerance() -> None:
    # File content has trailing spaces on lines
    content = "def calculate():   \n    total = 0   \n    return total"
    # 7B model generated clean lines without trailing spaces
    search = "def calculate():\n    total = 0\n    return total"
    replace = "def calculate():\n    total = 100\n    return total"

    updated, tier = fuzzy_replace_block(content, search, replace)
    assert tier == "trailing_whitespace_stripped"
    assert "total = 100" in updated


def test_fuzzy_replace_indentation_shift_tolerance() -> None:
    # File content is indented inside a class (4 spaces)
    content = (
        "class Worker:\n"
        "    def run(self):\n"
        "        status = 'idle'\n"
        "        return status\n"
    )
    # 7B model stripped outer class indentation (0 spaces)
    search = (
        "def run(self):\n"
        "    status = 'idle'\n"
        "    return status"
    )
    replace = (
        "def run(self):\n"
        "    status = 'active'\n"
        "    logger.info('running')\n"
        "    return status"
    )

    updated, tier = fuzzy_replace_block(content, search, replace)
    assert tier == "indentation_adjusted"
    # Verification: replacement must have preserved the 4-space class indentation!
    assert "    def run(self):\n        status = 'active'\n        logger.info('running')\n        return status" in updated


def test_patch_file_content_with_aider_blocks(tmp_path: Path) -> None:
    file = tmp_path / "module.py"
    file.write_text("def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n", encoding="utf-8")

    patch_text = """
<<<<<<< SEARCH
def add(a, b):
    return a + b
=======
def add(a, b):
    \"\"\"Add two numbers.\"\"\"
    return a + b
>>>>>>> REPLACE
"""
    res = patch_file_content(str(file), target=patch_text, root_dir=tmp_path)
    assert res["status"] == "success"
    assert res["blocks_applied"] == 1

    content = file.read_text(encoding="utf-8")
    assert '"""Add two numbers."""' in content


def test_patch_file_content_non_unique_error(tmp_path: Path) -> None:
    file = tmp_path / "test.txt"
    file.write_text("item = 1\nitem = 1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="matches 2 times"):
        patch_file_content(str(file), "item = 1", "item = 2", root_dir=tmp_path)


def test_patch_file_content_not_found_error(tmp_path: Path) -> None:
    file = tmp_path / "test.txt"
    file.write_text("greeting = 'hi'\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Failed exact match"):
        patch_file_content(str(file), "goodbye = 'bye'", "goodbye = 'see ya'", root_dir=tmp_path)
