# 黄金价格投资辅助工具 · 说明文档

> 项目名：`gold-etf-analyzer` ｜ 当前版本：**V0.78.2**
> 命题：面向个人黄金投资者（中短期 ETF 波段），三市场对照（纽约金/上海金/黄金ETF）+ 综合趋势评估指数（技术/宏观/消息面）+ 持仓跟踪 + ETF购买决策 + 世界央行购金统计 + 消息面研判复盘 + 多用户账号体系
> 技术栈：FastAPI + Pydantic v2 + SQLAlchemy 2.0 (async) + AKShare + WGC Gold Demand Trends (HTML chart JS) + bcrypt（V0.75.0）
> 仓库：https://github.com/surui1981/gold-etf-analyzer
> 相关文档：[README](../README.md) · [improvement-path（工程路线）](./improvement-path.md) · **[ux-roadmap（应用 / UX 路线，V0.68.0 → V0.78.0）](./ux-roadmap.md)** · [feature-alignment（对账）](./feature-alignment.md)

> **本指南已按内容类别拆分为 5 个独立文件**，请按需打开：

| 文件 | 包含原章节 | 主题 |
|------|------------|------|
| [overview.md](./overview.md) | §1 项目概述 + §2 功能清单 | 产品是什么、有什么功能 |
| [getting-started.md](./getting-started.md) | §4 快速开始 + §8 配置说明 | 怎么把服务跑起来、`.env` 怎么配 |
| [architecture.md](./architecture.md) | §3 技术架构 + §7 数据源 | 分层设计、数据从哪来 |
| [api-reference.md](./api-reference.md) | §5 API 参考 + §6 核心模型 | 怎么调用 API、模型怎么算 |
| [development.md](./development.md) | §9 测试 + §10 版本历史 + §11 下一阶段改进计划 + §12 备注 | 维护者视角：测试与演进 |

> 章节编号 §1–§12 在 5 个新文件中**保持原样**，因此 `feature-alignment.md` 等历史审计记录中的 `§X` / `第 X 章` 引用继续有效。

---

## 章节 → 文件映射（保留章节编号，便于历史引用）

| 原章节 | 主题 | 新文件 |
|--------|------|--------|
| §1 项目概述 | 产品定位、技术栈、命题 | [overview.md](./overview.md) |
| §2 功能清单 | 11 个核心能力 + 页面列表 | [overview.md](./overview.md) |
| §3 技术架构 | 分层结构、目录、数据流 | [architecture.md](./architecture.md) |
| §4 快速开始 | 安装、启动、测试、Docker | [getting-started.md](./getting-started.md) |
| §5 API 参考 | 全部 REST 端点表 | [api-reference.md](./api-reference.md) |
| §6 核心模型 | 评分 / 决策 / 复盘 / 结论卡 等算法 | [api-reference.md](./api-reference.md) |
| §7 数据源 | AKShare / WGC / Mock 兜底 | [architecture.md](./architecture.md) |
| §8 配置说明 | `.env` 模板（认证 / 推送 / 行情源等） | [getting-started.md](./getting-started.md) |
| §9 测试 | 945 用例 / 离线口径 / JS 门禁 / 文档门禁 | [development.md](./development.md) |
| §10 版本历史 | V0.10 → V0.78.0 完整变更 | [development.md](./development.md) |
| §11 下一阶段改进计划 | P0-P3 路线 + UX 6.x 专项 + 状态补遗 | [development.md](./development.md) |
| §12 备注 | 投资声明、能力边界、字段语义澄清 | [development.md](./development.md) |

---

## 快速跳转

- 想**了解产品** → [overview.md](./overview.md)
- 想**跑起来** → [getting-started.md](./getting-started.md)
- 想**调用 API / 看算法** → [api-reference.md](./api-reference.md)
- 想**了解设计、数据源** → [architecture.md](./architecture.md)
- 想**看测试与版本演进** → [development.md](./development.md)
