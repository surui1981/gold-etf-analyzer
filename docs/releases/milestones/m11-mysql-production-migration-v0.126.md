# M11 · 生产库切到 MySQL（V0.126）

> **一句话**：**生产库从 SQLite 正式切到 MySQL 8.0.46** —— 结构 + 历史数据全迁
> （25 张表 / 88 284 行，逐表 SHA-256 校验和一致），停机窗口实测 **30 秒**。
>
> **发版区间**：V0.126.0 ｜ **状态**：活跃（最新里程碑）
> **本文件定位**：把这次迁移的**口径决策**、**踩到的 9 个方言坑**与**留下的运维契约**写成一条可复核的脉络。
> **逐版原始全文**在 git 历史里：`git show v0.126.0:CHANGELOG.md`
> **注意**：本里程碑覆盖到当前版本，**应用当前正在用的版本号以 [../../version-status.md](../../version-status.md) 为准**。

## 〇 一页结论

| 问 | 答 | 依据 |
|---|---|---|
| 生产库现在是什么？ | **MySQL 8.0.46**（`gold_etf` 库，应用账号 `gold_etf_app`） | §一 |
| SQLite 还在吗？ | 在，但**降级为开发/测试库**（`.env` 指向 `data/gold_etf.db`） | §一·3 |
| 迁了多少？ | **25 张表 / 88 284 行**，每张表**行数 + SHA-256 内容校验和**逐项比对一致 | §三 |
| 停机多久？ | **30 秒**（15:11:55 停 → 15:12:25 健康检查通过） | §三·4 |
| 能回滚吗？ | 能 —— SQLite 库文件原样保留 + 一条 `cutover_rollback.sh` | §五 |
| 结构是照谁建的？ | 照**生产 SQLite 的 `sqlite_master`**（**不是** ORM）—— ORM 与生产库有 **42 处差异** | §二·1 |
| 目标库的版本号谁写的？ | 迁移脚本把 SQLite 的 `alembic_version`（`t2u3v4w5x6y`）一并搬过去 | §二·3 |
| MySQL 上还跑 Alembic 吗？ | **不跑** —— `migrations/env.py` 对 MySQL **硬性拒绝** | §二·4 |
| 时间戳会偏 8 小时吗？ | 不会 —— 连接层把**会话时区**钉成 UTC（MySQL 的 `CURRENT_TIMESTAMP` 用会话时区） | §四·1 |
| 外键约束建了吗？ | **没建** —— 生产 SQLite 的 `PRAGMA foreign_keys` 默认关 ⇒ 外键**从来没被执行过** | §二·5 |
| 顺带修掉的另一个真缺陷？ | **COMEX 库存卡的「1 年」变化率恒为「—」** —— **与 MySQL 无关**，是被 2026-11-09 的新观测触发的**时间炸弹**（详见 §三·6） | §三·6 |

---

## 一、决策与目标形态

### 1.1 用户拍板的三件事

| 决策 | 选择 | 影响 |
|---|---|---|
| **目标形态** | **生产库正式切到 MySQL**（不是「留个 MySQL 影子库」） | `.env.prod` 的 `DATABASE_URL` 真的换掉；SQLite 变开发/测试库 |
| **历史数据** | **结构 + 历史数据全迁** | 25 张表全量搬 + 逐表校验和比对；不是「只搬新数据」 |
| **停机窗口** | **可停 5–30 分钟** | 实测只用掉 **30 秒**（远低于预算） |

### 1.2 为什么不是「继续用 SQLite」

| 维度 | SQLite（迁移前） | MySQL（迁移后） |
|---|---|---|
| 写并发 | WAL 模式 + `busy_timeout` 兜着，**并发写会互相阻塞** | 行级锁 + MVCC ⇒ 并发写互不干扰 |
| 数据量 | 单文件已 **37 MB / 8.8 万行**（且 `telemetry_events` 6.2 万行在涨） | 表空间 + InnoDB |
| 备份 | `sqlite3 .backup()`（要停写才有快照） | `mysqldump --single-transaction`（**不停写**的一致性快照） |
| 备份工具 | 两条备份链路各写各的目录（`backup/` vs `backups/`） | 一条链路，读 `.env.prod` 自动分流 |
| 类型系统 | 弱类型（`VARCHAR(3)` 塞 8 字符也不报错） | 严格模式（同一份数据直接报 1406） |

