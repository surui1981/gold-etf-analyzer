# API 参考与核心模型

> 本指南已拆分为 5 部分，本文件包含 **API 参考（§5）+ 核心模型（§6）**。
> 其他部分：[overview](overview.md) · [getting-started](getting-started.md) ·
> [architecture](architecture.md) · [development](development.md)
>
> 完整索引见 [application-guide.md](application-guide.md)。

## 5. API 参考

| 方法 | 路径 | 说明 | 关键参数 |
|------|------|------|----------|
| GET | `/` | 趋势追踪页 | - |
| GET | `/portfolio` | 个人交易跟踪与购买决策页 | - |
| GET | `/weights` | 评估权重配置页 | - |
| GET | `/news` | 消息面评估页 | - |
| GET | `/central-bank` | **世界央行购金统计页** | - |
| GET | `/trades` | **交易历史查询页** | - |
| GET | `/login` | **登录 / 注册页（307 跳 `/static/login.html`，V0.75.0）** | - |
| GET | `/api/v1/health` | 健康检查 | - |
| GET | `/api/v1/market/health` | 数据源健康度统计 | - |
| GET | `/api/v1/market/freshness` | 三市场数据时效与交易时段 | - |
| POST | `/api/v1/analysis/opportunity` | 宏观机会评分 | body: `factors{dxy, us10y_yield, real_rate, inflation_expectation, risk_off}` |
| GET | `/api/v1/analysis/history` | 历史分析记录 | `limit`(1-100) |
| GET | `/api/v1/market/gold` | 黄金ETF最新报价 | - |
| GET | `/api/v1/market/gold/trend` | 趋势追踪 + 评估指数（**默认纽约金 COMEX 为投资指引基准**） | `days`(20-750)、`target`(ny/etf/gram，默认 ny)、`interval`(D/W/M，默认 D) |
| GET | `/api/v1/market/gold/ny-trend` | 纽约金 60 天趋势曲线（美元/盎司，等价于 `/gold/trend?target=ny`） | `days`(20-750)、`interval`(D/W/M，默认 D) |
| GET | `/api/v1/market/gold/compare` | ETF vs 黄金克价对照（points 含真实价 `etf_price`/`gram_price` + 归一化 `etf`/`gram`） | `days`(20-250) |
| GET | `/api/v1/market/gold/etf-quote` | **黄金ETF报价（元/份，估值与交易专用口径）** | - |
| GET | `/api/v1/market/gold/gram-quote` | **上海金 Au99.99 克价（元/克，P2 #8 V0.70.0）** | - |
| GET | `/api/v1/market/silver/quote` | **纽约白银 SI 报价（美元/盎司，P3-a P2 #11 V0.71.0）** | - |
| GET | `/api/v1/market/silver/etf-quote` | **白银 ETF 562800 报价（元/份，P3-a P2 #11 V0.71.0）** | - |
| GET | `/api/v1/market/silver/trend` | **白银 ETF 趋势追踪 + 评估指数（P3-a P2 #11 V0.71.0）** | `days`(20-750)、`interval`(D/W/M) |
| GET | `/api/v1/market/silver/ny-trend` | **纽约白银趋势曲线（美元/盎司，P3-a P2 #11 V0.71.0）** | `days`(20-750)、`interval`(D/W/M) |
| GET | `/api/v1/market/silver/compare` | **白银 ETF vs 纽约白银 对照（归一化，P3-a P2 #11 V0.71.0）** | `days`(20-250) |
| POST | `/api/v1/backtest/run` | **参数回测（权重网格 × 阈值带 → Sharpe/最大回撤/命中率，5 分钟节流，P3-a P2 #10 V0.71.0）** | body: `BacktestRequestIn`（days/target/weight_grid/threshold_bands）；header: `X-Backtest-Cached: true\|false` |
| GET | `/api/v1/backtest/coverage` | **回测数据覆盖期报告（start/end/available_days/sample_warning，P3-a P2 #10 V0.71.0）** | `target`(ny/etf/gram/silver_ny/silver_etf)、`days`(20-365) |
| GET | `/api/v1/backtest/config` | **回测预设配置读取（settings 表 key=backtest_config，60s 缓存，P3-a P2 #10 V0.71.0）** | - |
| PUT | `/api/v1/backtest/config` | **回测预设配置保存（P3-a P2 #10 V0.71.0）** | body: `BacktestConfigIn` |
| POST | `/api/v1/positions` | 开仓买入 | body: `{symbol, quantity, price, fee}`；query: `account_id`（缺省=默认账本） |
| GET | `/api/v1/positions` | 持仓列表（实时盈亏） | `include_closed`、`account_id`（缺省=全部账本） |
| GET | `/api/v1/positions/export` | 持仓 + 流水 CSV 导出 | `account_id` |
| POST | `/api/v1/positions/{id}/trades` | 加仓/减仓 | body: `{side, quantity, price}` |
| POST | `/api/v1/positions/{id}/close` | 按市价清仓 | - |
| DELETE | `/api/v1/positions/{id}` | 软删除持仓（可撤销） | - |
| POST | `/api/v1/positions/{id}/restore` | 撤销软删除 | - |
| GET | `/api/v1/positions/{id}/trades` | 某持仓成交流水（倒序） | - |
| GET | `/api/v1/portfolio/equity-curve` | **账户收益曲线（流水+历史价回放，含最大回撤）** | `days`(20-250)、`account_id` |
| GET | `/api/v1/portfolio/performance` | **获利分析总结（已实现/浮动盈亏、胜率、盈亏比 + 中文总结）** | `account_id` |
| GET | `/api/v1/accounts` | 账本清单（含持仓/流水统计） | query: `include_archived` |
| POST | `/api/v1/accounts` | 新建账本 | body: `{name, note, is_default}` |
| PATCH | `/api/v1/accounts/{id}` | 改名 / 备注 / 排序 / 设为默认 | body: `{name?, note?, sort_order?, is_default?}` |
| POST | `/api/v1/accounts/{id}/archive` | 归档账本（数据保留） | - |
| POST | `/api/v1/accounts/{id}/restore` | 恢复已归档账本 | - |
| GET | `/api/v1/trades` | 交易历史查询（分页 + 汇总） | query: `account_id/side/position_id/symbol/keyword/start/end/page/page_size` |
| GET | `/api/v1/trades/export` | 交易历史 CSV 导出（含汇总） | 同上（无分页） |
| GET | `/api/v1/decision/etf` | 购买决策（趋势指数×持仓 + 仓位推荐 + 红绿理由） | `days`(20-250)、`account_id` |
| GET/PUT | `/api/v1/settings/weights` | 权重配置读取/保存 | body: `{tech, macro, news}` 等 |
| GET/PUT | `/api/v1/news-score` | 消息面打分（客户评估；当日 3 槽位 + 加权有效分值） | body: `{score, notes, slot?, basis?, review_note?, score_date?}` |
| DELETE | `/api/v1/news-score/{slot}` | 撤销当日某一次打分（释放槽位） | `score_date`（可选，默认当日） |
| GET | `/api/v1/news-score/history` | 历史打分记录（跨日回看） | `limit`(1-100) |
| POST | `/api/v1/snapshots/capture` | 捕获当日评估快照 | - |
| GET | `/api/v1/snapshots` | 历史评估快照（自动补当日） | `limit` |
| GET | `/api/v1/central-bank/summary` | **央行购金摘要（T12M 总量 / 参与国数 / 最新季度）** | - |
| GET | `/api/v1/central-bank/top-buyers` | **某年度 Top N 买家** | `year`(2020-2030)、`limit`(1-20) |
| GET | `/api/v1/central-bank/purchases` | **央行购金明细（按国家 / 季度范围筛选）** | `from_q`、`to_q`、`country` |
| GET | `/api/v1/review/meta` | **复盘元信息（标的 / 判定窗口 / 12 个依据标签 / 价格日历覆盖）** | `target`(ny/etf/gram，默认 ny) |
| GET | `/api/v1/review/journal` | **研判日志（按日期倒序：基准收盘 → T+N 收盘 + 命中判定）** | `days`(1-365)、`horizon`(1/3/5)、`target` |
| GET | `/api/v1/review/stats` | **复盘统计（命中率 / 方向分组 / 窗口分组 / 分值分箱校准 / 标签胜率）** | `days`(1-730)、`horizon`、`target` |
| GET | `/api/v1/review/hint` | **打分校准提示（该分值区间历史命中率与上涨概率）** | `score`(0-100)、`days`、`target` |
| GET | `/api/v1/review/horizons` | 可用判定窗口（T+1 / T+3 / T+5）与默认值 | - |
| POST | `/api/v1/review/backfill` | **回填历史金价日历（幂等，建立对比基准）** | `days`(5-730)、`target` |
| GET | `/api/v1/resonance/signal` | **当日共振信号（4 类 + confidence 0-100，P2 #7 V0.70.0；V0.75.1 起支持 `target` 切换黄金/白银口径）** | `target`（`ny`/`etf`/`gram`/`silver_etf`/`silver_ny`/`silver_gram`，默认 `etf`，非法值 422） |
| GET | `/api/v1/resonance/history` | **共振信号历史回放（按日期倒序）** | `days`(1-365) |
| GET | `/api/v1/resonance/strength-up` | **STRONG_UP 命中率统计（样本<20 时 sample_warning=true）** | `days`(1-730)、`horizon`(1-30) |
| GET | `/api/v1/settings/alert-rules` | **告警规则读取（P3-b #15 V0.72.0）** | - |
| PUT | `/api/v1/settings/alert-rules` | **告警规则保存（PUT admin 守卫；channel 至少 1 项 + 不重复；波动阈值 0.1-20）** | body: `{level_crossing_enabled, volatility_enabled, volatility_pct, quiet_hours:{start,end}, channels:[]}` |
| POST | `/api/v1/settings/test-email` | **测试邮件发送（admin 守卫；dev 模式无 ADMIN_TOKEN 时 skip；返回 `{channel,success,message}`）** | - |
| POST | `/api/v1/settings/test-wechat` | **测试微信发送（admin 守卫；Server 酱 SendKey 验证）** | - |
| GET | `/api/v1/push/vapid-public-key` | **VAPID 公钥（首次自动生成 EC P-256 持久化到 app_settings，P3-b #15 V0.72.0）** | - |
| POST | `/api/v1/push/subscribe` | **Web Push 订阅 upsert by endpoint（push_subscriptions 表，P3-b #15 V0.72.0）** | body: `{endpoint, keys:{p256dh,auth}, user_agent?}` |
| DELETE | `/api/v1/push/subscribe` | **退订（按 endpoint 硬删）** | query: `endpoint` |
| POST | `/api/v1/push/test` | **管理员测试 push 推送（admin 守卫）** | - |
| GET | `/api/v1/auth/status` | **认证状态（公开；`{auth_enabled, allow_registration, authenticated, user?}`，V0.75.0）** | - |
| POST | `/api/v1/auth/register` | **注册并直接登录（首个用户自动成为 `owner`；受 `ALLOW_REGISTRATION` 约束）** | body: `{email, password, display_name?}` |
| POST | `/api/v1/auth/login` | **登录（签发 `pm_session` HttpOnly cookie + `pm_csrf` 可读 cookie）** | body: `{email, password}` |
| POST | `/api/v1/auth/logout` | **登出（幂等；撤销当前会话并清 cookie，无需先登录）** | - |
| GET | `/api/v1/auth/me` | **当前登录用户（未登录 401）** | - |
| POST | `/api/v1/auth/change-password` | **修改口令（保留当前会话，撤销其余全部会话）** | body: `{current_password, new_password}` |

