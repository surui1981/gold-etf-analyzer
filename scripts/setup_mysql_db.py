#!/usr/bin/env python
"""MySQL 初始化脚本（V0.126.0 生产库迁移）：建库 + 建应用账号。

为什么要有这个脚本
------------------
生产库从 SQLite 切到 MySQL 需要**可重复**的建库步骤：库名、字符集、
排序规则、应用账号的权限与认证插件。手工在 ``mysql`` 里敲一遍容易漏，
也没法在别的机器上复现。⇒ 固化成脚本，**建库与建号幂等**（可重跑）。

⚠ **不动服务器全局配置**
------------------------
本脚本**只**建库建号，**不**改 ``default-time-zone`` 等 server 级参数：
这台机器上还跑着别的库（``ruirui_app``），改全局时区会连带影响它们的
``NOW()`` 语义。
⇒ 时区一致性改在**连接层**解决（应用侧 ``init_command`` 把会话时区置成 UTC，
见 ``src/app/repositories/db.py``）—— **这是本项目最容易踩的一个坑**：
SQLite 的 ``CURRENT_TIMESTAMP`` 是 **UTC**，MySQL 的是**会话时区**
（本机 ``time_zone=SYSTEM`` ⇒ **CST / UTC+8**）⇒ 不置会话时区的话，
所有 ``created_at`` 会整体**偏移 8 小时**。

用法
----
    # ① 用管理员凭据建库建号，密码由脚本生成并直接写进 .env.prod（不进 argv）
    sudo python3 scripts/setup_mysql_db.py \
        --admin-defaults /etc/mysql/debian.cnf \
        --db gold_etf --user gold_etf_app \
        --write-env .env.prod

    # ② 只打印要写进 .env.prod 的 DATABASE_URL（不建库；密码交互输入）
    python3 scripts/setup_mysql_db.py --db gold_etf --user gold_etf_app --print-url-only

⚠ **管理员凭据**：``--admin-defaults`` 指向 mysql 客户端的 defaults-file。
⚠ mysql 要求 ``--defaults-file`` 必须是**命令行上的第一个选项** ⇒ 本脚本已处理。
⚠ ``/etc/mysql/debian.cnf`` 是 root-only ⇒ 用它建库得 **sudo 跑本脚本**
（本脚本只用标准库，system python3 即可）。
"""

from __future__ import annotations

import argparse
import getpass
import os
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote_plus

# MySQL 8 的推荐组合：utf8mb4 全 Unicode + 不区分大小写/重音的排序规则
CHARSET = "utf8mb4"
COLLATION = "utf8mb4_0900_ai_ci"

ROOT = Path(__file__).resolve().parents[1]


def _run_mysql(admin_defaults: str | None, sql: str, *, user: str = "root") -> str:
    """跑一段 SQL 并返回 stdout（stderr 直接透传）。

    ⚠ ``--defaults-file`` 必须是**第一个**选项，否则 mysql 会拒绝启动。
    """
    cmd: list[str] = ["mysql"]
    if admin_defaults:
        # ⚠ 必须是**程序名之后的第一个选项**，否则 mysql 拒绝启动
        cmd.append(f"--defaults-file={admin_defaults}")
    else:
        cmd += ["-u", user]
    cmd += ["--batch", "--raw", "--skip-column-names", "-e", sql]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"mysql 退出码 {proc.returncode}")
    return proc.stdout.strip()


def build_url(host: str, port: int, db: str, user: str, password: str) -> str:
    """拼 SQLAlchemy 异步 URL。

    ⚠ 密码里若有 URL 保留字符（@ / : / ? # %）必须百分号编码 ——
    SQLAlchemy 的 URL 解析器会把它们当结构符号。
    """
    return (
        f"mysql+asyncmy://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{db}?charset={CHARSET}"
    )


