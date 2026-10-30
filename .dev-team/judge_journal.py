"""Судья задачи «режим 3 стенда умеет отказывать на разрыве».

Проверяет не текст, а поведение вердикта на заведомо расходящейся базе:
  1. контроль: база без разрыва -> verify-journal возвращает 0;
  2. дефект: из журнала удалено одно событие -> verify-journal обязан вернуть 1.

Сейчас (до правки) второй случай возвращает 0: разрыв считается и печатается,
но в вердикт не входит. Это и есть красное.

Команда самодостаточна: работает в свежем клоне, `.venv` не требует.
"""

import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tools" / "crash_harness.py"
KEYS = ("k1", "k2", "k3")


def build(tmp: Path) -> Path:
    """База с журналом в том же файле: три ключа, три события."""
    sys.path.insert(0, str(ROOT))
    from purr import EventStream, Store

    db = tmp / "store.db"
    store = Store(str(db), journal=EventStream(str(db)))
    try:
        for key in KEYS:
            store.set(key, "v")
    finally:
        store.close()
    return db


def verify(db: Path, keys_file: Path) -> tuple[int, dict]:
    r = subprocess.run(
        [sys.executable, str(HARNESS), "verify-journal", str(db), str(db), str(keys_file)],
        capture_output=True, text=True, cwd=ROOT,
    )
    payload = {}
    for line in reversed(r.stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                pass
            break
    return r.returncode, payload


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="purr-j3-"))
    try:
        keys_file = tmp / "confirmed.txt"
        keys_file.write_text("\n".join(KEYS) + "\n", encoding="utf-8")
        db = build(tmp)

        code_ok, data_ok = verify(db, keys_file)
        control = code_ok == 0
        print(f"{'PASS' if control else 'FAIL'}  контроль: разрыва нет -> exit={code_ok}, gap={data_ok.get('gap')}")

        conn = sqlite3.connect(db)
        try:
            row = conn.execute(
                "SELECT rowid FROM events WHERE payload LIKE '%k2%' LIMIT 1"
            ).fetchone()
            conn.execute("DELETE FROM events WHERE rowid = ?", (row[0],))
            conn.commit()
        finally:
            conn.close()

        code_bad, data_bad = verify(db, keys_file)
        gap = data_bad.get("gap")
        refuses = code_bad == 1 and gap == 1
        print(f"{'PASS' if refuses else 'FAIL'}  дефект: разрыв 1 -> exit={code_bad}, gap={gap} (ожидалось exit=1, gap=1)")

        ok = control and refuses
        print(f"ИТОГ: {'режим 3 отказывает' if ok else 'режим 3 молчит при разрыве'}")
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
