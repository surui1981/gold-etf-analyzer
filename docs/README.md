# 文档导航

> **目标读者**：所有人（这是 docs/ 的入口）｜ **最近更新**：2026-11-05
>
> 本文件回答两个问题：**「我要找 X，该打开哪个文件？」** 和 **「这个文件还算不算数？」**。
> 其余文档一律不再重复回答这两个问题。

---

## 一、按「我要做什么」找

| 我想… | 打开 |
|---|---|
| 了解这个项目能干什么 | [overview.md](overview.md) |
| 第一次跑起来 | [getting-started.md](getting-started.md) |
| 部署 / 升级 / 排查线上 | [deployment.md](deployment.md) |
| 改代码、加功能 | [development.md](development.md) |
| 理解模块划分与数据源 | [architecture.md](architecture.md) |
| 查接口字段与返回结构 | [api-reference.md](api-reference.md) |
| **弄懂综合趋势评估指数怎么算的** | [composite-trend-index.md](composite-trend-index.md) |
| **调评估参数 / 加新参数** | [parameter-evaluation.md](parameter-evaluation.md) |
| **调权重（前端可改的那部分）** | 应用内 `/weights` 页 → [api-reference.md](api-reference.md) 的 settings 段 |
| **知道下一步要做什么** | [roadmap.md](roadmap.md) ← **唯一活跃路线** |
| 知道「哪个能力是哪个版本加的」 | [releases/index.md](releases/index.md) |
| **知道「当前是哪个版本」** | [version-status.md](version-status.md) |
| 看**演进脉络**（某个阶段做了什么、为什么这么做） | [releases/milestones/](releases/milestones/) |
| 了解**某个功能为什么当初这么做** | [reports/历史评估汇总-202609.md](reports/历史评估汇总-202609.md) |

---

## 二、目录结构

```
docs/
├── README.md                    ← 本文件（入口）
│
├── 【当前文档】活跃，随代码一起改
│   ├── overview.md              产品能力概览（刻意不带版本号）
│   ├── getting-started.md       上手
│   ├── architecture.md          模块划分 + 数据源
│   ├── api-reference.md         接口契约
│   ├── development.md           怎么开发
│   ├── deployment.md            怎么部署
│   ├── parameter-evaluation.md  评估参数清单与调参建议
│   ├── composite-trend-index.md 综合趋势评估指数：计算方式与主要参考
│   ├── version-status.md        应用版本状态（单一真源：现在到底是哪个版本）
│   └── roadmap.md               路线图（唯一权威的「下一步」，逐条带实测判据）
│
├── releases/
│   ├── index.md                 能力 × 版本对照表（哪个能力哪个版本加的）
│   └── milestones/              7 份里程碑文档（V0.11 → 当前，演进脉络）
│
├── parameter-evaluation/        参数调优的专项报告（逐份带日期与 commit）
└── reports/                     决策链存档（历史评估汇总 + 时点快照）
```

### 三条边界（V0.110.0 确立，V0.120.5 修订）

1. **`docs/*.md` 只放当前有效的文档。** 不再随代码更新的内容，移进 `reports/`。
   V0.120.5 据此**删除**了 5 份互相重叠且基线落后 16–43 个版本的规划文档
   （`improvement-path` / `ux-roadmap` / `roadmap` / `next-steps` / `app-improvement-path` /
   `feature-alignment`），合并成**一份** [roadmap.md](roadmap.md)。
2. **`releases/` 与 `parameter-evaluation/` 只增不改。**
   V0.120.5 起 `releases/` 下**不再有逐版 release notes** ——
   60 份小版本合并为**里程碑文档**（V0.121.0 起共 7 份）；逐版原始全文在 **git 历史**里
   （tag 与原文件名同名：`git show v0.118.0:docs/releases/v0.118.0.md`）。
3. **`reports/` 是「决策链存档」**，记述性内容允许写出当时错误或已废弃的实体名 ——
   这是它被排除在 `check_docs_claims.py` 扫描范围之外的原因（见该脚本 `SKIP_FILES`）。

---

## 三、当前状态与已知待办