### 5.1 机会分析示例

```jsonc
// POST /api/v1/analysis/opportunity
{
  "factors": {
    "dxy": 96.0, "us10y_yield": 3.6, "real_rate": 1.4,
    "inflation_expectation": 3.0, "risk_off": 9
  },
  "gold_price_usd": 2350.5
}
// 响应：score 94.5 / window "strong" / signal "bullish"
//       factors[] 每项含 direction（bullish/bearish/neutral）供红绿着色
```

### 5.2 趋势追踪示例

```jsonc
// GET /api/v1/market/gold/trend?days=60&interval=D  （默认 target=ny：纽约金 COMEX；target=etf/gram 返回对应市场；interval=D/W/M 支持多时间框架）
{
  "symbol": "GC", "name": "纽约金COMEX", "unit": "美元/盎司", "days": 60,
  "points": [/* 60 个 {date, close, ma5, ma20, ma40} */],
  "metrics": { /* start/end/change_pct/high/low/ma20/ma40/direction/summary */ },
  "indicators": [ /* 5 个维度 {name, value, score, direction, weight, contribution, detail} */ ],
  "index": { "score": 95.0, "level": "strong_up", "direction": "bullish", "summary": "..." }
}
```

---

## 6. 核心模型

### 6.1 宏观机会评分模型（PM-Evaluator 架构）