### 1.3 切换后的三库分工

| 库 | URL 来源 | 用途 | 谁跑迁移 |
|---|---|---|---|
| **生产** | `.env.prod` 的 `DATABASE_URL` = `mysql+asyncmy://…` | systemd 跑的线上服务 | `scripts/migrate_sqlite_to_mysql.py`（**不跑 Alembic**） |
| **开发/测试** | `.env` 的 `DATABASE_URL` = `sqlite+aiosqlite:///./data/gold_etf.db` | 本地跑服务、`pytest`、CI | **Alembic**（32 个迁移照旧管 SQLite） |
| **一次性** | `.env.mysql`（0600，gitignore） | 迁移脚本连 MySQL 的凭据 + 切库时的 URL 来源 | — |

⚠ **`.env.mysql` 已在 `.gitignore` 里**（`git status` 不会带出去），密码不进 argv、不进日志。

---

## 二、迁移口径（**结构从哪来**、**边界在哪**）

### 2.1 目标 schema 照**生产 SQLite**，不是照 ORM

生产库的权威结构是「ORM + 32 个 Alembic 迁移 + 若干手工 ALTER」的**叠加结果**，
与 ORM 已有 **42 处差异**（例如 `user_news_favorites.news_source` 在 ORM 里是
`String(32)`、在生产库里还是更早的 `TEXT`）。

⇒ 用 ORM `create_all` 生成 MySQL 结构，等于**顺手改掉 42 处**没人审过的差异。
⇒ `scripts/migrate_sqlite_to_mysql.py` **只认生产 SQLite 的实际结构**
（`sqlite_master` + `PRAGMA table_info`），逐列翻译成 MySQL DDL。

只有 **3 处**例外（`COLUMN_TYPE_OVERRIDES`），且每处都有硬理由：

| 表.列 | 生产 DDL | MySQL 目标 | 为什么必须改 |
|---|---|---|---|
| `user_news_favorites.news_source` | `TEXT` | `VARCHAR(32)` | MySQL 的 UNIQUE **不能**建在 TEXT 上（error 1170） |
| `user_news_favorites.site_name` | `TEXT` | `VARCHAR(64)` | 同上（INDEX 不能建在 TEXT 上） |
| `central_bank_purchases.country_iso` | `VARCHAR(3)` | `VARCHAR(16)` | 库里存着 WGC 全球合计行的伪 ISO `WGC_AGGR`（**8 字符**）⇒ MySQL 严格模式报 1406 |

### 2.2 列类型按「**精度等价**」翻译，不是按名字翻译

| SQLite | MySQL | 为什么 |
|---|---|---|
| `INTEGER` | `BIGINT` | SQLite INTEGER = int64；MySQL `INT` = int32（**溢出**） |
| `FLOAT` / `REAL` | `DOUBLE` | SQLite FLOAT = float64；MySQL `FLOAT` = float32（**静默截断**） |
| `TEXT` | `LONGTEXT` | MySQL `TEXT` 只有 64 KB；`macro_detail` 这类 JSON 会超 |
| `DATETIME` | `DATETIME(6)` | MySQL `DATETIME` 是秒级 ⇒ 微秒被**四舍五入**（整秒都可能差 1） |
| `NUMERIC(p,s)` | `DECIMAL(p,s)` | 同义 |

⚠ MySQL 的 `DOUBLE` 默认 `asdecimal=True` ⇒ 必须显式 `DOUBLE(asdecimal=False)`，
否则 ORM 读回来是 `Decimal` 而不是 `float`。

### 2.3 主键必须是 `AUTO_INCREMENT`

SQLite 里 `id INTEGER NOT NULL, PRIMARY KEY (id)`（表级单列 PK）**是 rowid 别名**
⇒ 插入时 SQLite 自己发 id。而 MySQL 的 `BIGINT PRIMARY KEY` **不发** id
⇒ 应用（ORM 省略 id 插入）会直接撞主键。

