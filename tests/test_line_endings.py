"""The working tree must agree with git wherever `.gitattributes` pins LF.

`.gitattributes` declares `text eol=lf` for a set of extensions, so git stores LF
in the index and checks LF out. Nothing keeps the *working copy* that way
afterwards: a file rewritten by a CRLF-emitting tool normalises back to the same
blob on commit, so `git status` stays clean while the bytes on disk disagree with
the index. That disagreement is invisible, and it silently defeats every string
replacement written against `"\\n"` — the pattern simply never matches.

The scope is the declared contract, not "every text file", and the difference is
measured rather than assumed. With `core.autocrlf=true` (this machine), a file
covered only by `* text=auto` — `.gitattributes` itself, `.gitignore`, `LICENSE` —
is checked out CRLF by git on purpose. Reporting those would make the check red in
a pristine clone and blame the repository for the developer's git config. So the
extension set is read out of `.gitattributes`: whatever it pins to `eol=lf`, this
module holds to `eol=lf`.

The check cannot be `git status`; it has to read the bytes. Only files git tracks
are read (an untracked file is not part of the contract), and each offender is
named with its line count so the repair is addressable rather than "somewhere
there is a CRLF".
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

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


def enforced_extensions(root: Path) -> frozenset[str]:
    """Extensions `.gitattributes` pins to LF, lower-cased, leading dot kept.

    Only `*.ext` patterns count. The catch-all `* text=auto` is not a promise
    about line endings — it defers to `core.autocrlf` — and treating it as one
    would put the whole disk in scope and make the result depend on each
    developer's git config.
    """
    extensions: set[str] = set()
    for raw in (root / ".gitattributes").read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        pattern, *attributes = line.split()
        if "eol=lf" not in [attribute.lower() for attribute in attributes]:
            continue
        if pattern.startswith("*.") and "/" not in pattern:
            extensions.add(pattern[1:].lower())
    return frozenset(extensions)


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
    """Tracked files under `root` that `eol=lf` covers but that hold CRLF.

    Counting is done on bytes, not on text: a universal-newline read translates
    `\\r\\n` away and would report a clean tree. Empty files and files without
    any newline carry no CRLF and therefore never appear here.
    """
    extensions = enforced_extensions(root)
    offenders: list[tuple[str, int]] = []
    for name in tracked_files(root):
        if Path(name).suffix.lower() not in extensions:
            continue
        data = (root / name).read_bytes()
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            # An extension pinned to eol=lf that holds non-text bytes is its own
            # problem; this check is about line endings and does not judge it.
            continue
        crlf = data.count(b"\r\n")
        if crlf:
            offenders.append((name, crlf))
    return offenders


def _report(offenders: list[tuple[str, int]]) -> str:
    lines = [
        f"{len(offenders)} tracked file(s) hold CRLF in the working tree while "
        f".gitattributes pins their extension to eol=lf:",
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


def test_gitattributes_pins_python_to_lf() -> None:
    """Guard against the check going green because the contract was deleted.

    If the `*.py text eol=lf` line disappears, the extension set empties, nothing
    is inspected, and the module passes over zero files. That is the failure this
    test refuses to let pass silently.
    """
    assert ".py" in enforced_extensions(REPO_ROOT)


def test_git_lists_tracked_files() -> None:
    """Guard against the check passing because git answered nothing.

    A failed or misdirected `git ls-files` yields an empty list, and an empty
    list yields no offenders — a green gate over zero files.
    """
    assert tracked_files(REPO_ROOT) != []


def test_detector_counts_crlf_lines_per_file(tmp_path: Path) -> None:
    """The detector's own control: a controlled repo, a known answer.

    Without this the module could be green on any tree by inspecting nothing.
    Empty files and files with no newline at all are in the fixture because a
    line-ending check that trips over them is unusable.
    """
    _git(tmp_path, "init", "-q")
    (tmp_path / ".gitattributes").write_bytes(b"*.py text eol=lf\n")
    (tmp_path / "crlf.py").write_bytes(b"one\r\ntwo\r\n")
    (tmp_path / "empty.py").write_bytes(b"")
    (tmp_path / "single.py").write_bytes(b"no newline here")
    _git(tmp_path, "add", ".gitattributes", "crlf.py", "empty.py", "single.py")

    assert find_crlf_files(tmp_path) == [("crlf.py", 2)]


def test_detector_ignores_out_of_contract_files(tmp_path: Path) -> None:
    """Three ways a file can carry CRLF and still not be a defect.

    Not tracked: outside the contract with git. Not a pinned extension: the
    attributes file makes no promise, so git's `core.autocrlf` decides. Pinned
    but binary: it has no line endings to be consistent about.
    """
    _git(tmp_path, "init", "-q")
    (tmp_path / ".gitattributes").write_bytes(
        b"*.py text eol=lf\n*.png binary\n*.db binary\n"
    )
    (tmp_path / "clean.py").write_bytes(b"clean\n")
    (tmp_path / "notes.log").write_bytes(b"one\r\ntwo\r\n")
    (tmp_path / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\r\n")
    (tmp_path / "dump.db").write_bytes(b"header\r\npayload\r\n")
    (tmp_path / "untracked.py").write_bytes(b"one\r\ntwo\r\n")
    _git(tmp_path, "add", ".gitattributes", "clean.py", "notes.log", "image.png", "dump.db")

    assert find_crlf_files(tmp_path) == []