| 文档 | 状态 | 备注 |
|------|------|------|
| `roadmap.md` | 活跃 | V0.120.5 重写：合并 6 份旧规划文档并逐条实测复核；V0.121.0 更新为 3 批发版编排（基线 V0.121.0） |
| `releases/milestones/` | 归档 | 7 份里程碑文档，覆盖 V0.11 → 当前（M0–M5 + **M6 可信度修复 V0.121**） |
| `releases/index.md` | 活跃 | 「详情」列现在指向**该能力所属里程碑**（不再是逐版文件） |
| `composite-trend-index.md` | 活跃 | 2026-11-08 新建：综合趋势评估指数的四面加权公式、5+11+6 个因子的打分公式、数据源总表、7 条口径纪律与完整算例 |
| `parameter-evaluation.md` | 活跃 | 参数清单完整；建议值章节的基线是 V0.77.2，重估时需按当前代码复核 |
| `version-status.md` | 活跃 | **发版必更**（`check_version_sync.py` 校验它声明的基线 == 应用版本） |

> **为什么归档文档要移走而不是留在原地**：`check_docs_claims.py` 的扫描范围是
> `docs/*.md`（非递归）—— 留在根目录的归档文档仍会被扫描，
> 里面记述的旧实体名会报红。移到子目录才真正退出扫描范围。

---

## 四、文档门禁（改文档前先知道会被什么拦）

| 脚本 | 拦什么 | 扫描范围 |
|------|-------|---------|
| `check_docs_claims.py` | 文档里写的**表名 / localStorage key / 静态页 / API 端点**在代码里不存在 | `README.md` + `docs/*.md`（**非递归**） |
| `check_links.py` | 死链 + 锚点失效（含 `[label]: target` 这种**长得不像链接**的 link reference definition）；**以及 release notes 未被 `releases/index.md` 登记** | `README.md` + **根 `CHANGELOG.md`** + `docs/**`（**递归**） |
| `check_version_sync.py` | 4 处版本号不一致；CHANGELOG 版本段乱序/重复；当前版本缺发布记录或未登记；**`version-status.md` 基线过期** | 版本文件 + CHANGELOG + `docs/releases/index.md` + `docs/version-status.md` |
| `check_routes.py` | 路由与文档双向验证 | 运行时 |

**四条踩过的坑**：

- 归档文档被 `check_docs_claims.py` 扫描 → 里面记述的旧实体名会报红。
  解法是**移到子目录**，而不是删（删了就没了）。
- **在 markdown 里写正则字面量** → `check_links.py` 的 `LINK_RE` 会把
  「左方括号 + 圆括号」当成链接。必须用 fenced code block **且**把捕获组
  `( … )` 改成非捕获组 `(?: … )`。
- **门禁只做存在性断言**，不校验版本号、测试数、日期。文档写「基于 V0.79.0」
  而代码已到 V0.120.4，没有任何脚本会报红 —— 这类「内容腐化」只能靠人工复核
  （[roadmap.md](roadmap.md) 就是为此在每次合并时逐条实测复核）。
- **`git checkout <commit> -- <path>` 会改索引** —— 做「旧代码对照组」时用它，
  后续 `git add` 会把旧版一起提交。做对照组请用 `git worktree`。

---

## 五、写作约定

- **抬头三行**：`# 标题` + `> **目标读者**：… ｜ **状态**：活跃/归档 ｜ **最近更新**：YYYY-MM-DD`。
- **当前文档不带版本号**，版本号只出现在 `releases/index.md`、`releases/milestones/` 与 `CHANGELOG.md`。
  - **唯一例外**：`version-status.md` —— 它**就是**讲版本号的，所以必须带。
    为防它悄悄过期，`check_version_sync.py` 会校验它声明的基线 == 应用版本，
    **发版时忘了更新它，门禁立刻变红**。
- **能力首次落地**才登记进 `releases/index.md`；同一能力的后续小修不登记。
- 文件名：里程碑文档用 `m<N>-<英文 kebab>-<版本区间>.md`；其余用英文 kebab-case。