⇒ 单列 INTEGER 主键一律翻译成 `BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY`，
并在灌完数据后把 `AUTO_INCREMENT` 拨到 `max(id)+1`。

### 2.4 MySQL 上**不跑 Alembic**

那 32 个迁移是按「**从零建库**」写的，在已有表的库上会「table already exists」报错；
更糟的是**中途失败会留下半迁移的 schema**（前几条 apply、后几条没 apply），
而版本号已推进 ⇒ 再也跑不回来。

⇒ 两道防线：
1. `src/app/main.py::_migrate_db` —— MySQL 分支只做**只读校验**（表齐不齐、
   `alembic_version` 对不对），对不上就**启动失败并说清楚**；
2. `migrations/env.py` —— 检测到 MySQL 直接 `raise RuntimeError`（防有人误跑
   `alembic upgrade`）。

⇒ MySQL 的 `alembic_version` 由迁移脚本**从 SQLite 一起搬过去**（`t2u3v4w5x6y`），
读起来是连续的，但**语义上是「迁移工具维护的」而不是「Alembic 推进的」**。

### 2.5 不建外键约束

生产 SQLite 的 `PRAGMA foreign_keys` **默认关** ⇒ 外键**从来没被真正执行过**
（`ON DELETE CASCADE` 也是空话）。
在 MySQL 里真建外键 = **顺手改语义**：删用户时 MySQL 会因 `RESTRICT` 报 1451，
删会话时会真的级联删消息 —— 这些行为线上**从没发生过**。

⇒ 迁移只搬数据与结构，**不改行为**；要不要在 MySQL 上真正启用外键，是另一件事。

### 2.6 TEXT 列的默认值必须写成表达式

MySQL 报 error **1101**「BLOB/TEXT/JSON 列不能有默认值」⇒
`server_default=""` 全部改成 `DEFAULT ('')`（8.0.13+ 的**带括号表达式**默认值；
SQLite 也接受带括号的常量表达式 ⇒ 两个库通吃）。

---

## 三、迁移执行与验证

### 3.1 三条命令

```bash
python scripts/migrate_sqlite_to_mysql.py --dry-run   # 只打印 DDL 计划（不连 MySQL）
python scripts/migrate_sqlite_to_mysql.py --apply     # 建表 + 灌数据 + 逐表校验
python scripts/migrate_sqlite_to_mysql.py --verify    # 只校验（行数 + 校验和）
python scripts/migrate_sqlite_to_mysql.py --drop-target  # 回滚：删掉 MySQL 侧目标表
```

⚠ `--apply` 会**先 DROP 目标表再重建** ⇒ 跑之前必须停服务（否则目标表被删时
线上正在读它）。

### 3.2 逐表校验：行数 + SHA-256 内容校验和

校验和**按列类型归一化**后再哈希 —— 抹掉「表示差异」但**保留数值差异**：

| 列类型 | 归一化 | 为什么 |
|---|---|---|
| `DATETIME` | `%Y-%m-%d %H:%M:%S.%f` | SQLite 给**字符串**、MySQL 给 `datetime` ⇒ 不归一化就是两个哈希（假红） |
| `DECIMAL` | 按 `scale` 格式化 | MySQL 读回来是 `Decimal`、SQLite 是 `float` |
| `BOOLEAN` | `1` / `0` | SQLite 0/1 ↔ MySQL TINYINT |
| `DOUBLE` | `.9f` | 浮点尾数差 |

⚠ 目标侧用**游标分页**（`WHERE pk > 上一页最后一个 pk`），不用 `OFFSET` ——
`OFFSET` 60 万行那种深翻页是 O(n²)。

### 3.3 实测结果（2026-11-11 生产切换）

```
[schema] 建表 25 张（含索引）
[copy]   25 张表，共 88 284 行
[verify] ✅ 全部表一致（25/25 行数相同 + SHA-256 相同）
```

逐表行数（节选）：

| 表 | 行数 | 表 | 行数 |
|---|---|---|---|
| `telemetry_events` | 61 936 | `daily_macro_factors` | 20 108 |
| `news_feed_items` | 3 584 | `gold_inventory_daily` | 1 247 |
| `ai_messages` | 327 | `daily_money_flow_factors` | 502 |
| `central_bank_purchases` | 147 | `gold_price_daily` | 178 |
| `reports` | 22 | `news_scores` | 36 |
| `daily_snapshots` | 66 | `scoring_daily_wide` | 66 |
| `users` | 1 | `positions` / `trade_records` | 1 / 1 |

