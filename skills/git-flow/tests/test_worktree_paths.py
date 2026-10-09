"""Integration regressions for real linked-worktree metadata, no user repo writes."""
import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "worktree_paths.py"
spec = importlib.util.spec_from_file_location("paths", SCRIPT)
paths = importlib.util.module_from_spec(spec)
spec.loader.exec_module(paths)


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True,
                                   stderr=subprocess.PIPE).strip()


class TestPortablePointers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "main repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "main")
        git(self.repo, "config", "user.name", "Test")
        git(self.repo, "config", "user.email", "test@example.invalid")
        (self.repo / "file.txt").write_text("original\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "initial")
        self.wt = self.root / "first worktree"
        git(self.repo, "worktree", "add", "-b", "feature/first", str(self.wt))

    def tearDown(self):
        self.tmp.cleanup()

    def test_repair_preserves_dirty_worktree_and_both_links(self):
        (self.wt / "file.txt").write_text("user edit\n")
        (self.wt / "untracked.txt").write_text("untracked\n")
        head = git(self.wt, "rev-parse", "HEAD")
        status = git(self.wt, "status", "--porcelain")
        result = paths.repair_worktree(self.wt)
        self.assertEqual(result["head"], head)
        self.assertEqual(git(self.wt, "status", "--porcelain"), status)
        forward = (self.wt / ".git").read_text().strip().removeprefix("gitdir: ")
        self.assertFalse(Path(forward).is_absolute())
        admin = (self.wt / forward).resolve()
        backward = (admin / "gitdir").read_text().strip()
        self.assertFalse(Path(backward).is_absolute())
        self.assertEqual((admin / backward).resolve(),
                         Path(os.path.realpath(str(self.wt / ".git"))))
        listed = git(self.repo, "worktree", "list")
        self.assertTrue(
            any(os.path.realpath(line.rsplit(None, 2)[0]) == os.path.realpath(str(self.wt))
                for line in listed.splitlines()),
            listed)

    def test_nested_creation_and_duplicate_admin_basename(self):
        second = self.root / "nested" / self.wt.name
        second.parent.mkdir()
        git(self.wt, "worktree", "add", "-b", "feature/second", str(second))
        admin = Path(git(second, "rev-parse", "--absolute-git-dir"))
        self.assertNotEqual(admin.name, second.name)
        paths.repair_worktree(second)
        self.assertEqual(git(second, "branch", "--show-current"), "feature/second")
        self.assertEqual(git(second, "rev-parse", "HEAD"), git(self.repo, "rev-parse", "HEAD"))

    def test_validation_failure_rolls_back_original_pointer_bytes(self):
        admin = Path(git(self.wt, "rev-parse", "--absolute-git-dir"))
        pointers = [self.wt / ".git", admin / "gitdir"]
        originals = [p.read_bytes() for p in pointers]
        with patch.object(paths, "check_worktree", side_effect=RuntimeError("other Git failed")):
            with self.assertRaisesRegex(RuntimeError, "other Git failed"):
                paths.repair_worktree(self.wt)
        self.assertEqual([p.read_bytes() for p in pointers], originals)
        self.assertEqual(git(self.wt, "branch", "--show-current"), "feature/first")

    def test_mismatched_back_pointer_is_rejected_without_writes(self):
        admin = Path(git(self.wt, "rev-parse", "--absolute-git-dir"))
        (admin / "gitdir").write_text(str(self.repo / ".git") + "\n")
        original = (self.wt / ".git").read_bytes()
        with self.assertRaisesRegex(RuntimeError, "another worktree"):
            paths.repair_worktree(self.wt)
        self.assertEqual((self.wt / ".git").read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
