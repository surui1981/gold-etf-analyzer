# gold-etf-analyzer · 版本差距分析与改进方向

> 分析日期：**2026-09-27** ｜ 分析对象：`surui1981/gold-etf-analyzer`（Private）
> 本地仓库：`C:\Users\DFCFF\WorkBuddy\2026-08-30-07-53-17\gold-etf-analyzer`
> 分析方法：`git ls-remote`/`git log` 溯源 + 逐条「文档声明 → 代码实证」核验 + 门禁与 CI 实跑

---

## 一、结论速览

**版本差距本身极小，真正的差距在「文档可信度」与「工程债」。**

| 维度 | 结论 |
|------|------|
| **代码版本差距** | 本地 → 远程仅差 **1 个提交**（`4685118`，纯 README 文档），已 fast-forward 同步。**本地 = 远程 = `4685118`，V0.74.0** |
| **功能差距** | **无** —— 无未合并的分支、无待落地代码，功能上完全对齐 |
| **文档可信度差距** | ⚠️ **重要** —— 新提交新增的 V0.75~V0.77 路线章节含 **10 处与代码不符**，其中 **2 个数据表根本不存在**、**2 处 API 命名错误**。若不纠正就进入实施，会直接污染迁移脚本与方案评估 |
| **工程债差距** | ⚠️ **重要** —— `Docker 镜像构建` job 在当前触发配置下**不可达**（全仓 27 个 run 无一是 tag 触发，该 job 结论恒为 `skipped`），**从未真正执行过一次**；CI **无类型检查、无覆盖率**；无障碍「axe-core 0 critical」**没有任何自动化守卫** |
| **门禁状态** | ✅ 全绿（ruff lint 0 / format 174 files / JS 门禁 12 页 + 19 脚本）+ 最近 **2 次 CI 连续 success**（此前连续 8 次 failure） |

**一句话结论**：功能迭代速度（12 个版本主题）已经远超工程配套的建设速度——**广度够了，短板在纵深**。

---

## 二、版本差距明细

### 2.1 同步状态（已处理）

```
本地 HEAD : def5c5c  ←→  远程 main: 4685118   （差 1 个提交）
执行     : git merge --ff-only FETCH_HEAD → Fast-forward
结果     : 本地 = 远程 = 4685118（V0.74.0），工作区干净
```

远程新增的这 1 个提交：

| SHA | 类型 | 内容 | 实际改动文件 |
|-----|------|------|-------------|
| `4685118` | docs | 「V0.74.0 N+18 同步 — README 补齐 + 版本号 0.72.0→0.74.0」 | **仅 `README.md`**（+54/−2） |

> 📌 注意：该提交信息声称改了 `pyproject.toml` / `uv.lock`，但**实际未改**（因为上一提交 `def5c5c` 已完成版本号单源化，无差异可改）。提交信息与实际改动不符，是本次文档漂移的伏笔。

### 2.2 版本演进脉络（V0.64.0 → V0.74.0，11 个版本）

| 版本 | 主题 | 关键产出 |
|------|------|---------|
| V0.64.0 | 多时间框架 | 周/月线聚合 + MA 重算 |
| V0.65.0 | 消息面槽位 | 每日 3 次打分 1:2:3 加权 |
| V0.66.0 | 研判复盘 | T+1/T+3/T+5 命中 + 分值分箱校准 |
| V0.67.0 | 工程基础 | CI/CD + trace_id 全链路 + 价格校验 |
| V0.68.0 | 导航与埋点 | 导航折叠 + ⌘K 命令面板 + telemetry |
| V0.69.0 | 主题与无障碍 | 4 主题 + a11y 扩面 |
| V0.70.0 | 共振 + 克数 | 三色共振信号卡 + 克数持仓 |
| V0.71.0 | 白银 + 回测 | 白银 provider + 权重网格回测 |
| V0.72.0 | 推送 + PWA | Web Push + SMTP + Server酱 + 公开部署 |
| V0.73.0 | i18n + 数据健康 | 简繁英三语 + 数据健康独立页 |
| V0.74.0 | 仪表盘 + 告警规则 | 卡片拖拽持久化 + 告警规则 CRUD |
| — | CI 收口 | ruff lint/format 修复 + 版本号单源化（`def5c5c`） |

### 2.3 标签差距