| 因子 | 权重 | 与黄金关系 | 友好度100分位 | 友好度0分位 |
|------|------|-----------|--------------|------------|
| 实际利率 | 35% | 强负相关 | 1.5% | 2.5% |
| 美元指数 DXY | 30% | 负相关 | 95 | 105 |
| 美债10Y收益率 | 15% | 负相关 | 3.5% | 4.5% |
| 通胀预期 | 10% | 正相关 | 3.0% | 2.0% |
| 避险情绪 | 10% | 正相关 | 10 | 0 |

- 综合评分 = Σ(因子友好度 × 权重)
- 窗口：`≥70 strong` / `≥55 medium` / `≥40 weak` / `<40 standby`
- 配置位置：`services/scoring.py::FACTOR_RULES`

### 6.2 市场趋势评估追踪指数

| 维度 | 权重 | 评分依据 |
|------|------|----------|
| 结构 | 30% | 均线排列（MA5/20/40 多空）+ MA20 斜率 |
| 动量 | 20% | 近 20 日涨跌幅 |
| 支撑 | 20% | 收盘价相对 MA20/MA40 乖离 |
| 动能 | 15% | RSI(14) |
| 回撤 | 15% | 距区间高点回撤 |

- 指数 = Σ(维度评分 × 权重)，0-100
- 等级：`≥75 强势上升` / `≥55 上升` / `≥45 震荡` / `≥25 下降` / `<25 弱势下降`
- 配置位置：`services/trend.py::TREND_WEIGHTS`

