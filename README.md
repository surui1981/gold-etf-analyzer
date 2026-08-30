# Gold Price Investment Assistant · 黄金价格投资辅助工具

面向**个人黄金投资者**的一站式数据参考平台：汇聚 **纽约金（COMEX）、上海金（Au99.99）、黄金ETF（518880）** 三大市场价格，提供**综合趋势评估指数**（技术面 × 宏观面加权，0-100 量化多空）、个人持仓跟踪与盈亏管理、参数面 × 交易面驱动的 **ETF 购买决策**、以及**每日评估快照**本地历史数据。

延续 PM-Evaluator 的预期评估架构：各因子/维度按典型经验赋权加权评分，输出机会窗口与多空信号（红绿着色，面向客户展示）。

> 📖 完整说明文档（架构 / API 参考 / 核心模型 / 改进计划）：[docs/application-guide.md](docs/application-guide.md)

## 快速开始

### 方式一：本机常驻（推荐）

```bash
# 手动启动（双击运行，窗口保持即可常驻，6 秒后自动打开浏览器）
start_server.bat

# 开机自启（Windows 计划任务，登录时后台启动 + server.log 日志）
# 右键 install_startup.ps1 -> 使用 PowerShell 运行（仅需执行一次）
# 卸载：Unregister-ScheduledTask -TaskName "GoldPriceAssistant" -Confirm:$false
```

### 方式二：命令行 / Docker

```bash
# pip
python -m pip install -e ".[dev]"
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8888

# Docker
docker compose up --build
```

访问：主页 `http://127.0.0.1:8888/` ｜ Swagger `http://127.0.0.1:8888/docs` ｜ 健康 `http://127.0.0.1:8888/api/v1/health`

## 功能清单

| 模块 | 能力 |
|------|------|
| 三市场行情 | 纽约金 / 上海金 / 黄金ETF 实时价格与趋势曲线 |
| 综合趋势指数 | 技术面（5 维度）× 宏观面（5 因子）加权合成 0-100 指数 |
| 宏观参考因子 | 美元指数 / 美债10Y·30Y / VIX / 央行购金，随参数动态变化 |
| 权重配置 | `/weights` 页面调整技术/宏观/合成比权重，指数实时重算 |
| 个人交易跟踪 | 开仓/加仓/减仓/清仓、实时盈亏（SQLite 持久化） |
| 购买决策 | 趋势指数 × 持仓状态 → 买入/加仓/持有/减仓/卖出 + 理由明细 |
| 每日快照 | 每日参数+评估值本地存储（`daily_snapshots`），指数历史序列 |
| 可视化 | 趋势页（指数/曲线/对照/宏观因子/历史）、持仓页、权重页 |

## API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` / `/portfolio` / `/weights` | 趋势追踪 / 持仓决策 / 权重配置 页面 |
| GET | `/api/v1/health` | 健康检查 |
| POST | `/api/v1/analysis/opportunity` | 宏观因子 → 机会评分与窗口 |
| GET | `/api/v1/analysis/history` | 历史分析记录 |
| GET | `/api/v1/market/gold` | 黄金ETF最新报价 |
| GET | `/api/v1/market/gold/trend` | 趋势追踪 + 综合指数 + 宏观因子明细 |
| GET | `/api/v1/market/gold/ny-trend` | 纽约金 60 天曲线（美元/盎司） |
| GET | `/api/v1/market/gold/compare` | ETF vs 上海金 对照 |
| POST | `/api/v1/positions` | 开仓 |
| GET | `/api/v1/positions` | 持仓列表（实时盈亏） |
| POST | `/api/v1/positions/{id}/trades` | 加仓/减仓 |
| POST | `/api/v1/positions/{id}/close` | 清仓 |
| GET | `/api/v1/decision/etf` | 购买决策 |
| GET/PUT | `/api/v1/settings/weights` | 权重配置读取/保存 |
| POST | `/api/v1/snapshots/capture` | 捕获当日快照 |
| GET | `/api/v1/snapshots` | 每日评估历史（自动补当日） |

> 数据源：**AKShare**（新浪 ETF / 东方财富备选 / SGE 上海金 / 英为财情纽约金 / 中债美债收益率），
> 采集失败自动降级内置 Mock / 静态参考值；akshare 调用全局串行（py_mini_racer 兼容）。

## 综合趋势评估指数

```
综合指数 = 技术面评分 × 60% + 宏观参考评分 × 40%（权重可在 /weights 调整）
```

**技术面（5 维度）**：结构 30% / 动量 20% / 支撑 20% / 动能(RSI) 15% / 回撤 15%

**宏观参考（5 因子）**：

| 因子 | 权重 | 与黄金关系 | 100 分位 | 0 分位 |
|------|------|-----------|----------|--------|
| 美元指数 | 25% | 负相关 | 95 | 105 |
| 美债10Y | 20% | 负相关 | 3.5% | 4.5% |
| 美债30Y | 15% | 负相关 | 4.0% | 5.0% |
| VIX | 15% | 正相关（避险） | 25 | 12 |
| 央行购金 | 25% | 正相关（结构性） | 1200吨/年 | 500吨/年 |

等级：`≥75 强势上升` / `≥55 上升` / `≥45 震荡` / `≥25 下降` / `<25 弱势下降`。
权重集中在 `services/macro.py` / `services/trend.py`，可在 `/weights` 页面调整。

## 架构分层

```
gold-etf-analyzer/
├── src/app/
│   ├── main.py              # 入口：路由装配、CORS、lifespan、静态页
│   ├── config.py            # pydantic-settings 配置
│   ├── dependencies.py      # 依赖注入容器
│   ├── models/              # ORM：analysis / position / snapshot / settings
│   ├── schemas/             # Pydantic v2 请求/响应 + 枚举
│   ├── services/            # scoring / trend / macro / decision / position / compare / snapshot / settings
│   ├── repositories/        # analysis / market_data(AKShare) / position / snapshot / settings
│   ├── api/v1/              # health / analysis / market / position / decision / settings / snapshot
│   └── utils/               # 日志
├── static/                  # trend.html / portfolio.html / weights.html
├── tests/                   # pytest（56 用例）
├── start_server.bat         # 本机常驻：手动启动（自动开浏览器）
├── install_startup.ps1      # 本机常驻：注册开机自启计划任务
├── Dockerfile / docker-compose.yml
└── README.md
```

## 测试与代码质量

```bash
python -m pytest -v          # 56 个用例（服务层 + API 集成，不依赖网络）
ruff check src tests
ruff format src tests
```

## 待办 / 优化方向

- [ ] 宏观×技术共振深化：决策引擎纳入宏观机会评分（消息面权重生效）
- [ ] 克数持仓跟踪：实物金/积存金按克持仓，与 ETF 并列盈亏
- [ ] CI/CD（GitHub Actions）+ 每日快照定时任务
- [ ] Alembic 数据库迁移（替代启动时 create_all）
- [ ] 多时间框架（周线/月线）、指数参数回测校准
- [ ] 监控告警：数据源失败告警、价格异动提醒
- [ ] 公开部署：域名 + HTTPS（内部 → 公开发布）

> 完整三阶段改进计划见 [docs/application-guide.md](docs/application-guide.md) 第 11 章。