远程标签曾**止于 `v0.73.0`**、**缺 `v0.74.0`**（而 README / 四份 docs 均已声明 V0.74.0，声明与标签不一致）。→ ✅ **2026-09-27 已补齐**：`v0.74.0` 指向 `798e2c2` 并已推送。⚠️ 但该 tag 推送**未触发任何 CI run**（见 §四 Docker 一节），镜像验证仍未完成。

---

## 三、⚠️ 文档 vs 代码：10 处硬伤（逐条实证）＋ 2026-09-28 补充 7 处

以下均为新提交 `4685118` 在 README「功能拓展路径（V0.74.0 → V0.77.0）」章节（**README 第 212–260 行**）引入。

| # | README 声明 | 代码实际 | 实证位置 | 影响 |
|---|------------|---------|---------|------|
| 1 | `localStorage.pm_dash_layout` | **`pm_dashboard_layout`** | `static/dashboard.js:25` `const LS_KEY = "pm_dashboard_layout";` | 变量名错，调试/迁移时会找错 key |
| 2 | 告警规则类型名 `ThresholdRule / BandCrossRule / WindowRule / CustomRule` | **`VolatilityRule` / `CrossingRule` / `WindowRule` / `TPlusNRule`** | `src/app/schemas/alert.py:81/88/97/104`；discriminator `RuleKind = Literal["volatility","crossing","window","t_plus_n"]`（:25） | 4 个类名错 2 个（仅 `WindowRule` 碰巧正确） |
| 3 | 「数据健康独立页」列为 **V0.74.0 已落地** | 实际是 **V0.73.0 N+16** 的产物 | `git log -- static/data-health.html` → `3aa524b feat(health): … (V0.73.0 N+16)` | 版本归属错误 |
| 4 | V0.75.0 数据隔离：`alert_rules` 表加 `user_id` | **`alert_rules` 不是表**，是 `app_settings` 表里的 **JSON key** | `src/app/services/settings.py:185` `ALERT_RULES_KEY = "alert_rules"` | 迁移方案会写错对象 |
| 5 | V0.75.0 数据隔离：`portfolios` 表 | **代码中完全不存在**（「账本」的真实表名是 **`accounts`**） | `grep -r "portfolios" src/app/models/` 无结果 | ❌ 凭空捏造表名 |
| 6 | V0.75.0 数据隔离：`snapshot_overrides` 表 | **代码中完全不存在** | `grep -r "snapshot_overrides" src/app/` 无结果 | ❌ 凭空捏造表名 |
| 7 | README 顶部链接：ux-roadmap 范围 **「V0.74.0 → V0.77.0」** | `docs/ux-roadmap.md` 自身标题是 **「V0.68.0 → V0.75.0」**，正文只规划到 **V0.75.0**（第 164 行），**无 V0.76/V0.77 章节** | `docs/ux-roadmap.md:1` / `:164` | 新章节自称「冲突时以路线图为准」，而路线图里根本没有 V0.76/V0.77 → **自相矛盾**；同时「文档」小节也同步改成了 V0.77.0 |
| 8 | V0.74.0 整版标 **✅ 已落地** | `ux-roadmap.md` 中 V0.74.0 已标注为 **🟡 部分落地**（③ 打印友好 CSS + 一键 PDF 导出**未做**） | `docs/ux-roadmap.md:149` 起的落地注记 | 两文档直接冲突；且 V0.76.0 说「复用 V0.74.0 的打印 CSS」——**该 CSS 并不存在**（仅 `portfolio.html` 有 `@media print` 隐藏拖拽控制条），依赖前提不成立 |
| 9 | 「**测试覆盖率**」小节 → 内容写「728 用例 / 684 离线通过」 | 项目**无任何覆盖率工具与配置**（`pyproject.toml` 无 coverage/pytest-cov，CI 无 `--cov`） | `grep -n "coverage" pyproject.toml` → 空 | 概念误用：把「测试规模」当「覆盖率」。真实覆盖率**当前不可知** |
| 10 | 「无障碍 — axe-core 0 critical **守住**」 | 仓库中**无任何 axe-core 相关文件/测试**（`grep -rln axe tests/ static/ package.json` → 空） | 同上 | 「守住」无自动化守卫，是口头承诺 |

> **共性根因**：`docs/feature-alignment.md` 已建立「README ↔ 代码 ↔ 文档」三方对账机制，但它**是人工维护的、事后补记的**。新提交在写规划章节时没有做存在性校验，于是出现了「凭空造表名」这类错误。

