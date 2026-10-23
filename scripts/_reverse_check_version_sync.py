#!/usr/bin/env python3
"""反向验证 check_version_sync.py：每条断言在应该变红时必须真的变红。

做法：备份 4 个版本文件 → 逐个注入故障 → 跑门禁 → 断言它红 → 还原。
任何一条「注入了故障但门禁仍然全绿」= 这条断言是假绿，必须修。
"""

import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path("/home/surui/gold-etf-analyzer")
GATE = ROOT / "scripts" / "check_version_sync.py"

FILES = {
    "init": ROOT / "src" / "app" / "__init__.py",
    "pyproject": ROOT / "pyproject.toml",
    "uvlock": ROOT / "uv.lock",
    "sw": ROOT / "static" / "sw.js",
    "changelog": ROOT / "CHANGELOG.md",
    "index": ROOT / "docs" / "releases" / "index.md",
    "note": ROOT / "docs" / "releases" / "v0.116.0.md",
    "vstatus": ROOT / "docs" / "version-status.md",
}


def run_gate():
    p = subprocess.run([sys.executable, str(GATE)], capture_output=True, text=True, cwd=ROOT)
    return p.returncode, p.stdout + p.stderr


def restore(backup):
    for name, path in FILES.items():
        shutil.copy2(backup[name], path)


def case(label, mutate, expect_substr):
    backup = {n: pathlib.Path(tempfile.mkdtemp()) / n for n in FILES}
    for n, p in FILES.items():
        shutil.copy2(p, backup[n])
    try:
        mutate()
        code, out = run_gate()
        red = code != 0
        hit = expect_substr in out
        ok = red and hit
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
        print(f"        退出码={code}（{'红' if red else '绿 ← 假绿！'}）  命中期望输出={hit}")
        if not ok:
            print("        ---- 门禁输出 ----")
            for ln in out.splitlines():
                print("        " + ln)
            print("        ----------------")
        return ok
    finally:
        restore(backup)


