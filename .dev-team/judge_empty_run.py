"""Судья задачи «пустой прогон не выглядит зелёным».

Проверяет вердикт режима 3, когда прогон фактически не состоялся:
  1. ребёнок не подтвердил ни одной записи -> run-journal обязан отказать
     и сказать «ПРОГОН НЕ СОСТОЯЛСЯ», а не напечатать разрыв 0;
  2. контроль: нормальный прогон -> exit=0 и этой строки нет.

Сейчас первый случай даёт exit=0: пустая база проходит проверку как
«расхождений нет», хотя проверять было нечего.
"""

import importlib.util
import io
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tools" / "crash_harness.py"


def load_harness():
    spec = importlib.util.spec_from_file_location("crash_harness_under_test", HARNESS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="purr-empty-"))
    bad = 0
    try:
        stub = tmp / "stub_child.py"
        stub.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")

        # 1. ребёнок умирает, ничего не записав
        mod = load_harness()
        mod.SELF = str(stub)
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = mod.cmd_run_journal(1)
        out = buf.getvalue()
        refused = code == 1 and "ПРОГОН НЕ СОСТОЯЛСЯ" in out
        print(f"{'PASS' if refused else 'FAIL'}  пустой прогон: exit={code}, отказ={'есть' if 'ПРОГОН НЕ СОСТОЯЛСЯ' in out else 'НЕТ'}")
        bad += 0 if refused else 1

        # 2. контроль: нормальный прогон
        mod = load_harness()
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = mod.cmd_run_journal(1)
        out = buf.getvalue()
        ok = code == 0 and "ПРОГОН НЕ СОСТОЯЛСЯ" not in out
        print(f"{'PASS' if ok else 'FAIL'}  нормальный прогон: exit={code}, отказа нет={'да' if 'ПРОГОН НЕ СОСТОЯЛСЯ' not in out else 'НЕТ'}")
        bad += 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"ИТОГ: провалено {bad} из 2")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