### 补充（2026-09-28）：清尾时又抓出 7 处同类硬伤

在修正上述 10 处、并新建 `scripts/check_docs_claims.py` 门禁之后，**门禁首跑即抓出 3 处真硬伤**（原 10 处之外）：

| # | 位置 | 文档声明 | 代码实际 | 影响 |
|---|------|---------|---------|------|
| 11 | `README.md:56` 页面导览 | `/static/central-bank.html` | **`central_bank.html`**（下划线） | ❌ 点开即 **404** |
| 12 | `improvement-path.md:236` / `application-guide.md:418` | `localStorage.pm_theme` | **`pm_theme_mode`**（`static/theme.js:15`） | ❌ 主题偏好 key 名不符，照文档调试找不到 |
| 13 | `ux-roadmap.md:123` | 端点列举含 `/api/v1/push/unsubscribe` | 真实只有 **`/api/v1/push/subscribe`**（`POST` 订阅 / `DELETE` 取消） | ⚠️ 端点名不符 |

另有 **4 处「未验证即声称」**：① `application-guide.md` 的 P1#3 把「tag 触发自动构建」标为 ✅ V0.67.0（该 job 从未执行，见 §四）；②③④ 「镜像 1.2GB → 280MB」在 4 处现状陈述中被当作既成事实，而镜像**从未构建过**（实为 Dockerfile 设计目标）。

> 这 7 处已全部修正（提交 `2d64f14`）。**门禁的价值当场兑现**——它们是靠 `scripts/check_docs_claims.py` 首跑发现的，不是人工复核。

---

## 四、工程债盘点（量化）

### 4.1 门禁现状（全绿 ✅）

| 门禁 | 命令 | 实测结果 |
|------|------|---------|
| 静态检查 | `ruff check src tests` | **All checks passed** |
| 格式 | `ruff format --check src tests` | **174 files already formatted** |
| 前端 JS | `python scripts/check_static_js.py` | **12 静态页 + 19 共享脚本全部通过** |
| 离线回归 | `pytest --ignore=…irfcl --ignore=…h15` | **684 passed / 0 failed**（728 收集 − 44 联网） |

### 4.2 CI 覆盖缺口

| 缺口 | 现状 | 风险 |
|------|------|------|
| **Docker 镜像从未验证** | `ci.yml` 的 `on.push` **只声明了 `branches: [main]`，未声明 `tags`**；按 GitHub 语义「若只定义 `branches` 或只定义 `tags`，则未定义的那类 ref 不会触发本 workflow」→ **tag push 不触发 CI**。而 `docker multi-stage build` job 的条件是 `if: startsWith(github.ref, 'refs/tags/v')` → **该 job 永远不可达**。<br>**实证**：全仓 `total_count=27` 个 run，`head_branch` **全部为 `main`，0 个 tag 触发**；docker job 在每个 run 中结论**恒为 `skipped`**（如 run `35732037933`，2026-09-22，main 分支，docker job = skipped）。 | 镜像是否可构建、能否 dry-run 启动，**至今未知**。V0.72.0 P3-b 声称的「tag 推送时构建多阶段镜像并 dry-run 启动验证」**一次都没跑过** |
| **无类型检查** | 无 `mypy` / `pyright` 配置，CI 无该步 | 项目已写了大量类型注解（`powertrain` 级别的收益被浪费）；重构时 `str | None` 类错误无拦截 |
| **无覆盖率** | 无 `pytest-cov` | 无法回答「改哪里安全」，也无法设「新代码必须带测试」的量化红线 |
| **无障碍无守卫** | 无 axe-core | 拖拽 / 模态等新交互的键盘可操作性是人工承诺 |
| nightly 联网回归 | `ci.yml` 注释写「由 main 分支 nightly job 单独跑（TODO V0.67.x）」 | 44 个联网 fetcher 用例在 CI 中**长期不跑**，行情源接口变更无法及时暴露 |

### 4.3 CI 稳定性（已改善）

```
6741707 → e861175 → c091f75 → c1e96ae → 0b4c87d → 3aa524b → 0f74be0 → cb94da5   连续 8 次 failure
def5c5c (修复提交)                                                                success ✅
4685118 (docs sync)                                                               success ✅
```

### 4.4 前端无构建步骤的技术债（量化）

前端 = 静态 HTML + 内联 `<script>`，**无构建/无打包/无 tree-shaking**：