### 3.4 停机窗口实测 **30 秒**

| 时刻 | 事件 |
|---|---|
| 15:11:55 | `systemctl stop`（**用 systemd，不用 `pkill`**） |
| 15:11:57 | SQLite 备份完成（`.backup` + `PRAGMA integrity_check` ⇒ ok） |
| 15:12:21 | 迁移 + 25 表校验全部完成 |
| 15:12:21 | `.env.prod` 的 `DATABASE_URL` 换成 MySQL |
| 15:12:25 | 健康检查通过（**第 3 次探测**）⇒ 停机 **30 秒** |

### 3.5 切换后的实测

| 项 | 实测 |
|---|---|
| 启动日志 | `MySQL schema 校验通过：25 张表，alembic_version=t2u3v4w5x6y（迁移工具已写入）` |
| SQLite 专属路径 | `db migrate: dialect=mysql ⇒ 跳过 SQLite 补列` / `跳过 SQLite 索引优化` |
| 写入路径 | `news feed refresh OK: upserted=16 from source=wallstcn`（调度器自动跑，**upsert 在 MySQL 上真的成功**） |
| 行数 | `news_feed_items` 3 584 → **3 600**（+16 新行，与 upsert 计数一致） |
| 时区 | 新行 `fetched_at = 2026-11-11 07:12:54` = **UTC**（日志本地时间 15:12:54 = UTC+8）⇒ **没偏 8 小时** |
| 读接口 | `/api/v1/health` `/reports/latest` `/market/gold/trend` `/market/freshness` `/central-bank/summary` `/favorites/stats` 全 200 |
| **切换后复核**（当日 15:4x 再跑一次 `--verify`） | **21 张表逐表 SHA-256 仍与切换瞬间的 SQLite 快照一致**；**4 张表不同** —— 全部因为**线上调度器在 MySQL 上持续写入**（不是迁移失真）：`gold_inventory_daily` 1 247 → **1 248**（+1 新观测）· `news_feed_items` 3 584 → **3 605**（+21 条新闻）· `telemetry_events` 61 936 → **62 156**（+220 条遥测）· `news_feed_daily` 26 → 26（**行数不变、内容变** ⇒ 每日聚合被调度器重算）。⇒ **迁移保真** 与 **应用在 MySQL 上真的在写** 同时得到验证 |

### 3.6 顺带修掉的另一个真缺陷：**COMEX 库存卡的「1 年」变化率恒为「—」**

切换完成后重跑浏览器门禁，`_verify_home_metals` 报「库存卡 3 条副行都有值」失败
（实得 `["-0.63%", "-2.05%", "—"]`）。**这不是 MySQL 引起的**：

| 步 | 事实 |
|---|---|
| 根因 | 查询窗口被卡在 `latest - 365d` 上，而源是**交易日频**（周末/假日缺行）⇒ 恰好等于 `latest - 365d` 的那天**常常没有观测** ⇒ 基线被挡在窗口**之外** ⇒ `_change` 找不到 `date <= target` 的点 ⇒ 1y 恒为 `None` |
| 触发 | 2026-11-09 调度器写入新的库存观测 ⇒ 回看窗口整体前移 3 天 ⇒ 窗口内最早一条（2025-11-10）比基线目标（2025-11-09）**晚一天** |
| ⚠ 反向验证 | 同一段计算在**迁移前的 SQLite 备份数据**（`data/backups/gold_etf-cutover-20261111-151153.db`）上跑出**同样的 None** ⇒ 与后端无关，纯粹取决于「最新观测日」与「源有没有那一行」 |
| 修法 | 回看窗口多取 **10 天余量**（`BASELINE_TOLERANCE_DAYS`）⇒ 「窗口内最后一个 ≤ target 的观测」能被找到 |
| 实测 | 1y 从「—」变成 `base=2025-11-07 / -39.05%` |
| ⚠ 为什么老单测测不到 | 既有单测用**每天一行**的序列（**没有缺口**）⇒ 这条边界在测试里永远不出现 ⇒ 补了 1 条**带缺口**的回归测试（撤销修复 ⇒ **实测变红**） |

