# 文档导航

> **目标读者**：所有人（这是 docs/ 的入口）｜ **最近更新**：2026-10-21
>
> 本文件回答两个问题：**"我要找 X，该打开哪个文件？"** 和 **"这个文件还算不算数？"**。
> 其余文档一律不再重复回答这两个问题。

---

## 一、按"我要做什么"找

| 我想… | 打开 |
|-------|-------|
| 了解这个项目能干什么 | [overview.md](overview.md) |
| 第一次跑起来 | [getting-started.md](getting-started.md) |
| 部署 / 升级 / 排查线上 | [deployment.md](deployment.md) |
| 改代码、加功能 | [development.md](development.md) |
| 理解模块划分与数据源 | [architecture.md](architecture.md) |
| 查接口字段与返回结构 | [api-reference.md](api-reference.md) |
| **调评估参数 / 加新参数** | [parameter-evaluation.md](parameter-evaluation.md) |
| **调权重（前端可改的那部分）** | 应用内 `/weights` 页 → [api-reference.md](api-reference.md) 的 settings 段 |
| 知道"哪个能力是哪个版本加的" | [releases/index.md](releases/index.md) |
| **知道"当前是哪个版本"** | [version-status.md](version-status.md) |
| 查某个版本的实现细节 | [releases/](releases/) 对应的 `vX.Y.Z.md` |
| 知道下一步要做什么 | [roadmap.md](roadmap.md) |
| 了解**某个功能为什么当初这么做** | [reports/](reports/) 历史分析报告 |

---

## 二、目录结构与生命周期

```
docs/
├── README.md               ← 本文件（入口）
│
├── 【当前文档】活跃，随代码一起改
│   ├── overview.md              产品能力概览（刻意不带版本号）
│   ├── getting-started.md       上手
│   ├── architecture.md          模块划分 + 数据源
│   ├── api-reference.md         接口契约
│   ├── development.md           怎么开发
│   ├── deployment.md            怎么部署
│   ├── parameter-evaluation.md  评估参数清单与调参建议
│   ├── version-status.md        应用版本状态（单一真源：现在到底是哪个版本）
│   └── roadmap.md               路线图（唯一权威的"下一步"）
│
├── releases/              48 份 release notes + index.md（能力 × 版本对照）
├── parameter-evaluation/  参数调优的专项报告（逐份带日期与 commit）
└── reports/               阶段性分析报告（历史存档，见该目录 README）
```

**三条边界**（V0.110.0 整理时确立）：

1. **`docs/*.md` 只放当前有效的文档。** 一旦某份文档不再随代码更新，就打上
   `状态：归档` 抬头并移进 `reports/`。`improvement-path.md` / `ux-roadmap.md`
   已在 2026-10-18 做过一次聚类重组，仍留在根目录属过渡态。
2. **`releases/` 与 `parameter-evaluation/` 只增不改。** 已经发出去的版本说明
   不追溯修改；发现写错了就补一份勘误，不改历史。
3. **`reports/` 是"决策链存档"**，记述性内容允许写出当时错误或已废弃的实体名 ——
   这是它被排除在 `check_docs_claims.py` 扫描范围之外的原因（见该脚本 `SKIP_FILES`）。

---

## 三、当前状态与已知待办

| 文档 | 状态 | 备注 |
|------|------|------|
| `roadmap.md` | 活跃 | 历史里程碑表停在 V0.100.0；V0.101–V0.109 已发版但未回填，**待回填** |
| `improvement-path.md` | 归档（2026-10-18 起） | 已并入 `roadmap.md`，仅保留历史 |
| `ux-roadmap.md` | 归档（2026-10-18 起） | 已并入 `roadmap.md`，仅保留历史 |
| `feature-alignment.md` | 活跃（对账报告） | 引用了已删除的 `application-guide.md`，**待清理** |
| `parameter-evaluation.md` | 活跃 | 参数清单完整；建议值章节的基线是 V0.77.2，重估时需按当前代码复核 |

> **为什么归档文档还留在根目录**：`check_docs_claims.py` 的扫描范围是
> `docs/*.md`（非递归）。把归档文档移到子目录虽然能"正确地"退出扫描范围，
> 但也会让它们彻底脱离维护视线。目前保留在根目录 + 打归档抬头，是折中方案。

---

## 四、文档门禁（改文档前先知道会被什么拦）

| 脚本 | 拦什么 | 扫描范围 |
|------|-------|---------|
| `check_docs_claims.py` | 文档里写的**表名 / localStorage key / 静态页 / API 端点**在代码里不存在 | `README.md` + `docs/*.md`（**非递归**） |
| `check_links.py` | 死链 + 锚点失效（含 `[label]: target` 这种**长得不像链接**的 link reference definition）；**以及 release notes 未被 `releases/index.md` 登记** | `README.md` + **根 `CHANGELOG.md`** + `docs/**`（**递归**） |
| `check_version_sync.py` | 4 处版本号不一致；CHANGELOG 版本段乱序/重复；当前版本缺 notes 或未登记；**`version-status.md` 基线过期** | 版本文件 + CHANGELOG + `docs/releases/index.md` + `docs/version-status.md` |
| `check_routes.py` | 路由与文档双向验证 | 运行时 |

**三条踩过的坑**：

- 归档文档被 `check_docs_claims.py` 扫描 → 里面记述的旧实体名会报红。
  解法是把它们移到子目录，而不是删。
- **在 markdown 里写正则字面量** → `check_links.py` 的 `LINK_RE` 会把
  "左方括号 + 圆括号"当成链接。必须用 fenced code block **且**把捕获组
  `( … )` 改成非捕获组 `(?: … )`。参见 [releases/v0.87.0.md](releases/v0.87.0.md) §三·1。
- **门禁只做存在性断言**，不校验版本号、测试数、日期。文档写"基于 V0.79.0"
  而代码已到 V0.110.0，没有任何脚本会报红 —— 这类"内容腐化"只能靠人工复核。

---

## 五、写作约定

- **抬头三行**：`# 标题` + `> **目标读者**：… ｜ **状态**：活跃/归档 ｜ **最近更新**：YYYY-MM-DD`。
- **当前文档不带版本号**，版本号只出现在 `releases/index.md` 与 `CHANGELOG.md`。
  - **唯一例外**：`version-status.md` —— 它**就是**讲版本号的，所以必须带。
    为防它悄悄过期，`check_version_sync.py` 会校验它声明的基线 == 应用版本，
    **发版时忘了更新它，门禁立刻变红**。
- **能力首次落地**才登记进 `releases/index.md`；同一能力的后续小修不登记。
- 文件名：release notes 用 `vX.Y.Z.md`（与 git tag 一致）；其余用英文 kebab-case。