def main():
    results = []

    # 0) 基线：未注入故障时必须全绿
    code, out = run_gate()
    base_ok = code == 0 and "结果：9 passed" in out
    print(f"  {'PASS' if base_ok else 'FAIL'}  基线：未注入故障时全绿（结果：9 passed）")
    print(f"        退出码={code}")
    results.append(base_ok)
    if not base_ok:
        print(out)

    # 1) pyproject.toml 版本漂移
    def m1():
        p = FILES["pyproject"]
        p.write_text(
            p.read_text(encoding="utf-8").replace('version = "0.116.0"', 'version = "0.117.0"', 1),
            encoding="utf-8",
        )

    results.append(
        case("pyproject.toml 版本漂移 → pyproject 检查必须红", m1, "pyproject.toml == __version__")
    )

    # 2) uv.lock 版本漂移
    def m2():
        p = FILES["uvlock"]
        t = p.read_text(encoding="utf-8")
        t = t.replace(
            'name = "gold-etf-analyzer"\nversion = "0.116.0"',
            'name = "gold-etf-analyzer"\nversion = "0.117.0"',
            1,
        )
        p.write_text(t, encoding="utf-8")

    results.append(case("uv.lock 版本漂移 → uv.lock 检查必须红", m2, "uv.lock == __version__"))

    # 3) sw.js VERSION 漂移
    def m3():
        p = FILES["sw"]
        p.write_text(
            p.read_text(encoding="utf-8").replace(
                'const VERSION = "v0.116.0"', 'const VERSION = "v0.117.0"', 1
            ),
            encoding="utf-8",
        )

    results.append(
        case("sw.js VERSION 漂移 → sw.js 检查必须红", m3, "sw.js VERSION == __version__")
    )

    # 4) CHANGELOG 插入重复段（还原 V0.104.0 那个老 bug）
    def m4():
        p = FILES["changelog"]
        t = p.read_text(encoding="utf-8")
        t = t.replace(
            "## [V0.100.0] · 2026-10-18",
            "## [V0.104.0] · 2026-10-19\n\nx\n\n## [V0.100.0] · 2026-10-18",
            1,
        )
        p.write_text(t, encoding="utf-8")

    results.append(case("CHANGELOG 版本段乱序 → 顺序检查必须红", m4, "严格降序"))

    # 5) 删掉当前版本的 release notes
    def m5():
        FILES["note"].unlink()

    results.append(case("当前版本缺 release notes → notes 检查必须红", m5, "release notes"))

    # 6) index.md 去掉当前版本登记
    def m6():
        p = FILES["index"]
        p.write_text(
            p.read_text(encoding="utf-8").replace("v0.116.0.md", "v0.116.0.md.x"), encoding="utf-8"
        )

    results.append(case("index.md 未登记当前版本 → 登记检查必须红", m6, "index.md 登记"))

    # 7) 注释里的假 __version__ 不能被采纳（ast 抗干扰）
    #    正确行为是**保持绿** —— ast 忽略注释，仍读到真实的 0.116.0。
    #    （我第一版把期望写成「必须红」是错的：门禁应当无视注释里的假值。）
    backup7 = {n: pathlib.Path(tempfile.mkdtemp()) / n for n in FILES}
    for n, p in FILES.items():
        shutil.copy2(p, backup7[n])
    try:
        p = FILES["init"]
        t = p.read_text(encoding="utf-8")
        p.write_text('# __version__ = "9.9.9"\n' + t, encoding="utf-8")
        code, out = run_gate()
        green = code == 0
        ignored = "应用版本（src/app/__init__.py） = 0.116.0" in out
        not_fooled = "9.9.9" not in out.split("应用版本")[1].split("\n")[0]
        ok = green and ignored and not_fooled
        print(
            f"  {'PASS' if ok else 'FAIL'}  注释里的假 __version__ 必须被忽略（仍读到 0.116.0，门禁保持绿）"
        )
        print(
            f"        退出码={code}（{'绿' if green else '红 ← 不该红！'}）  仍读到 0.116.0={ignored}"
        )
        results.append(ok)
    finally:
        restore(backup7)

    # 7b) 真把 __version__ 清空 → 必须红
    backup7b = {n: pathlib.Path(tempfile.mkdtemp()) / n for n in FILES}
    for n, p in FILES.items():
        shutil.copy2(p, backup7b[n])
    try:
        p = FILES["init"]
        t = p.read_text(encoding="utf-8")
        p.write_text(t.replace('__version__ = "0.116.0"', '__version__ = ""'), encoding="utf-8")
        code, out = run_gate()
        red = code != 0
        hit = "FAIL" in out
        ok = red and hit
        print(f"  {'PASS' if ok else 'FAIL'}  __version__ 被清空 → 必须红")
        print(f"        退出码={code}（{'红' if red else '绿 ← 假绿！'}）")
        results.append(ok)
    finally:
        restore(backup7b)

    # 8) version-status.md 的基线版本过期 → 必须红
    #    这条断言的作用：单一真源文档一旦发版就会过期，
    #    过期而不报红 = 文档开始撒谎，比没有文档更坏。
    def m8():
        p = FILES["vstatus"]
        t = p.read_text(encoding="utf-8")
        p.write_text(t.replace("基线：V0.116.0", "基线：V0.115.0"), encoding="utf-8")

    results.append(case("version-status.md 基线版本过期 → 基线检查必须红", m8, "基线版本"))

    # 8b) version-status.md 里删掉基线声明 → 必须红
    def m8b():
        p = FILES["vstatus"]
        t = p.read_text(encoding="utf-8")
        p.write_text(t.replace("基线：V0.116.0", "基线："), encoding="utf-8")

    results.append(case("version-status.md 基线声明被抹掉 → 基线检查必须红", m8b, "基线版本"))

    print()
    passed = sum(1 for r in results if r)
    print(f"结果：{passed} passed / {len(results) - passed} failed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