---

## 四、踩到的 9 个方言坑（**每一个都是「静默失败」或「只在生产炸」**）

### 4.1 会话时区：MySQL 的 `CURRENT_TIMESTAMP` 用**会话时区**

SQLite 的 `CURRENT_TIMESTAMP` 是 **UTC**；MySQL 的是**会话时区**
（本机 `time_zone=SYSTEM` ⇒ **CST / UTC+8**）⇒ 不置会话时区的话，所有
`created_at` / `updated_at` 整体**偏移 8 小时**，而且**不报任何错**。

⇒ 连接层 `init_command="SET time_zone='+00:00'"`（**每条连接**建立时生效）。
⚠ **不能改 server 级 `default-time-zone`** —— 这台机器上还跑着别的库（`ruirui_app`），
改全局会连带影响它们的 `NOW()` 语义。

### 4.2 `rowcount` 语义：MySQL 报「**改动**行数」

`INSERT ... ON DUPLICATE KEY UPDATE`：插入=1 / 更新且值变了=**2** / 更新但值没变=**0**；
SQLite 返回「**处理过**的行数」（插入=1 / 更新=1）。

⇒ 打开 `CLIENT_FOUND_ROWS`（MySQL 改为返回「**匹配**行数」）⇒ 与 SQLite 逐点一致。
⚠ **SQLAlchemy 的 asyncmy/aiomysql 方言实现了 `_found_rows_client_flag()` 但基类从不调用它**
（只有 mysqldb 调用）⇒ 必须自己设。

### 4.3 行别名 `new.<col>` 只暴露 **INSERT 列清单里出现过的列**

SQLite 的 `excluded.<col>` **包含**被省略列的默认值；MySQL 的行别名 `new.<col>`
**不含** ⇒ 少一列就是 `error 1054 Unknown column 'new.fetched_at' in 'field list'`。

实测踩坑：`news_feed_items` 的 payload 不带 `fetched_at`（靠列的 `server_default` 补），
而 `update_columns` 里却有它 ⇒ **整个新闻流 upsert 失败**（而且只在跑那行 SQL 时才炸，
不会在启动时炸）。

⇒ 修法在 `repositories/upsert.py::_mysql_update_expressions`：对「payload 里没有、
但要更新」的列，改用该列的**隐式默认值**表达式。
⚠ 回归测试 `tests/test_repositories/test_upsert_dialect.py` **只看编译出来的 SQL**
⇒ 纯离线、秒级、不依赖外部服务 ⇒ CI（只有 SQLite）也能跑。

### 4.4 `VALUES(col)` vs 行别名 `AS new`：SQLAlchemy 会**自己换**

MySQL 8.0.20 起 `VALUES(col)` 官方标为 deprecated ⇒ SQLAlchemy 2.1 在
`server_version_info >= (8,0,20)` 时渲染成 `... AS new ON DUPLICATE KEY UPDATE col = new.col`。

⚠ 这个开关在 `Dialect.initialize()`（真连库时）里才设 ⇒ **离线的 `dialect()` 不会**。
⇒ 离线测试必须手工调 `_initialize_mysql()` 复刻那一步，否则**测的是另一种形态**
（断言会假绿）。

### 4.5 `strftime` 在 MySQL 8.0 上不存在

SQLite 的 `strftime('%Y-%m', col)` ⇒ MySQL 要用 `date_format(col, '%Y-%m')`。
新增 `repositories/sql_expr.py::year_month_expr` 统一封装。

⚠ **同一份表达式必须逐字同时进 `select()` 与 `group_by()`** ——
SQLite 上 `group_by("ym")` 认的是**列名**不是别名 ⇒ 两个库会给出**不同的分组结果**
（一个按别名、一个按字面列名 ⇒ 分组错位或直接报错）。

### 4.6 `sqlite_insert` 在 MySQL 上直接语法错

