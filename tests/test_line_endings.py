"""The working tree must agree with git about line endings.

`.gitattributes` declares `text eol=lf`, so git stores LF in the index and checks
LF out. Nothing keeps the *working copy* that way afterwards: a file rewritten by
a CRLF-emitting tool normalises back to the same blob on commit, so `git status`
stays clean while the bytes on disk disagree with the index. That disagreement is
invisible, and it silently defeats every string replacement written against
`"\\n"` — the pattern simply never matches.

So the check cannot be `git status`; it has to read the bytes. This module reads
only files git tracks (an untracked file is not part of the contract), skips what
`.gitattributes` marks binary, and names each offender together with its line
count so the repair is addressable rather than "somewhere there is a CRLF".
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

# The same set `.gitattributes` marks `binary`. A binary file has no line
# endings to be consistent about, and decoding it as text would either raise or,
# worse, succeed by accident and report a false offender.
BINARY_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".sqlite", ".db", ".pyc"}
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        check=True,
    )


def _in_git_work_tree(root: Path) -> bool:
    """Whether `root` has an index to compare against.

    Deliberately not `_git`: a probe that raises on failure cannot be used as a
    skip condition, it aborts collection instead. Measured — `check=True` here
    turns "not a repository" into `exit=2` and an ERROR during collection, which
    reads like a broken test rather than an absent precondition.
    """
    probe = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=root,
        capture_output=True,
    )
    return probe.returncode == 0


def tracked_files(root: Path) -> list[str]:
    """Paths git tracks under `root`, repo-relative, posix-style.

    `-z` because a path may contain anything, newlines included; splitting on
    `\\0` is the only form that cannot be fooled. Untracked files are absent from
    this list by construction, which is what makes the check about the contract
    with git rather than about the whole disk.
    """
    out = _git(root, "ls-files", "-z").stdout
    return [name for name in out.decode("utf-8").split("\0") if name]


def find_crlf_files(root: Path) -> list[tuple[str, int]]:
    """Every tracked text file under `root` holding CRLF, with its CRLF count.

    Counting is done on bytes, not on text: a universal-newline read translates
    `\\r\\n` away and would report a clean tree. Empty files and files without
    any newline carry no CRLF and therefore never appear here.
    """
    offenders: list[tuple[str, int]] = []
    for name in tracked_files(root):
        if Path(name).suffix.lower() in BINARY_EXTENSIONS:
            continue
        data = (root / name).read_bytes()
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            # Not text: an extension the attributes file does not know about
            # (an image, an archive, a stray dump) still must not be judged.
            continue
        crlf = data.count(b"\r\n")
        if crlf:
            offenders.append((name, crlf))
    return offenders


def _report(offenders: list[tuple[str, int]]) -> str:
    lines = [
        f"{len(offenders)} tracked text file(s) hold CRLF in the working tree "
        f"while .gitattributes declares eol=lf:",
    ]
    lines += [f"  {name}: {count} CRLF line(s)" for name, count in offenders]
    lines.append(
        "The index stores LF, so `git status` reports a clean tree and the "
        "divergence stays invisible until a `\\n` replacement silently misses."
    )
    return "\n".join(lines)


pytestmark = pytest.mark.skipif(
    not _in_git_work_tree(REPO_ROOT),
    reason=(
        "not a git work tree: there is no index to disagree with, so the check "
        "has nothing to compare and must not report success on its own"
    ),
)


def test_working_tree_matches_git_on_line_endings() -> None:
    offenders = find_crlf_files(REPO_ROOT)
    assert offenders == [], _report(offenders)


def test_git_lists_tracked_files() -> None:
    """Guard against the check passing because git answered nothing.

    A failed or misdirected `git ls-files` yields an empty list, and an empty
    list yields no offenders — a green gate over zero files. This test makes
    that failure visible instead of silent.
    """
    assert tracked_files(REPO_ROOT) != []


def test_detector_counts_crlf_lines_per_file(tmp_path: Path) -> None:
    """The detector's own control: a controlled repo, a known answer.

    Without this the module could be green on any tree by inspecting nothing.
    Empty files and files with no newline at all are in the fixture because a
    line-ending check that trips over them is unusable.
    """
    _git(tmp_path, "init", "-q")
    (tmp_path / "crlf.py").write_bytes(b"one\r\ntwo\r\n")
    (tmp_path / "empty.py").write_bytes(b"")
    (tmp_path / "single.py").write_bytes(b"no newline here")
    _git(tmp_path, "add", "crlf.py", "empty.py", "single.py")

    assert find_crlf_files(tmp_path) == [("crlf.py", 2)]


def test_detector_ignores_binary_and_untracked_files(tmp_path: Path) -> None:
    """CRLF is not a defect in a PNG, and an untracked file is not in the contract."""
    _git(tmp_path, "init", "-q")
    (tmp_path / "tracked.py").write_bytes(b"clean\n")
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\r\n")
    (tmp_path / "dump.db").write_bytes(b"header\r\npayload\r\n")
    (tmp_path / "untracked.py").write_bytes(b"one\r\ntwo\r\n")
    _git(tmp_path, "add", "tracked.py", "image.png", "dump.db")

    assert find_crlf_files(tmp_path) == []