| 指标 | 数值 |
|------|------|
| HTML 总量 | 6,311 行 |
| **内联 JS** | **3,581 行（占 HTML 的 56.7%）** |
| 外部共享 JS | 3,974 行（16 个顶层文件） |
| **前端 JS 总计** | **7,555 行** —— 已达后端（16,752 行）的 **45%** |
| 最重的页 | `portfolio.html`：1,386 行 HTML 中 **1,013 行内联 JS（73.1%）** |
| 内联 `<script>` 标签数 | 138 个 |

> 风险：内联 JS 无法被 ESLint 静态分析（当前门禁只做 `node --check` 语法 + 未定义函数 + DOM id 三项），**`portfolio.html` 一个页面就有 1,013 行无 lint 覆盖的命令式代码**。

### 4.5 代码与测试规模

| 项 | 数值 |
|----|------|
| 后端 | 108 个 `.py` / 16,752 行 |
| 测试 | 59 个 `test_*.py` / 13,058 行（含 `conftest.py` 等辅助文件；测试:源码 ≈ **0.78 : 1**，比例健康） |
| REST | 61 路径 / 70 个操作；`/api/v1/market` 独占 14 个 |
| i18n | zh-CN **699** / en-US **700** / zh-TW **451** key（zh-TW 覆盖率 **64.5%**） |
| 数据库表 | **11 张**：`accounts` / `analysis_records` / `app_settings` / `central_bank_purchases` / `daily_snapshots` / `gold_price_daily` / `news_scores` / `positions` / `push_subscriptions` / `telemetry_events` / `trade_records` |

---

## 五、改进方向（分级建议）

### 🔴 P0 · 立即处理（1–2 天，低风险高收益）

**P0-1 修正 README 新章节的 10 处技术错误**（§三表格逐条对照）

> ✅ **已完成（2026-09-27，已推送 `798e2c2` + 标签 `v0.74.0`）**：10 处硬伤全部修正；另修 `ux-roadmap.md` 头部「适用版本 V0.67.0」陈旧 → V0.74.0；V0.74.0 表补「打印 CSS + PDF 未落地」行、新增 `🟡 部分落地` 标注档；明确 V0.76/77 为 README 展望、不在路线图内。对账文档新增偏差 **#39** 登记。门禁三连通过（ruff lint 0 / format 174 files / JS 门禁 12 页 + 19 脚本）。
- 把 `ThresholdRule/BandCrossRule/…` 改为真实的 `VolatilityRule/CrossingRule/WindowRule/TPlusNRule`；
- 把 `pm_dash_layout` 改为 `pm_dashboard_layout`；
- 删掉 `portfolios` / `snapshot_overrides` 两个不存在的表，`alert_rules` 改述为「`app_settings` 的 JSON key，需先建模为独立表或 JSON 内多用户维度」；
- 「数据健康独立页」版本归属改为 V0.73.0 N+16；
- ux-roadmap 链接范围与「文档」小节改回 **V0.74.0 → V0.75.0**（或先把 V0.76/V0.77 真正写进路线图，再改链接）；
- V0.74.0 状态从「✅ 已落地」改为「🟡 部分落地（③ 打印/PDF 未做）」；
- 「测试覆盖率」小节改名为「测试规模」，或先引入 `pytest-cov` 后再谈覆盖率；
- 「axe-core 0 critical 守住」改为「**待引入** axe-core 自动化守卫」。

**P0-2 打通 tag → Docker 镜像验证链**（这是唯一「假绿灯」级别的缺陷）