### 6.3 宏观参考指数（综合趋势指数 = 技术面 × 30% + 宏观面 × 40% + 消息面 × 30%）

| 因子 | 权重 | 与黄金关系 | 友好度100分位 | 友好度0分位 |
|------|------|-----------|--------------|------------|
| 美元指数 DXY | 25% | 负相关 | 95 | 105 |
| 美债10Y收益率 | 20% | 负相关 | 3.5% | 4.5% |
| 美债30Y收益率 | 15% | 负相关 | 4.0% | 5.0% |
| VIX恐慌指数 | 15% | 正相关（避险） | 25 | 12 |
| 国际央行购金量 | 25% | 正相关（结构性） | 1200吨/年 | 500吨/年 |

- 宏观参考指数 = Σ(因子友好度 × 权重)，0-100；**随宏观参数动态变化**（美债实时采集 `bond_zh_us_rate`，美元指数/VIX 静态参考值，央行购金为年度数据）
- 综合趋势指数 = 技术面 × 30% + 宏观面 × 40% + 消息面 × 30%（`services/macro.py::TECH_WEIGHT/MACRO_WEIGHT/NEWS_WEIGHT`，用户可在 `/weights` 调整）

### 6.4 告警规则 + Web Push 订阅（V0.72.0）

**alert_rules**（持久化到 `app_settings` 表，key=`alert_rules`；与 weight_config / backtest_config 同表）：

| 字段 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `level_crossing_enabled` | bool | True | 档位穿越告警（BULLISH↔BEARISH 主轴翻转；SIDEWAYS 抖动忽略） |
| `volatility_enabled` | bool | True | 单日波动告警（按 `volatility_pct` 阈值） |
| `volatility_pct` | float (0.1-20) | 3.0 | 波动阈值百分比（绝对值 ≥ 此值触发） |
| `quiet_hours.start` | HH:MM | "22:00" | 静默起始（BJT） |
| `quiet_hours.end` | HH:MM | "07:00" | 静默结束（BJT，跨夜有效） |
| `channels` | list[NotifyChannel] | ["browser"] | 推送渠道偏好（按顺序尝试；至少 1 项 + 不重复） |
| `updated_at` | datetime \| null | — | 上次保存时间（BJT） |

**NotifyChannel**：`"browser" \| "webpush" \| "email" \| "wechat"`（4 选 N，Literal 校验）