6 个仓储各自 `from sqlalchemy.dialects.sqlite import insert` ⇒ MySQL 下这行**不是静默降级，
是直接报错**。⇒ 差异收在 `repositories/upsert.py` 一处。

### 4.7 UNIQUE / INDEX 不能建在 TEXT 上（error 1170）

MySQL 的索引键必须有长度 ⇒ 生产里两个 `TEXT` 列（`news_source` / `site_name`）
必须改成 `VARCHAR`（见 §二·1）。

### 4.8 `VARCHAR` 长度在 MySQL 上**真的会被校验**（error 1406）

SQLite **不校验** VARCHAR 长度 ⇒ `country_iso VARCHAR(3)` 装着 8 字符的 `WGC_AGGR`
一路存得好好的。MySQL 严格模式直接报「Data too long」⇒ **整个 `cb_gold` 因子写不进去**。

### 4.9 `TEXT` 列不能有字面量默认值（error 1101）

见 §二·6。

---

## 五、留下的运维契约

### 5.1 回滚路径

| 步骤 | 命令 |
|---|---|
| 回滚脚本 | `bash /tmp/cutover_rollback.sh`（或显式给备份路径） |
| 备份文件 | `data/backups/gold_etf-cutover-20261111-151153.db`（**原样保留**） |
| 回滚动作 | 停服务 → `.env.prod` 切回 SQLite → 用备份覆盖 `data/gold_etf.db` → 起服务 |

⚠ **MySQL 侧的数据没动**（还在那儿）⇒ 切回 MySQL 重跑迁移脚本即可。
⚠ 回滚**不 bump 版本** —— 代码层两个方言都支持，回滚只是改一行配置。

### 5.2 备份链路（两条 ⇒ 现在只剩一条口径）

| 工具 | 入口 | 行为 |
|---|---|---|
| `scripts/daily_backup.sh`（systemd timer，每日 03:00） | 读 `.env.prod` 的 `DATABASE_URL` 前缀自动分流 | SQLite ⇒ `.backup()` + `integrity_check`；MySQL ⇒ `mysqldump --single-transaction` |
| `watchdog.py`（随采集触发） | 同上 | MySQL ⇒ `mysqldump --single-transaction --quick --hex-blob --tz-utc` |

⚠ 两条备份工具此前**各写各的目录**（`data/backup/` vs `data/backups/`）⇒ 同一个库
有两份互不相干的备份，且谁也不知道对方那份还在不在。⇒ **目录名已统一为 `backups`（复数）**。

⚠ 凭据走 **0600 临时 defaults 文件**（`--defaults-extra-file`）⇒ 密码不进 argv
（`ps` 可见）、不进环境变量、不进日志。

### 5.3 MySQL 分支**不**做的事（写进代码，不是写进文档）

| 事 | 在哪被挡住 |
|---|---|
| 跑 Alembic | `migrations/env.py` ⇒ `RuntimeError` |
| `create_all` | `main.py::_migrate_db` 的 MySQL 分支直接 `return` |
| 补列 / 建索引 | `utils/db_migrate.py` 两个入口都先判方言 |
| WAL checkpoint | `main.py::_checkpoint_wal` 对非 SQLite 直接返回 |
| 快照归档直连 sqlite3 | `watchdog.py` 改走 SQLAlchemy（双方言同一份 SQL） |

---

## 六、验证与门禁

### 6.1 本轮跑过的门禁

| 门禁 | 结果 |
|---|---|
| `ruff check src tests scripts` | ✅ 0 |
| `ruff format --check src tests` | ✅ **313** 文件已格式化（CI 口径 `src tests`；含 `scripts/` 是 343） |
| `pytest tests/test_repositories/` | ✅ **334 passed** |
| `pytest tests/test_repositories/test_upsert_dialect.py` | ✅ **5 passed**（含反向验证） |
| `check_pwa_assets` | ✅ SW `v0.126.0` == 应用版本，54 条 SHELL_ASSETS |
| `check_deps` | ✅ `src/` 14 个三方 import 全在 dependencies |
| `check_i18n_keys` | ✅ **0 missing / 582 in-scope** |
| `check_static_js` | ✅ 22 页 + 39 脚本 |
| `check_freshness_consistency` | ✅ PASSED |
| `check_links` | ✅ **31** 份文档 / **446** 条内部链接 + 4 个锚点 |
| `check_version_sync` | ✅ 4 处版本号 + CHANGELOG 降序 + 里程碑登记 + 基线 |
| 浏览器门禁（DB 换了后端 ⇒ 重跑） | ✅ `_verify_nav_8` 27/0 · `_verify_home_report` 49/0 · `_verify_home_verdict` 55/0 · `_verify_home_metals` **39/0（连跑 4 次）** · `_verify_scoring_robust` 8/0 · `_verify_report_archive` 43/0 · `_verify_central_bank_aggregate` 18/0 · `_verify_top20` / `_verify_date_nav` 无失败项 |
| `pytest tests/test_services/test_gold_inventory.py` | ✅ **15 passed**（含 1 条新回归测试） |

