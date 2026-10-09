"""Read-only workspace resolution of linked worktrees."""
import contextlib
import importlib.util
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "resolve_workspace.py"
spec = importlib.util.spec_from_file_location("resolve", SCRIPT)
resolve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resolve)


class TestWorktreeResolution(unittest.TestCase):
    def test_linked_repo_is_recognized_without_metadata_changes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "source"
            repo.mkdir()
            def git(*args):
                subprocess.run(["git", "-C", str(repo), *args], check=True,
                               capture_output=True)
            git("init", "-b", "main")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.invalid")
            (repo / "file.txt").write_text("initial\n")
            git("add", ".")
            git("commit", "-m", "initial")
            workspace = root / "testspace"
            (workspace / "repos").mkdir(parents=True)
            (workspace / "workspace.yaml").write_text("project: test\nrepos:\n  backend: {}\n")
            worktree = workspace / "repos" / "backend"
            git("worktree", "add", "-b", "feature/test", str(worktree))
            before = (worktree / ".git").read_bytes()
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                result = resolve.locate_repo(str(worktree))
            self.assertEqual(result, 0)
            data = json.loads(out.getvalue())["data"]
            self.assertEqual(data["mode"], "located")
            self.assertEqual(data["worktree_compatibility"]["branch"], "feature/test")
            self.assertEqual((worktree / ".git").read_bytes(), before)
            out = io.StringIO()
            with patch.object(resolve._paths, "check_worktree", side_effect=RuntimeError("bad path")):
                with contextlib.redirect_stdout(out):
                    result = resolve.locate_repo(str(worktree))
            self.assertEqual(result, 1)
            self.assertEqual(json.loads(out.getvalue())["status"], "error")
            self.assertEqual((worktree / ".git").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