**push_subscriptions** 表（迁移 `9e2f4a1b8c7d_push_subscriptions.py`）：

| 列 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | Integer | PK | 自增主键 |
| `endpoint` | String(512) | UNIQUE NOT NULL | FCM / Mozilla 推送端点 URL |
| `p256dh` | Text | NOT NULL | 椭圆曲线公钥（base64url） |
| `auth` | Text | NOT NULL | 认证密钥（base64url） |
| `user_agent` | String(256) | NULL | 订阅时浏览器 UA |
| `created_at` | DateTime(timezone) | DEFAULT CURRENT_TIMESTAMP | 创建时间 |
| `archived_at` | DateTime(timezone) | NULL + INDEX | 410 Gone 时设；查询 `WHERE archived_at IS NULL` 过滤活跃订阅 |

**vapid_keys**（持久化到 `app_settings` 表，key=`vapid_keys`，BaseModel）：
- `private_key`: PEM 编码 EC P-256 私钥（启动时若不存在则自动生成一次）
- `public_key`: base64url 编码的 X962 UncompressedPoint（暴露给前端订阅）

### 6.5 认证与账号体系（V0.75.0 第 ① 步）

> ⚠️ **本版是「认证骨架」**：已具备凭证校验、会话与权限守卫的完整链路，但业务表（持仓 / 账本 / 消息面 / 快照等）**尚未加 `user_id` 列**，因此**尚无数据隔离** —— 能登录进来的人看到的是同一份数据。数据隔离在 V0.75.2 落地，找回密码 + 用户管理在 V0.75.3 落地。

**users** 表（迁移 `d5f81a3c9b47_auth_users_sessions.py`）：

| 列 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | Integer | PK | 自增主键；`LEGACY_USER_ID = 1` 为单用户模式下的隐式主体 |
| `email` | String(255) | UNIQUE + INDEX | 登录名，入库前经 `normalize_email()` 小写 + 去空白 |
| `display_name` | String(64) | NULL | 显示名（顶栏徽章） |
| `password_hash` | String(255) | NOT NULL | **bcrypt**（cost 由 `BCRYPT_COST` 控制，默认 12）；**永不随响应返回** |
| `role` | String(16) | DEFAULT `member` | `owner` / `member`；首个注册用户自动 `owner` |
| `is_active` | Boolean | DEFAULT true | 禁用后无法登录（文案与密码错误完全一致，不泄露账号状态） |
| `created_at` / `updated_at` / `last_login_at` | DateTime | 朴素 UTC | 与 SQLite 存储格式对齐（`utcnow()` / `as_naive_utc()`） |

**sessions** 表（**服务端会话**，可即时撤销）：

| 列 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `id` | String(64) | PK | 不透明令牌 `secrets.token_urlsafe(32)`（43 字符）；**不放 JWT，不存用户信息** |
| `user_id` | Integer | INDEX | 归属用户 |
| `expires_at` | DateTime | INDEX | 过期时刻（`SESSION_TTL_HOURS`，默认 336h = 14 天） |
| `last_seen_at` | DateTime | — | 滑动续期（`SESSION_TOUCH_SECONDS`，默认 300s 内不重复写） |
| `revoked_at` | DateTime | NULL | 撤销时刻；登出 / 改密 / 禁用用户时写入 |
| `user_agent` / `ip` | String | NULL | 审计用 |
| `created_at` | DateTime | — | 签发时刻 |

> 复合索引 `ix_sessions_user_revoked (user_id, revoked_at)` 支撑「用户有效会话列表」与「批量撤销」；**无外键**（与 `push_subscriptions` 理由一致：SQLite 上便于迁移与清理）。

**关键行为约定**

