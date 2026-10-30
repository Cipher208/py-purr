"""Судья задачи «CI снова зелёный».

Пять проверок, каждая возвращает код, а не текст:
  1. формат   ruff format --check purr tests -> exit 0
  2. линт     ruff check purr tests          -> exit 0
  3. пин      ruff==<версия> в pyproject и установленная версия совпадает
  4. формат-только  каждый изменённый .py байт-в-байт равен `ruff format` от базы;
                    новые .py в режиме форматирования запрещены
  5. тесты    pytest с порогом покрытия 85 — ровно то, что запускает CI

Проверка 4 сильнее сравнения AST: AST не видит комментарии и правки внутри
строковых литералов, а байтовое сравнение с выводом форматтера видит всё.
Смысл: файл обязан быть ровно тем, что форматтер делает из базовой версии,
значит никакой другой правки в нём нет по построению.

База: тег accept-base, если он есть, иначе HEAD.
"""

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def base_ref() -> str:
    tag = git("rev-parse", "-q", "--verify", "refs/tags/accept-base")
    return "accept-base" if tag.returncode == 0 else "HEAD"


def check_format() -> tuple[bool, str]:
    r = subprocess.run(
        [sys.executable, "-m", "ruff", "format", "--check", "purr", "tests"],
        cwd=ROOT, capture_output=True, text=True,
    )
    lines = (r.stdout + r.stderr).strip().splitlines()
    return r.returncode == 0, (lines[-1] if lines else "нет вывода")


def check_lint() -> tuple[bool, str]:
    r = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "purr", "tests"],
        cwd=ROOT, capture_output=True, text=True,
    )
    lines = (r.stdout + r.stderr).strip().splitlines()
    return r.returncode == 0, (lines[-1] if lines else "нет вывода")


def check_pin() -> tuple[bool, str]:
    text = PYPROJECT.read_text(encoding="utf-8")
    dev = re.search(r"dev\s*=\s*\[(.*?)\]", text, re.S)
    if not dev:
        return False, "в pyproject нет блока dev-зависимостей"
    m = re.search(r'"ruff(==|>=)([^"]+)"', dev.group(1))
    if not m:
        return False, "ruff не объявлен в dev-зависимостях"
    if m.group(1) != "==":
        return False, f"ruff объявлен как ruff{m.group(1)}{m.group(2)} — это диапазон, не версия"
    pinned = m.group(2)
    r = subprocess.run(
        [sys.executable, "-m", "ruff", "--version"], cwd=ROOT, capture_output=True, text=True
    )
    installed = r.stdout.strip().split()[-1] if r.returncode == 0 else "?"
    if installed != pinned:
        return False, f"пин {pinned}, в окружении {installed} — локальный прогон не равен CI"
    return True, f"ruff=={pinned}, окружение совпадает"


def changed_py() -> list[str]:
    ref = base_ref()
    out = git("diff", "--name-status", ref, "--", ".", ":!.dev-team").stdout
    files, added = [], []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status, path = parts[0], parts[-1]
        if not path.endswith(".py"):
            continue
        if status.startswith("A"):
            added.append(path)
        else:
            files.append(path)
    untracked = git("status", "--porcelain", "--untracked-files=all").stdout
    for line in untracked.splitlines():
        if line.startswith("?? ") and line[3:].endswith(".py") and ".dev-team/" not in line:
            added.append(line[3:])
    return files, added


def check_format_only() -> tuple[bool, str]:
    ref = base_ref()
    files, added = changed_py()
    if added:
        return False, f"в режиме форматирования появились новые .py: {', '.join(added)}"
    if not files:
        return True, f"нет изменённых .py относительно {ref}"

    tmp = Path(tempfile.mkdtemp(prefix="purr-fmt-"))
    try:
        shutil.copy2(PYPROJECT, tmp / "pyproject.toml")
        for f in files:
            base = git("show", f"{ref}:{f}")
            if base.returncode != 0:
                return False, f"нет базовой версии {f} в {ref}"
            dst = tmp / f
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(base.stdout.encode("utf-8"))
        r = subprocess.run(
            [sys.executable, "-m", "ruff", "format", "."], cwd=tmp, capture_output=True, text=True
        )
        if r.returncode != 0:
            lines = (r.stdout + r.stderr).strip().splitlines()
            return False, f"форматтер не смог обработать базу: {lines[-1] if lines else '?'}"

        extra = []
        for f in files:
            want = (tmp / f).read_bytes()
            have = (ROOT / f).read_bytes()
            if want != have:
                extra.append(f)
        if extra:
            return False, (
                "файл отличается от «форматтер(база)» — это не только форматирование: "
                + ", ".join(extra)
            )
        return True, f"{len(files)} изменённых .py равны форматтер(база {ref}), новых .py нет"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def check_tests() -> tuple[bool, str]:
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--cov=purr",
         "--cov-report=term-missing", "--cov-fail-under=85"],
        cwd=ROOT, capture_output=True, text=True,
    )
    lines = [ln for ln in (r.stdout + r.stderr).strip().splitlines() if ln.strip()]
    return r.returncode == 0, (lines[-1] if lines else "нет вывода")


def main() -> int:
    results = [
        ("формат", check_format()),
        ("линт", check_lint()),
        ("пин", check_pin()),
        ("формат-только", check_format_only()),
        ("тесты", check_tests()),
    ]
    failed = 0
    for name, (ok, detail) in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
        failed += 0 if ok else 1
    print(f"ИТОГ: {len(results) - failed}/{len(results)} проверок пройдено")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