> ✅ **已闭环（2026-09-28）—— 首次真实镜像验证成功，「假绿灯」熄灭**
>
> PAT 更换为含 `workflow` scope 后，`on.push.tags: ['v*']` 与文档门禁步骤随合并提交 `d8f135c`
> 进入 `main`（分支 `ci/enable-tag-trigger` 亦已推送），随后打 `v0.74.0`。**决定性实证**：推送 tag 后
> 立即出现 `head_branch=v0.74.0` 的 run（此前全仓 27 个 run 的 `head_branch` 全为 `main`），
> `docker multi-stage build` 从此真实执行。
>
> **打通后首轮即失败，暴露 4 处镜像缺陷（全部已修）**：
>
> | # | 缺陷 | 症状 | 修复 |
> |---|---|---|---|
> | 1 | **src-layout 构建失败** —— builder 仅 `COPY pyproject.toml README.md` 便 `pip install .`，而 `[tool.setuptools.packages.find] where = ["src"]` 要求 `src/` 在场 | `Build (runtime stage)` 失败：`error in 'egg_base' option: 'src' does not exist or is not a directory` | builder 改为只装依赖，业务代码由 runtime 以 `/app/src` 提供（`8c6f8b2`） |
> | 2 | **容器内 `PROJECT_ROOT` 错位** —— `config.py` / `main.py` 均以 `parents[2]` 推导项目根，若 `app` 从 `/install/app` 载入则算成 `/` | `static/`、`data/`、`alembic.ini`、`migrations/` 全部指向不存在路径；非 root 的 `appuser` 无法写 `/` → 启动失败 | `src` 落至 `/app/src` + `PYTHONPATH=/app/src:/install`；**已用两种目录布局对照实证** |
> | 3 | **运行时缺 `httpx`** —— 仅声明在 dev extra，但 `services/notify.py:17` 是模块级无保护导入 | 导入 `app.services.notify` 即 `ImportError` → 容器启动失败 | 提升为运行时依赖 + 重跑 `uv lock` |
> | 4 | **镜像依赖未走 `uv.lock`（根因）** —— 裸 `pip install` 现场解析版本，与锁文件完全脱钩 | 容器装到 `sqlalchemy 2.1.1`（锁 `2.0.52`，**次版本跃迁**）、`starlette 1.7.0`（锁 `1.6.0`）、`pandas 3.0.6`（锁 `3.0.5`）、`akshare 1.18.97`（锁 `1.18.94`）等 —— 一套**从未被 CI 测试过**的依赖组合 → 启动即崩 | 改用 `uv export --frozen --no-dev --no-emit-project` 从锁文件导出精确版本（`7c96d82`） |
>
> 附带修复：smoke test 原用 `docker run --rm -d`，容器启动即退出会被连带删除、`docker logs`
> 只报 `No such container` —— **失败时零信息**（首轮失败即因此无从定位，全靠推断）；已改为去掉 `--rm`
> + 轮询至多 120s + 无论成败都打印容器日志。另新增此前缺失的 `.dockerignore`
> （原先整个仓库含本地 SQLite 库都被当构建上下文上传）。
>
> **终态**：第三轮构建 `docker multi-stage build` = **success**（`Build (runtime stage)` 与
> `Smoke test` 全部通过），容器 **6s 内健康**（`GET /api/v1/health` → 200），装到的正是锁内版本
> （`sqlalchemy-2.0.52` / `starlette-1.6.0` / `pandas-3.0.5` / `akshare-1.18.94`）；
> py3.11 / py3.12 双矩阵同轮 success。
>
> 经验沉淀：**「门禁从未执行过」不等于「门禁通过」**。此次真正的价值不是修好了一个 job，
> 而是让一条被 `skipped` 掩盖了 20+ 个版本的验证链第一次真正运行 —— 一运行就暴露 4 处缺陷。

**P0-3 建立「文档声明可校验」机制**（根治 §三这类错误）

> ✅ **已完成（2026-09-28，已推送 `2d64f14`）**：`scripts/check_docs_claims.py` 落地并接入 `make check-docs`；扫描 `README.md` + `docs/*.md` 的**数据表名 / `localStorage` key / 静态页 / API 端点**做存在性断言（287 处引用全部校验）。**首跑即抓出 7 处真硬伤**（见 §三 补充）；**负向测试**注入 4 类假声明 → 全部命中、退出码 1，删除后恢复全绿（证明不是「假绿灯」）。规划项由脚本内 `ALLOW` 登记，对账报告 `feature-alignment.md` 整体跳过（它天然引用错误值）。
> ⚠️ **CI 接入未生效**：`ci.yml` 的新增步骤与 `on.push.tags: ['v*']` 同属 workflow 改动，**因 PAT 缺 `workflow` scope 推不上去** → 保存在本地分支 `ci/enable-tag-trigger`（`67de9df` + `7c9ec23`），待解锁后 rebase 到最新 main 一并推送。
新增 `scripts/check_docs_claims.py`，纳入 CI：
- 扫描 `README.md` + `docs/*.md` 中出现的 **`` 反引号包裹的表名 / 文件路径 / 端点路径 / localStorage key / 类名**；
- 对每一项做**存在性断言**（表名比对 `models/*.py` 的 `__tablename__` 清单、路径比对 `Path.exists()`、端点比对 `app.openapi()['paths']`、key 比对 `static/*.js` 字符串）；
- 查不到即失败并打印 `文件:行号`。
> 这一条把「对账」从人工事后补记变成**机制性门禁**，是防止文档再次漂移最划算的投入。

