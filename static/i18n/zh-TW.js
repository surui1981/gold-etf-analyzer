/*!
 * static/i18n/zh-TW.js — 繁體中文（V0.73.0）
 *
 * 本期最小覆蓋：nav.* + common.* + time.* + brand.* + help.* + theme.*
 * 其餘未翻譯的 key 走 fallback 到 zh-CN（與簡中差異小）。
 */
window.PM_I18N_zh_TW = {
  /* ── 公共 ── */
  "common.save": "儲存",
  "common.cancel": "取消",
  "common.confirm": "確認",
  "common.delete": "刪除",
  "common.edit": "編輯",
  "common.loading": "載入中…",
  "common.error": "出錯了",
  "common.refresh": "重新整理",
  "common.close": "關閉",
  "common.search": "搜尋",
  "common.placeholder_search": "搜尋頁面、動作、時間區間…",
  "common.none": "無",
  "common.yes": "是",
  "common.no": "否",
  "common.all": "全部",
  "common.back": "返回",
  "common.retry": "重試",
  "common.unit_share": "份",
  "common.unit_gram": "克",

  /* ── 頂部導航（10 項）── */
  "nav.trend": "趨勢追蹤",
  "nav.portfolio": "持倉與決策",
  "nav.trades": "交易歷史",
  "nav.weights": "權重配置",
  "nav.news": "消息面評估",
  "nav.review": "研判復盤",
  "nav.central_bank": "央行購金統計",
  "nav.silver": "白銀追蹤",
  "nav.backtest": "參數回測",
  "nav.settings": "通知中心",

  /* ── 時間相對格式 ── */
  "time.just_now": "剛剛",
  "time.minutes_ago": "{n} 分鐘前",
  "time.hours_ago": "{n} 小時前",
  "time.days_ago": "{n} 天前",
  "time.seconds_ago": "{n} 秒前",

  /* ── 說明系統 ── */
  "help.tab_guide": "操作指南",
  "help.tab_glossary": "術語速查",
  "help.tab_source": "資料來源",
  "help.tour_skip": "跳過引導",
  "help.tour_next": "下一步",
  "help.tour_prev": "上一步",
  "help.tour_done": "完成",
  "help.guide_version_title": "版本更新",

  /* ── 品牌 ── */
  "brand.gold": "🏅 黃金價格投資輔助工具",
  "brand.silver": "🪙 白銀價格投資輔助工具",
  "brand.backtest": "⚙️ 參數回測",

  /* ── 主題（V0.69.0）── */
  "theme.light": "淺色模式",
  "theme.dark": "深色模式",
  "theme.auto": "跟隨系統",
  "theme.hc": "高對比度",

  /* ── 警告橫幅（warn.* 共用）── */
  "warn.title": "使用前必讀",
  "warn.b1_strong": "本工具僅供個人研究與輔助決策",
  "warn.b1_rest": "，不構成投資建議；投資決策應自行承擔風險。",
  "warn.b2_strong": "價格資料來自第三方公開來源",
  "warn.b2_rest": "（新浪 / 東方財富 / 英為財情 / 上海黃金交易所），存在延遲與口徑差異。",
  "warn.b3_strong": "歷史回測與勝率為過去表現",
  "warn.b3_rest": "，未來表現可能與過去差異極大。",
  "warn.b4_strong": "本工具不含槓桿與衍生品",
  "warn.b4_rest": "，僅以實物黃金 / 白銀 / 對應 ETF 為標的。",

  /* ── 頁面標題（page_title）── */
  "trend.page_title": "黃金趨勢追蹤（紐約黃金基準）",
  "portfolio.page_title": "持倉與決策 · 黃金 ETF 輔助",
  "news.page_title": "消息面評估 · 黃金 ETF 輔助",
  "weights.page_title": "權重配置 · 黃金 ETF 輔助",
  "trades.page_title": "交易歷史 · 黃金 ETF 輔助",
  "review.page_title": "研判復盤 · 黃金 ETF 輔助",
  "central_bank.page_title": "央行購金統計 · 黃金 ETF 輔助",
  "silver.page_title": "白銀趨勢追蹤（白銀 ETF + 紐約白銀）",
  "backtest.page_title": "參數回測（夏普 + 最大回撤 + 校準）",
  "settings.page_title": "通知中心 · 黃金 ETF",

  /* ── 持倉（portfolio.html）── */
  "portfolio.tagline": "以三大維度（技術面 / 宏觀面 / 消息面）綜合評估持倉與交易決策。",
  "portfolio.holdings_title": "當前持倉",

  /* ── a11y 共用 ── */
  "a11y.skip_to_main": "跳至主要內容",
};