### 6.2 ⚠ 反向验证（**每个新断言都要能变红**）

| 断言 | 撤销后必须变红 |
|---|---|
| `test_mysql_upsert_missing_payload_column_uses_default_not_alias` | 把 `_mysql_update_expressions` 改回 `{col: stmt.inserted[col] …}` ⇒ 编译结果里重新出现 `new.fetched_at` ⇒ **已实测变红** |
| `test_mysql_dialect_uses_row_alias_form` | 若 SQLAlchemy 退回 `VALUES(col)` 写法 ⇒ 形态钉不住 ⇒ 其余断言会**假绿** ⇒ 这条专门守它 |

---

## 七、教训（**留给下一个碰数据库的人**）

1. **「SQLite 上能跑」不等于「语义相同」。** SQLite 的宽松（不校验 VARCHAR 长度、
   不执行外键、`excluded` 含默认值、`CURRENT_TIMESTAMP` 是 UTC）**每一条**在 MySQL 上
   都会变成一次**静默失败或只在生产炸**。⇒ 迁移前必须逐条列对方言差异。

2. **生产 schema 的真源是 `sqlite_master`，不是 ORM。** ORM 与生产库有 42 处差异
   ⇒ 用 ORM 生成目标结构 = 顺手改掉 42 处没人审过的东西。

3. **静默失败比崩溃更贵。** 时区偏 8 小时、rowcount 虚高 30%、`VALUES(col)` 换形
   —— 这些**都不报错**，只会让数字悄悄变错。⇒ 每一处都要有**判据**（校验和 / 编译出的 SQL /
   UTC 时间戳 / 行数增量）。

4. **离线测试要复刻生产的初始化。** `Dialect.initialize()` 里设的开关
   （行别名形态）离线 `dialect()` **不会设** ⇒ 测试会测成另一种形态 ⇒ 断言**假绿**。
   ⇒ 离线复刻要连**私有 API** 一起调（改了就直接报错，而不是静默测错）。

5. **MySQL 上别跑 Alembic。** 那 32 个迁移是「从零建库」脚本 ⇒ 已有表的库上会中途失败
   ⇒ 留下**半迁移 schema** 且版本号已推进 ⇒ 再也跑不回来。⇒ 宁可**启动失败并说清楚**，
   也不要「在生产库上顺手修一下」。

6. **外键是行为，不是结构。** 建约束 = 改语义（线上从没发生过的级联删除会真的发生）
   ⇒ 迁移只搬数据与结构，**不改行为**。

---

## 八、版本一览

| 版本 | 主题 | 关键交付 |
|---|---|---|
| **V0.126.0** | 生产库切到 MySQL | 25 张表 / 88 284 行全迁（逐表 SHA-256 一致）· 停机 **30 秒** · 方言无关 upsert 抽象层（3 条不变量）· 双方言引擎（UTC 会话时区 + `CLIENT_FOUND_ROWS` + 连接预检）· MySQL 启动期**只读** schema 校验 + Alembic **硬性拒绝** · TEXT 默认值改表达式式（1101）· `country_iso` 放宽到 VARCHAR(16)（1406）· 迁移工具 + 双方言备份 · **5 条**离线方言回归测试（含反向验证）· 顺带修掉 COMEX 库存「1 年」变化率恒为「—」（§三·6）+ 1 条带缺口的回归测试 |