def _write_env(path: Path, url: str) -> None:
    """把 DATABASE_URL 写进 env 文件（替换已有行；没有则追加）。

    ⚠ 写完把权限收到 600 —— 里面有明文口令。
    """
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    line = f"DATABASE_URL={url}"
    out_lines = []
    replaced = False
    for ln in text.splitlines():
        if ln.strip().startswith("DATABASE_URL="):
            out_lines.append(line)
            replaced = True
        else:
            out_lines.append(ln)
    if not replaced:
        out_lines.append(line)
    path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def main() -> int:
    ap = argparse.ArgumentParser(description="MySQL 建库建号（幂等）")
    ap.add_argument("--db", default="gold_etf", help="数据库名")
    ap.add_argument("--user", default="gold_etf_app", help="应用账号")
    ap.add_argument("--host", default="127.0.0.1", help="应用连接地址（写进 URL）")
    ap.add_argument("--port", type=int, default=3306, help="应用连接端口")
    ap.add_argument(
        "--admin-defaults",
        default=None,
        help="mysql 客户端的 defaults-file（如 /etc/mysql/debian.cnf）—— 管理员凭据来源",
    )
    ap.add_argument("--admin-user", default="root", help="无 defaults-file 时的管理员账号")
    ap.add_argument("--password", default=None, help="应用账号密码（不给则交互读取/生成）")
    ap.add_argument(
        "--gen-password",
        action="store_true",
        help="自动生成随机口令（推荐：口令不经过任何命令行/历史）",
    )
    ap.add_argument(
        "--write-env",
        default=None,
        help="把 DATABASE_URL 写进这个 env 文件（mode 600）",
    )
    ap.add_argument(
        "--print-url-only",
        action="store_true",
        help="只打印 DATABASE_URL，不建库建号",
    )
    args = ap.parse_args()

    if args.password and args.gen_password:
        print("--password 与 --gen-password 互斥", file=sys.stderr)
        return 2

    if args.gen_password:
        pw = secrets.token_urlsafe(24)
    elif args.password:
        pw = args.password
    else:
        pw = getpass.getpass(f"{args.user} 的密码: ")
    if not pw:
        print("密码不能为空", file=sys.stderr)
        return 2

    url = build_url(args.host, args.port, args.db, args.user, pw)
    masked = url.replace(quote_plus(pw), "***")

    if args.print_url_only:
        print(url)
        return 0

    # ① 建库（幂等：IF NOT EXISTS）
    _run_mysql(
        args.admin_defaults,
        f"CREATE DATABASE IF NOT EXISTS `{args.db}` "
        f"DEFAULT CHARACTER SET {CHARSET} DEFAULT COLLATE {COLLATION};",
        user=args.admin_user,
    )
    print(f"[ok] 数据库 `{args.db}` 已就绪（{CHARSET}/{COLLATION}）")

    # ② 建号（幂等：先 DROP 再 CREATE，避免残留的旧口令/插件）
    #    ⚠ 应用账号只用本机（'localhost'）—— 不开放 '%'，不暴露到局域网。
    #    ⚠ caching_sha2_password（8.0 默认，最强）；asyncmy 原生支持。
    esc_user = args.user.replace("'", "''")
    esc_pw = pw.replace("'", "\\'")
    _run_mysql(
        args.admin_defaults,
        f"DROP USER IF EXISTS '{esc_user}'@'localhost';"
        f"CREATE USER '{esc_user}'@'localhost' "
        f"IDENTIFIED WITH caching_sha2_password BY '{esc_pw}';"
        f"GRANT ALL PRIVILEGES ON `{args.db}`.* TO '{esc_user}'@'localhost';"
        f"FLUSH PRIVILEGES;",
        user=args.admin_user,
    )
    print(f"[ok] 账号 '{esc_user}'@'localhost' 已就绪（caching_sha2_password）")

    # ③ 写 env（口令不进 argv、不进 git）
    if args.write_env:
        env_path = Path(args.write_env)
        if not env_path.is_absolute():
            env_path = ROOT / env_path
        _write_env(env_path, url)
        print(f"[ok] DATABASE_URL 已写入 {env_path}（mode 600）")
    else:
        print(f"[ok] DATABASE_URL = {masked}")
        print("     ⚠ 密码请写进 .env.prod（mode 600），不要进 git。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
