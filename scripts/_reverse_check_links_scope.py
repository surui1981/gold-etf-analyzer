#!/usr/bin/env python3
"""反向验证 check_links.py 的两处新增能力（2026-10-24）。

**为什么要有这个脚本**
2026-10-24 之前，死链门禁有两个盲区，两个都不报错：

  ① **根 `CHANGELOG.md` 根本不在扫描范围内** ——
     门禁只扫 `README.md` + `docs/**`。于是 CHANGELOG 里 4 条指向
     不存在的 release notes 的内联死链，在任何门禁下都是绿的。

  ② **link reference definition（`[label]: target`）压根不被检查** ——
     内联链接正则抓不到这种写法。于是 CHANGELOG 底部 5 条坏定义
     （4 条指向不存在的 release notes + 1 条指向 `example.com` 占位 URL）
     同样是绿的。**它们是死链，只是长得不像链接。**

只修实例不修类别 = 缺陷会复发。本脚本证明新能力**真能变红**，且**不误报**。

**做法**：备份 → 注入故障 → 跑门禁 → 断言它红（或绿）→ 还原。
任何一条「注入了故障但门禁仍然全绿」= 这条能力是假绿，必须修。

退出码：0 = 全部通过，1 = 有失败。
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts" / "check_links.py"

CHANGELOG = ROOT / "CHANGELOG.md"
SAMPLE_DOC = ROOT / "docs" / "overview.md"

FILES = {"cl": CHANGELOG, "doc": SAMPLE_DOC}


def run_gate() -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(GATE)], capture_output=True, text=True, cwd=ROOT)
    return p.returncode, p.stdout + p.stderr


def backup_all() -> dict[str, pathlib.Path]:
    bak = {}
    for name, path in FILES.items():
        dest = pathlib.Path(tempfile.mkdtemp()) / name
        shutil.copy2(path, dest)
        bak[name] = dest
    return bak


def restore(bak: dict[str, pathlib.Path]) -> None:
    for name, path in FILES.items():
        shutil.copy2(bak[name], path)


def case(label: str, mutate, expect_red: bool, expect_substr: str = "") -> bool:
    """expect_red=True  → 注入了故障，门禁必须红
    expect_red=False → 这是「不该报」的场景，门禁必须保持绿（防误报）"""
    bak = backup_all()
    try:
        mutate()
        code, out = run_gate()
        red = code != 0
        hit = (expect_substr in out) if expect_substr else True
        ok = (red == expect_red) and hit
        if expect_red:
            detail = f"退出码={code}（{'红' if red else '绿 ← 假绿！'}）  命中期望输出={hit}"
        else:
            detail = f"退出码={code}（{'红 ← 误报！' if red else '绿（正确不报）'}）"
        print(f"  {'PASS' if ok else 'FAIL'}  {label}")
        print(f"        {detail}")
        if not ok:
            print("        ---- 门禁输出 ----")
            for ln in out.splitlines():
                print("        " + ln)
            print("        ----------------")
        return ok
    finally:
        restore(bak)


def main() -> int:
    results: list[bool] = []

    # 0) 基线：未注入故障时必须全绿
    code, out = run_gate()
    base_ok = code == 0 and "死链门禁通过" in out
    print(f"  {'PASS' if base_ok else 'FAIL'}  基线：未注入故障时全绿")
    print(f"        退出码={code}")
    results.append(base_ok)
    if not base_ok:
        print(out)

    # 1) 能力①：根 CHANGELOG.md 现在在扫描范围内
    #    ⇒ 在 CHANGELOG 里塞一条死链，门禁必须红
    def m1() -> None:
        with CHANGELOG.open("a", encoding="utf-8") as f:
            f.write("\n[x-ref-dead]: docs/releases/v0.999.9-does-not-exist.md\n")

    results.append(
        case(
            "CHANGELOG.md 里塞死链 → 必须红（证明根 CHANGELOG 已纳入扫描）",
            m1,
            expect_red=True,
            expect_substr="v0.999.9-does-not-exist",
        )
    )

    # 2) 能力②：link reference definition 现在会被检查（就在 CHANGELOG 里）
    def m2() -> None:
        with CHANGELOG.open("a", encoding="utf-8") as f:
            f.write("\n[x-def-dead]: docs/releases/v0.888.8-nope.md\n")

    results.append(
        case(
            "link reference definition 指向不存在的文件 → 必须红",
            m2,
            expect_red=True,
            expect_substr="v0.888.8-nope",
        )
    )

    # 3) 能力②不只对 CHANGELOG 生效：docs/ 下的文档同样要抓
    def m3() -> None:
        with SAMPLE_DOC.open("a", encoding="utf-8") as f:
            f.write("\n[x-def-dead2]: docs/releases/v0.777.7-nope.md\n")

    results.append(
        case(
            "docs/ 下的 link reference definition 死链 → 必须红",
            m3,
            expect_red=True,
            expect_substr="v0.777.7-nope",
        )
    )

    # 4) 内联死链仍要被抓（老能力没被改坏）
    def m4() -> None:
        with SAMPLE_DOC.open("a", encoding="utf-8") as f:
            f.write("\n[x-inline-dead](docs/releases/v0.666.6-nope.md)\n")

    results.append(
        case(
            "内联死链仍被抓（老能力未回退）",
            m4,
            expect_red=True,
            expect_substr="v0.666.6-nope",
        )
    )

    # 5) 防误报：代码块里的 `[label]: target` 只是示例文字，**不该**报红
    def m5() -> None:
        with SAMPLE_DOC.open("a", encoding="utf-8") as f:
            f.write(
                "\n```markdown\n[example-label]: docs/releases/v0.555.5-not-a-real-link.md\n```\n"
            )

    results.append(
        case(
            "代码块里的 link reference definition → 必须保持绿（防误报）",
            m5,
            expect_red=False,
        )
    )

    # 6) 防误报：外部 URL 的定义不该被查
    def m6() -> None:
        with SAMPLE_DOC.open("a", encoding="utf-8") as f:
            f.write("\n[ext-label]: https://example.com/some/compare/page\n")

    results.append(
        case(
            "外部 URL 的 link reference definition → 必须保持绿（防误报）",
            m6,
            expect_red=False,
        )
    )

    print()
    passed = sum(1 for r in results if r)
    print(f"结果：{passed} passed / {len(results) - passed} failed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