| 项 | 口径 |
|----|----|
| 密码策略 | 长度 ≥ 8、≤ 72 字节（**bcrypt 硬上限，超长直接拒绝而非静默截断**）、非纯数字、不在弱口令黑名单 |
| 登录限流 | 进程内滑动窗口 `LoginThrottle`，`user:<email>` 与 `ip:<ip>` **双维度**；`LOGIN_MAX_ATTEMPTS=5` / 窗口 15min / 锁定 15min；超限返回 429 `login_throttled` |
| 时间攻击缓解 | 账号不存在时仍执行一次等成本的**虚拟哈希**，避免「响应快 = 账号不存在」的侧信道 |
| 会话 Cookie | `pm_session`：`HttpOnly` + `SameSite=Strict` + `Path=/` + `SESSION_COOKIE_SECURE` 可配 |
| CSRF | **双提交**：可读 cookie `pm_csrf` + 请求头 `X-CSRF-Token`，`secrets.compare_digest` 恒时比较；仅校验写方法（POST/PUT/PATCH/DELETE） |
| 中间件顺序 | `CORSMiddleware → RateLimitMiddleware → TraceIdMiddleware → AuthMiddleware → CsrfMiddleware → routes`（**先注册即内层**，故 401/403 响应仍带 CORS 头、审计日志仍带 trace_id、暴力破解先被 per-IP 限流拦下） |
| 单用户兼容 | `AUTH_ENABLED=false`（默认）时两个中间件**读完配置即 return**，不读 cookie、不访问 DB、不 set-cookie → 行为与 V0.74.3 逐字节一致 |
| 公开路径白名单 | `/api/v1/health`、`/api/v1/auth/{status,login,register,logout}`、`/api/v1/telemetry/ingest`（telemetry 需保留匿名上报能力） |
| 文档暴露 | `AUTH_ENABLED=true` 且 `APP_ENV=prod` 时自动关闭 `/docs` / `/redoc` / `/openapi.json` |
| 审计埋点 | `login_success` / `login_fail` / `logout` / `authz_violation` 四类事件进前后端同一白名单 |

### 6.6 首页综合研判结论卡（V0.75.1）

> 设计出发点：**缺的不是数据，是收敛**。首页此前把综合指数 / 三维分值 / 共振类别 / 决策建议 / 建议仓位 / 理由明细平铺在 6 个面板里，用户需要自己横向扫一遍再心算「到底该不该动」。结论卡只做一件事——**把这些原料按决策顺序排成一条线**。

| 口径 | 规则 |
|------|------|
| 三大数据源 | `GET /api/v1/market/gold/trend?days=60&target=` （必需）+ `GET /api/v1/decision/etf?days=60&target=` + `GET /api/v1/resonance/signal?target=`（后两者失败仅降级对应区块，`Promise.allSettled`） |
| 结论行 | 行动建议与置信度**一律取后端 `decision`**（`action` / `action_label` / `confidence` ∈ low·medium·high），前端不自造阈值 |
| 三维分值 | 技术面 30% / 宏观面 40% / 消息面 30%，权重与 `/weights` 页面同源（`index.components`）；红=利多 绿=利空 **且附 ↑↓→ 文字符号**（满足色觉障碍可读性） |
| 一致性判定 | **不在前端重算** —— 直接取 `/api/v1/resonance/signal` 的 `signal`（5 类：`strong_up` / `strong_down` / `weak_up` / `divergent` / `neutral`）。后端阈值 `_THRESH_UP=55` / `_THRESH_DOWN=45`、`confidence = avg × (1 - stdev/55)`。**理由**：若前端另立一套阈值，后端调参后两处口径必然打架 |
| 仓位对照 | 后端 `position_ratio` 恒为 `0`（`services/position.py` 注释「账户本金未知，暂不估算」）→ 卡片**不展示「当前仓位 X%」**，只显示「空仓 / 持有 N 份 · 浮盈浮亏」，避免用 0 编造出「仓位 0%」的假信号 |
| 数据质量折损 | ① 宏观因子中 `source == "静态参考值"` 的项数 / 名称 / 最新数据日（判据用**后端真正写入的字面量**，不能用「非 H.15 即静态」这类启发式——央行购金来源是 `世界黄金协会 GDT Q2 2026`，属正当季度源）；② 消息面 `scored=false` 时提示未打分；③ `trend.degraded=true` 时报出 mock 源市场数。三者都直接扣减「结论可信度」的提示，**如实标注优先于观感统一** |
| 品种切换 | 黄金 `etf` / 白银 `silver_etf`，一次切换使 trend / decision / resonance **三个 target 同步生效**，选择记忆于 `localStorage.pm_synthesis_asset` |
| 刷新 | 60s 轮询 + `inflight` 重入保护（防止慢响应叠加）；`i18n:change` 事件触发重渲染；`aria-live="polite"` 播报结论变化 |
| i18n | 自持 `T(key, fallback)` 包装：缺失 key 时**回落到中文硬编码**（`I18n.t()` 查不到会返回 key 字面量，若不兜底页面上会直接出现 `syn.cons_strong_up` 这种裸 key）；三语各 42 个 `syn.*` 键，并由 2 条门禁守住（脚本引用键三语齐全 + 三语键集合严格一致） |