### 🟠 P1 · 短期（1–2 周）

**P1-1 引入类型检查（增量开启，不要一次性全量）**
项目已有大量类型注解，边际收益高。建议 `mypy` 严格模式**只对 `src/app/schemas` + `src/app/services` 开启**，`repositories` / `api` 先设 `ignore_errors`，按季度收窄。CI 加一步 `uv run mypy src/app`。

**P1-2 建立覆盖率基线与增量门禁**
`pytest-cov` 记录当前基线（先测出真实数字），CI 只在 **低于基线** 时失败 —— 避免一次性全红，同时守住「新代码必须带测试」。
> 注意：`--ignore` 静默失效坑同样适用于 `--cov`（路径写错不报错），脚本里要断言覆盖率报告文件确实生成。

**P1-3 前端内联 JS 治理（分三步走）**
1. 把 ESLint（`npx eslint --no-eslintrc` 直跑，**不需要构建步骤**）加到 `check_static_js.py` 之后；
2. 优先外提 `portfolio.html` 的 **1,013 行内联 JS** 到 `static/portfolio.js`（收益最大、风险最低，且已有 `dashboard.js` 先例可循）；
3. 长期引入 Alpine.js/htmx 之类的「无构建」渐进增强方案，替代命令式 DOM 操作。

**P1-4 补 nightly 联网回归 job**
`ci.yml` 自己写了 TODO（V0.67.x）但从未实现。加 `schedule: cron` + 跑那 44 个联网 fetcher 用例，失败只告警不阻塞 —— 这样行情源（akshare / Yahoo / WGC）接口变更能及时暴露。

### 🟢 P2 · 中期（与 V0.75 并行）

**P2-1 先把 V0.75 的「数据隔离」设计做对，再写迁移**
关键决策点（当前路线表述错误，必须先澄清）：
- 真实需要加 `user_id` 的是 **7 张用户行为表**：`accounts` / `positions` / `trade_records` / `news_scores` / `daily_snapshots` / `analysis_records` / `push_subscriptions`（+ `telemetry_events` 视隐私口径）；
- `app_settings` 是**全局单例表**（权重、告警规则都在里面），多用户下必须**拆表或改复合主键**（`key` + `user_id`）——这是本次迁移**最难的一处**，建议单独立项设计；
- `central_bank_purchases` / `gold_price_daily` 是**共享只读行情数据**，**不应**加 `user_id`。

**P2-2 补 V0.74.0 的打印/PDF 欠账**
`portfolio.html` / `trend.html` 补完整 `@media print` 样式（隐藏导航/按钮、展开卡片），再做「月度报告 PDF」。否则 V0.76.0 的 PDF 导出建立在不存在的前提上。

**P2-3 无障碍引入自动化守卫**
Playwright + `@axe-core/playwright` 跑 4–5 个关键页（trend / portfolio / settings / data-health），断言 `critical` 级违规为 0。把「人工守住」变成 CI 项。

**P2-4 多标的扩展先打样再复制**
V0.77.0 的铂金/钯金/原油不要一次上 3 个页面。建议**只做铂金**（`XPT=F`，与白银同走 Yahoo chart v8，provider 抽象大概率可直接复用），验证「图表 + 共振 + 权重按标的独立配置」三件事真的可复用后，再批量复制到钯金/原油。

**P2-5 AI 消息面解读（V0.77.0 的可选项）建议明确降级为「实验特性」**
当前依赖清单**无任何 LLM SDK**（只有 aiosmtplib / pywebpush / cryptography），且项目核心原则是「数据本地化」。建议：默认 `OLLAMA_BASE_URL` + 显式开关 + 结果与人工打分**并列存储且人工可覆盖**，并把「不外发任何用户持仓/账本数据」写进 `.env.example` 注释与 README。

---

## 六、V0.75~V0.77 路线修正版

