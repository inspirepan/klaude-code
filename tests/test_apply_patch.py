import os
import tempfile
import unittest
from pathlib import Path

# Ensure imports from src/
ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if SRC_DIR.is_dir() and str(SRC_DIR) not in os.sys.path:  # type: ignore
    os.sys.path.insert(0, str(SRC_DIR))  # type: ignore

from klaude_code.core.tool import DiffError, process_patch  # noqa: E402


class BaseTempDirTest(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_cwd = os.getcwd()
        self._tmp = tempfile.TemporaryDirectory()
        os.chdir(self._tmp.name)

        # Track file operations for verification
        self.written_files: dict[str, str] = {}
        self.removed_files: set[str] = set()

    def tearDown(self) -> None:
        os.chdir(self._orig_cwd)
        self._tmp.cleanup()

    def open_fn(self, path: str) -> str:
        """Mock open function that reads from actual files"""
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            raise DiffError(f"Missing File: {path}") from None

    def write_fn(self, path: str, content: str) -> None:
        """Mock write function that tracks written files"""
        self.written_files[path] = content
        # Also write to actual file for verification
        if "/" in path:
            parent = "/".join(path.split("/")[:-1])
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def remove_fn(self, path: str) -> None:
        """Mock remove function that tracks removed files"""
        self.removed_files.add(path)
        if os.path.exists(path):
            os.remove(path)


class TestProcessPatch(BaseTempDirTest):
    def test_process_patch_add_file(self):
        """Test adding a new file"""
        patch_text = """*** Begin Patch
*** Add File: new_file.txt
+Hello, World!
+This is a new file.
*** End Patch"""

        result = process_patch(patch_text, self.open_fn, self.write_fn, self.remove_fn)

        self.assertEqual(result, "Done!")
        self.assertIn("new_file.txt", self.written_files)
        self.assertEqual(self.written_files["new_file.txt"], "Hello, World!\nThis is a new file.")
        self.assertTrue(os.path.exists("new_file.txt"))

    def test_process_patch_delete_file(self):
        """Test deleting an existing file"""
        # Create file to delete
        with open("to_delete.txt", "w", encoding="utf-8") as f:
            f.write("This file will be deleted\n")

        patch_text = """*** Begin Patch
*** Delete File: to_delete.txt
*** End Patch"""

        result = process_patch(patch_text, self.open_fn, self.write_fn, self.remove_fn)

        self.assertEqual(result, "Done!")
        self.assertIn("to_delete.txt", self.removed_files)
        self.assertFalse(os.path.exists("to_delete.txt"))

    def test_process_patch_simple_update(self):
        """Test simple file update without @@ markers"""
        # Create file to update
        with open("simple.txt", "w", encoding="utf-8") as f:
            f.write("hello\nworld")

        patch_text = """*** Begin Patch
*** Update File: simple.txt
-hello
+Hi
 world
*** End Patch"""

        result = process_patch(patch_text, self.open_fn, self.write_fn, self.remove_fn)

        self.assertEqual(result, "Done!")
        self.assertIn("simple.txt", self.written_files)
        expected_content = "Hi\nworld"
        self.assertEqual(self.written_files["simple.txt"], expected_content)

    def test_process_patch_mixed_operations(self):
        """Test patch with add, update, and delete operations"""
        # Create files
        with open("existing.txt", "w", encoding="utf-8") as f:
            f.write("old content\nkeep this line")
        with open("delete_me.txt", "w", encoding="utf-8") as f:
            f.write("will be deleted")

        patch_text = """*** Begin Patch
*** Update File: existing.txt
-old content
+new content
 keep this line
*** Add File: new.txt
+brand new file
*** Delete File: delete_me.txt
*** End Patch"""

        result = process_patch(patch_text, self.open_fn, self.write_fn, self.remove_fn)

        self.assertEqual(result, "Done!")

        # Check update
        self.assertIn("existing.txt", self.written_files)
        self.assertEqual(self.written_files["existing.txt"], "new content\nkeep this line")

        # Check add
        self.assertIn("new.txt", self.written_files)
        self.assertEqual(self.written_files["new.txt"], "brand new file")

        # Check delete
        self.assertIn("delete_me.txt", self.removed_files)

    def test_process_patch_invalid_format_no_begin(self):
        """Test error when patch doesn't start with *** Begin Patch"""
        patch_text = """*** Invalid Start
*** Add File: test.txt
+content
*** End Patch"""

        with self.assertRaises(AssertionError):
            process_patch(patch_text, self.open_fn, self.write_fn, self.remove_fn)

    def test_process_patch_invalid_format_no_end(self):
        """Test error when patch doesn't have proper end"""
        patch_text = """*** Begin Patch
*** Add File: test.txt
+content"""

        with self.assertRaises(DiffError) as cm:
            process_patch(patch_text, self.open_fn, self.write_fn, self.remove_fn)
        self.assertIn("Invalid patch text", str(cm.exception))

    def test_process_patch_missing_file_for_update(self):
        """Test error when trying to update a non-existent file"""
        patch_text = """*** Begin Patch
*** Update File: nonexistent.txt
@@ some content
-old
+new
*** End Patch"""

        with self.assertRaises(DiffError) as cm:
            process_patch(patch_text, self.open_fn, self.write_fn, self.remove_fn)
        self.assertIn("Missing File: nonexistent.txt", str(cm.exception))

    def test_process_patch_missing_file_for_delete(self):
        """Test error when trying to delete a non-existent file"""
        patch_text = """*** Begin Patch
*** Delete File: nonexistent.txt
*** End Patch"""

        with self.assertRaises(DiffError) as cm:
            process_patch(patch_text, self.open_fn, self.write_fn, self.remove_fn)
        self.assertIn("Missing File: nonexistent.txt", str(cm.exception))

    def test_process_patch_duplicate_file_operations(self):
        """Test error when same file appears multiple times"""
        with open("duplicate.txt", "w", encoding="utf-8") as f:
            f.write("content")

        patch_text = """*** Begin Patch
*** Update File: duplicate.txt
-content
+new content
*** Delete File: duplicate.txt
*** End Patch"""

        with self.assertRaises(DiffError) as cm:
            process_patch(patch_text, self.open_fn, self.write_fn, self.remove_fn)
        self.assertIn("Duplicate Path: duplicate.txt", str(cm.exception))

    def test_process_patch_complex_update(self):
        """Test complex file update with multiple chunks"""
        original = """function hello() {
    console.log("Hello");
}

function goodbye() {
    console.log("Goodbye");
}

const x = 1;"""

        with open("complex.js", "w", encoding="utf-8") as f:
            f.write(original)

        patch_text = """*** Begin Patch
*** Update File: complex.js
-function hello() {
+function sayHello() {
     console.log("Hello");
 }
 
 function goodbye() {
-    console.log("Goodbye");
+    console.log("Farewell");
 }
 
-const x = 1;
+const x = 42;
*** End Patch"""

        result = process_patch(patch_text, self.open_fn, self.write_fn, self.remove_fn)

        self.assertEqual(result, "Done!")
        expected = """function sayHello() {
    console.log("Hello");
}

function goodbye() {
    console.log("Farewell");
}

const x = 42;"""
        self.assertEqual(self.written_files["complex.js"], expected)

    def test_process_patch_file_with_move(self):
        """Test updating a file with move operation"""
        with open("original.txt", "w", encoding="utf-8") as f:
            f.write("content to move")

        patch_text = """*** Begin Patch
*** Update File: original.txt
*** Move to: moved.txt
-content to move
+moved content
*** End Patch"""

        result = process_patch(patch_text, self.open_fn, self.write_fn, self.remove_fn)

        self.assertEqual(result, "Done!")

        # Original should be deleted, new file should be created
        self.assertIn("original.txt", self.removed_files)
        self.assertIn("moved.txt", self.written_files)
        self.assertEqual(self.written_files["moved.txt"], "moved content")

    def test_process_patch_add_file_in_subdirectory(self):
        """Test adding a file in a subdirectory"""
        patch_text = """*** Begin Patch
*** Add File: subdir/new_file.txt
+Content in subdirectory
*** End Patch"""

        result = process_patch(patch_text, self.open_fn, self.write_fn, self.remove_fn)

        self.assertEqual(result, "Done!")
        self.assertIn("subdir/new_file.txt", self.written_files)
        self.assertTrue(os.path.exists("subdir/new_file.txt"))
        self.assertEqual(self.written_files["subdir/new_file.txt"], "Content in subdirectory")

    def test_process_patch_empty_add_file(self):
        """Test adding an empty file"""
        patch_text = """*** Begin Patch
*** Add File: empty.txt
*** End Patch"""

        result = process_patch(patch_text, self.open_fn, self.write_fn, self.remove_fn)

        self.assertEqual(result, "Done!")
        self.assertIn("empty.txt", self.written_files)
        self.assertEqual(self.written_files["empty.txt"], "")

    def test_process_patch_invalid_add_file_line(self):
        """Test error when add file has invalid line format"""
        patch_text = """*** Begin Patch
*** Add File: invalid.txt
invalid line without +
*** End Patch"""

        with self.assertRaises(DiffError) as cm:
            process_patch(patch_text, self.open_fn, self.write_fn, self.remove_fn)
        self.assertIn("Invalid Add File Line", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