### 6.7 首页内嵌消息面打分器（V0.76.0）

`static/news-score-widget.js`（IIFE + `window.PM_NewsScore = { mount, load, openSlot, getState }`，自注入 `<style>` 并全部走 `--up/--down/--muted/--accent/--border/--card` 变量 → 4 主题免覆盖），自动挂载到 `trend.html` 的 `#newsScoreCard`（位于 `#synthesisCard` 之下、实时评估摘要之上）。

| 方面 | 说明 |
|------|------|
| 起因 | 消息面占综合评估指数 **30%**，却是三维中唯一**由用户自己产出**的维度。V0.75.1 收敛「今日操作清单」后，首页只剩 `#newsFactor` 一行只读展示 —— 想打一次分必须整页跳到 `/news` |
| 组件构成 | ① **3 槽位状态一览**（分值 / 权重 1:2:3 / 方向 / 提交时刻 / 备注 / 补录标记 + 逐槽「修改」「撤销」）② **当日有效分值** + **后端算式原样展示**（`(1×45 + 2×70) ÷ 3 = 61.7`）③ **内嵌编辑器**（滑杆 + 快捷档位 + 沿用上次 + 方向判定 + 研判备注 + 12 依据标签 + 复盘批注）④ **状态提示条**（未打分 / 还有 N 次 / 三次已用完，三态配色走 `--chip-*-bg/fg/bd`） |
| 接口 | 复用既有 `GET|PUT|DELETE /api/v1/news-score`（**未新增任何端点**，`app.openapi()` 仍为 67 paths / 76 operations）；依据标签取 `GET /api/v1/review/meta` 的 `basis_tags`（失败时回落到内置 6 个标签，不阻塞打分主流程） |
| 口径同源 | 方向阈值（>55 看多 / <45 看空）与当日有效分值 **1:2:3 加权**一律取后端（`services.news.aggregate_slots`，与 `/news`、复盘页同源）；**前端只做展示与提交，绝不重算加权** |
| 保存后刷新 | 派发 `news-score-changed` → `trend.html` 监听后调 `refreshTrendQuotes()` 重算评估口径；同时直接调 `window.PM_Synthesis.load()` 刷新置顶结论卡。**全程不跳页** |
| ⚠️ 数据守门 | 载入既有槽位时**必须回填 `notes` / `basis` / `review_note`**：仓库层 `upsert` 的 UPDATE 分支对 `notes` 与 `basis` 是**硬覆盖**，不回传即被静默清空（2026-09-30 实测确认）；而 `review_note` 写的是 `review_note or existing.review_note` → **空值保留旧值、根本清不掉**（回填它是为了让用户看到真值，**不要**当它是可清空字段） |
| 刻意不轮询 | 打分器含可拖拽滑杆与文本框，定时重渲染会打断输入（滑杆跳回、光标丢失）；分值只因「有人提交」而变，提交后自渲染即可。只读的 `#newsFactor` 仍由首页既有 60s 轮询保持新鲜 |
| 与 `/news` 的关系 | `/news`（563 行）**本版未改动**，仍保留投行参考来源链接 + 跨日历史记录，是「完整详情页」；首页打分器是其**轻量通道**，两处共用同一接口与口径 |
| i18n | 三语各 64 个 `nsw.*` 键，由 2 条门禁守住（从脚本源码反推引用键三语齐全 + 三语键集合严格一致）；同样自持 `T(key, zh)` 中文兜底 |
| 已知边界 | 保存会触发后端 `TrendService.invalidate_for_news()` 让评估缓存失效 → 首页随即重算。**数据源不可达时该重算较慢**（本机 DNS 故障环境下实测 `GET /market/gold/trend` 首次重算 **23.26s**，缓存命中仅 0.017s），正常联网时应为亚秒级 |

---