| 版本 | 原路线表述 | 修正建议 |
|------|-----------|---------|
| **V0.75.0** 多用户登录 + 数据隔离 | 给 `positions / news_scores / alert_rules / portfolios / snapshot_overrides` 加 `user_id` ❌ | 改为「7 张用户行为表加 `user_id`；`app_settings` 全局单例表需**拆表/复合主键改造**（重点难点）；行情类表不加」 |
| **V0.76.0** 数据导入 / 导出 | 「复用 V0.74.0 的打印 CSS」❌（不存在） | 先补打印样式（P2-2），再做 CSV 导入向导 / PDF 月报 / Excel 多 sheet / 备份恢复 GUI。**建议把「券商对账单 CSV 导入」提到最前**——它是用户录入痛点，收益最直接 |
| **V0.77.0** 多标的 + AI 解读 | 一次上铂金/钯金/原油 3 个页面 + LLM 解读 | 先做**铂金单品种打样**验证 provider 与共振抽象可复用；AI 解读标为「实验特性」+ 本地 LLM 优先 |
| **（新增建议）V0.75.5** 工程债偿还 | — | 类型检查 + 覆盖率基线 + ESLint + axe-core + nightly 联网回归 + 文档声明校验脚本。**建议排在多用户登录之前** —— 多用户登录要动 7 张表 + 全局 settings 表，是本项目迄今最大的一次重构，没有这些护栏风险过高 |

---

## 七、下一步行动清单（可直接执行）

| 优先级 | 动作 | 命令 / 位置 | 预估 |
|--------|------|------------|------|
| P0 | ~~修正 README 10 处技术错误~~ | ✅ 已修 11 处并推送（`798e2c2`） | — |
| P0 | ~~`ci.yml` 补 `tags: ['v*']`~~ | ✅ 已推（`d8f135c`），tag 触发已实证生效 | — |
| P0 | ~~打 `v0.74.0` 标签~~ | ✅ 已重指至 `7c96d82`（含 tags 声明）；**首次镜像构建 + smoke test 双 success**，容器 6s 内健康 | — |
| P0 | ~~写 `scripts/check_docs_claims.py` 并接入 CI~~ | ✅ 脚本已落地 + 接入 `make check-docs` **并已进入 CI**（`Documentation claims gate` 步骤，py3.11/3.12 双矩阵跑绿，校验 287 处声明） | — |
| P1 | 增量引入 mypy（先 schemas + services） | `pyproject.toml` + `ci.yml` | 1 d |
| P1 | 引入 pytest-cov 基线 | 同上 | 4 h |
| P1 | 外提 `portfolio.html` 的 1,013 行内联 JS | → `static/portfolio.js` | 1–2 d |
| P1 | 补 nightly 联网回归 job | `ci.yml` | 2 h |
| P2 | 设计 `app_settings` 多用户改造方案 | 设计文档 | 1–2 d |
| P2 | 补 `@media print` + 月度报告 PDF | `portfolio.html` / `trend.html` | 2 d |
| P2 | Playwright + axe-core 门禁 | `tests/test_a11y/` | 1 d |
| P2 | 铂金单品种打样 | `static/platinum.html` + provider | 3 d |

---

## 附：本次核验用到的关键证据命令

```bash
# 版本差距
git ls-remote origin refs/heads/main
git log --oneline def5c5c..FETCH_HEAD

# 表名核验（11 张）
grep -rn '__tablename__' src/app/models/*.py

# alert_rules 真实身份（不是表，是 app_settings 的 key）
grep -n 'ALERT_RULES_KEY' src/app/services/settings.py

# localStorage key
grep -rn 'pm_dash' static/dashboard.js

# 告警规则真实类型名与 discriminator
grep -n 'Literal\|class .*Rule' src/app/schemas/alert.py

# 数据健康页归属版本
git log --oneline --all -- static/data-health.html

# ux-roadmap 真实规划范围（止于 V0.75.0）
grep -n '^### V0\.7' docs/ux-roadmap.md

# Docker job 不可达：验证「0 个 tag 触发的 run」
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://api.github.com/repos/surui1981/gold-etf-analyzer/actions/runs?per_page=100" \
  | python -c "import json,sys;from collections import Counter; \
      print(Counter(r['head_branch'] for r in json.load(sys.stdin)['workflow_runs']))"
# → Counter({'main': 27})  ← 无任何 v0.x 触发，docker job 恒为 skipped

# 无类型检查 / 无覆盖率 / 无 axe
grep -n 'mypy\|pyright\|coverage' pyproject.toml .github/workflows/ci.yml
grep -rln 'axe' tests/ static/ package.json
```
