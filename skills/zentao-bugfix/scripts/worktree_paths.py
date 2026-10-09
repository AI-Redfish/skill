#!/usr/bin/env python3
"""Portable linked-worktree pointers; standalone copy shipped with each skill.

Relative gitdir pointers are resolved from their containing directory, not cwd.
Repair changes only the two pointers and rolls them back if validation fails.
"""
import argparse
import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path


def write_bytes_keep_mode(path, content):
    """Overwrite git pointer files; hidden files reject 'wb' CREATE on Windows."""
    mode = path.stat().st_mode
    if not mode & stat.S_IWRITE:
        path.chmod(mode | stat.S_IWRITE)
    try:
        try:
            # r+b avoids the O_CREAT flag that Windows denies for hidden files.
            with open(path, "r+b") as handle:
                handle.write(content)
                handle.truncate(len(content))
        except FileNotFoundError:
            with open(path, "wb") as handle:
                handle.write(content)
    finally:
        if path.stat().st_mode != mode:
            path.chmod(mode)


def native_path(value):
    """Convert Windows drive paths and WSL mount paths for the Python host."""
    value = str(value)
    if os.name == "nt":
        match = re.match(r"^/mnt/([a-zA-Z])(?:/(.*))?$", value)
        if match:
            return match[1].upper() + ":/" + (match[2] or "")
    else:
        match = re.match(r"^([a-zA-Z]):[/\\](.*)$", value)
        if match:
            return "/mnt/" + match[1].lower() + "/" + match[2].replace("\\", "/")
    return value


def git_output(repo, *args, executable="git"):
    repo_arg = str(repo)
    if os.name != "nt" and str(executable).lower().endswith(".exe"):
        match = re.match(r"^/mnt/([a-zA-Z])/(.*)$", repo_arg)
        if match:
            repo_arg = match[1].upper() + ":/" + match[2]
    result = subprocess.run([executable, "-C", repo_arg, *args], capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Git validation failed")
    return result.stdout.strip()


def same_path(left, right):
    """Case-insensitive realpath comparison; expands Windows 8.3 short names."""
    return os.path.normcase(os.path.realpath(str(left))) == os.path.normcase(os.path.realpath(str(right)))


def check_worktree(repo):
    """Read-only checks; also test Windows Git on accessible WSL drive mounts."""
    repo = Path(native_path(repo)).resolve()
    head = git_output(repo, "rev-parse", "HEAD")
    branch = git_output(repo, "symbolic-ref", "--quiet", "--short", "HEAD")
    top = Path(native_path(git_output(repo, "rev-parse", "--show-toplevel")))
    if not same_path(top, repo):
        raise RuntimeError("Expected worktree root %s, got %s" % (repo, top))
    result = {"head": head, "branch": branch, "native_git": "passed",
              "windows_git": "not-applicable", "wsl_git": "not-checked"}
    if os.name == "nt":
        result["windows_git"] = "passed"
    elif re.match(r"^/mnt/[a-zA-Z]/", str(repo)):
        windows_git = shutil.which("git.exe")
        if windows_git:
            windows_head = git_output(repo, "rev-parse", "HEAD", executable=windows_git)
            windows_branch = git_output(repo, "symbolic-ref", "--quiet", "--short", "HEAD",
                                        executable=windows_git)
            windows_top = Path(native_path(git_output(
                repo, "rev-parse", "--show-toplevel", executable=windows_git)))
            if (head, branch) != (windows_head, windows_branch) or not same_path(top, windows_top):
                raise RuntimeError("Windows Git and native Git disagree on worktree identity")
            result["windows_git"] = "passed"
        else:
            result["windows_git"] = "not-checked: git.exe unavailable"
        result["wsl_git"] = "passed" if os.environ.get("WSL_DISTRO_NAME") else "not-checked"
    return result


def repair_worktree(repo):
    """Locate actual admin dir via Git; normalize forward and back pointers."""
    repo = Path(native_path(repo)).resolve()
    pointer = repo / ".git"
    if not pointer.is_file():
        raise RuntimeError("Expected a linked worktree with a .git file: %s" % repo)
    admin_value = git_output(repo, "rev-parse", "--absolute-git-dir")
    admin = Path(native_path(admin_value)).resolve()
    back_pointer = admin / "gitdir"
    if not back_pointer.is_file() or not (admin / "commondir").is_file():
        raise RuntimeError("Not a linked-worktree admin directory: %s" % admin)
    back_value = native_path(back_pointer.read_text(encoding="utf-8").strip())
    back_target = Path(back_value)
    if not back_target.is_absolute():
        back_target = admin / back_target
    if not same_path(back_target, pointer):
        raise RuntimeError("Admin back pointer belongs to another worktree; refusing to overwrite")
    # Compute both before writing: Windows cross-volume relpath raises ValueError.
    forward = os.path.relpath(admin, repo).replace("\\", "/")
    backward = os.path.relpath(pointer, admin).replace("\\", "/")
    # WSL can form /mnt/c -> /mnt/d relatives that cannot work on Windows.
    mount_a = re.match(r"^/mnt/([a-zA-Z])/", str(repo))
    mount_b = re.match(r"^/mnt/([a-zA-Z])/", str(admin))
    if (mount_a or mount_b) and (not mount_a or not mount_b or mount_a[1] != mount_b[1]):
        raise RuntimeError("Worktree and Git admin directory must share a Windows drive for dual access")
    expected = (git_output(repo, "rev-parse", "HEAD"),
                git_output(repo, "symbolic-ref", "--quiet", "--short", "HEAD"))
    originals = {pointer: pointer.read_bytes(), back_pointer: back_pointer.read_bytes()}
    try:
        write_bytes_keep_mode(pointer, ("gitdir: " + forward + "\n").encode("utf-8"))
        write_bytes_keep_mode(back_pointer, (backward + "\n").encode("utf-8"))
        result = check_worktree(repo)
        if expected != (result["head"], result["branch"]):
            raise RuntimeError("Repair unexpectedly changed worktree identity")
    except Exception:
        for path, content in originals.items():
            write_bytes_keep_mode(path, content)
        raise
    result["relative_pointers"] = True
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--repair", action="store_true", help="Explicitly repair linked-worktree pointers")
    args = parser.parse_args()
    try:
        result = repair_worktree(args.repo) if args.repair else check_worktree(args.repo)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": "ok", "data": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
