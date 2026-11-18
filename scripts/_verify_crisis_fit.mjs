// scripts/_verify_crisis_fit.mjs
// V0.128.0 验证：经济危机金价拟合曲线（/crisis-fit）+ 首页「形态拟合」磁贴
//
// 覆盖：
//  1. 别名可达（307 → /static/crisis-fit.html），页面真的渲染出结论数字
//  2. **drift 是假设** ⇒ 页面上必须同时出现 drift=0 的终点（两条都在）
//  3. **单周期终点区间**（离散度）在页面上
//  4. **锚点敏感性**在页面上（锚点 ±1 月的终点区间）
//  5. 拟合图有 3 条线（拟合 / 模板×缩放 / 各轮终点散点）+ 31 个点
//  6. 模板图有「等权模板 + 每轮原始路径」，且模板**支撑轮数**写在页面上
//  7. **模板 clamp 边界**在图注里标明（超过 template_max_t 是平台外推）
//  8. a11y 数据表兜底**不溢出图表容器**（V0.127.2 的判据）
//  9. **无产物 ⇒ 显示「待数据」且不画曲线**（不许画一条假线）
// 10. 首页磁贴改成「形态拟合」：文案、实时行、href 三项都对
// 11. 三语切换（查 textContent，不是 data-lang —— 记忆 i18n-init-await）
// 12. 无 4xx/5xx、无 console error、无 undefined/NaN 泄漏
// 13. E8：形态拟合页**不含**扇形图；扇形图页**不含**形态拟合曲线（两者不混）
//
// ⚠ 必须打 8888（主入口）。8889/gold/ 是备用入口且全站 /api/v1/* 404。
// ⚠ 必须 setViewport(1352×900)：顶 nav（sticky）会盖住按钮，page.click() 静默失效。
// ⚠ 必须 setCacheEnabled(false) + setBypassServiceWorker(true)：
//   SW 接管后页面级请求拦截会**静默失效**（记忆 puppeteer-sw-silently-bypasses-interception）。
// ⚠ mock 的 payload 是**用真服务跑出来的**（同一套算法跑的）⇒ schema 与真实接口一致，
//   不会「mock 出一个不存在的字段」而假绿。
// ⚠⚠ **本门禁打的是「活着的服务」** ⇒ **改了后端必须先重启服务再跑门禁**，
//   否则门禁跑的是旧进程里的代码 ⇒ 撤销改动门禁照样绿（实测踩过：
//   反向验证「无产物时伪造曲线」时没重启 ⇒ 门禁 40/0 全绿，假的）。
//   ⇒ 后端的断言在 tests/test_api/test_crisis_fit_api.py 里（那里直接 import 真代码）。
import puppeteer from "puppeteer-core";

const BASE = process.env.BASE_URL || "http://192.168.0.204:8888";
const CHROME =
  "/home/surui/.cache/puppeteer/chrome/linux-153.0.8010.36/chrome-linux64/chrome";

let pass = 0;
let fail = 0;
function ok(name, cond, extra = "") {
  if (cond) { pass++; console.log(`  \u2713 ${name}`); }
  else { fail++; console.log(`  \u2717 ${name} ${extra}`); }
}

// —— 有数据场景的 mock payload（由真实服务生成）——
const MOCK = {
  "target": "ny",
  "available": true,
  "reason": null,
  "horizon_months": 30,
  "drift": 0.003,
  "anchor_month": "2026-05",
  "anchor_avg": 3300.0,
  "peak_date": "2026-05-03",
  "peak_price": 3300.0,
  "last_month": "2026-11",
  "last_avg": 3200.0,
  "t0": 6,
  "cur_norm": 97.0,
  "template": [
    [
      0,
      100.0
    ],
    [
      1,
      92.08
    ],
    [
      2,
      94.57
    ],
    [
      3,
      92.68
    ],
    [
      4,
      92.98
    ],
    [
      5,
      90.61
    ],
    [
      6,
      91.08
    ],
    [
      7,
      89.87
    ],
    [
      8,
      87.23
    ],
    [
      9,
      90.97
    ],
    [
      10,
      91.87
    ],
    [
      11,
      94.69
    ],
    [
      12,
      96.95
    ],
    [
      13,
      95.24
    ],
    [
      14,
      96.52
    ],
    [
      15,
      96.36
    ],
    [
      16,
      95.4
    ],
    [
      17,
      94.94
    ],
    [
      18,
      89.9
    ],
    [
      19,
      83.96
    ],
    [
      20,
      79.79
    ],
    [
      21,
      75.8
    ],
    [
      22,
      72.54
    ],
    [
      23,
      76.28
    ],
    [
      24,
      76.1
    ],
    [
      25,
      74.29
    ],
    [
      26,
      72.0
    ],
    [
      27,
      68.93
    ],
    [
      28,
      70.21
    ],
    [
      29,
      73.33
    ],
    [
      30,
      75.39
    ],
    [
      31,
      73.27
    ],
    [
      32,
      72.72
    ],
    [
      33,
      72.18
    ],
    [
      34,
      73.96
    ],
    [
      35,
      73.08
    ],
    [
      36,
      69.78
    ],
    [
      37,
      68.98
    ],
    [
      38,
      66.32
    ],
    [
      39,
      67.75
    ],
    [
      40,
      70.58
    ],
    [
      41,
      69.24
    ],
    [
      42,
      66.51
    ],
    [
      43,
      67.65
    ],
    [
      44,
      67.64
    ],
    [
      45,
      66.67
    ],
    [
      46,
      63.67
    ],
    [
      47,
      63.08
    ],
    [
      48,
      63.47
    ],
    [
      49,
      65.42
    ],
    [
      50,
      61.31
    ],
    [
      51,
      60.7
    ],
    [
      52,
      61.95
    ],
    [
      53,
      67.69
    ],
    [
      54,
      70.26
    ],
    [
      55,
      70.1
    ],
    [
      56,
      71.15
    ],
    [
      57,
      72.03
    ],
    [
      58,
      75.43
    ],
    [
      59,
      75.62
    ],
    [
      60,
      74.86
    ]
  ],
  "template_counts": [
    3,
    3,
    3,
    3,
    3,
    3,
    3,
    3,
    3,
    3,
    3,
    2,
    2,
    2,
    2,
    2,
    2,
    2,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1,
    1
  ],
  "template_max_t": 60,
  "cycle_paths": [
    {
      "name": "200605",
      "points": [
        [
          0,
          100.0
        ],
        [
          1,
          88.27
        ],
        [
          2,
          93.83
        ],
        [
          3,
          93.66
        ],
        [
          4,
          88.57
        ],
        [
          5,
          86.73
        ],
        [
          6,
          92.96
        ],
        [
          7,
          93.25
        ],
        [
          8,
          93.45
        ],
        [
          9,
          98.42
        ],
        [
          10,
          96.96
        ]
      ]
    },
    {
      "name": "200803",
      "points": [
        [
          0,
          100.0
        ],
        [
          1,
          93.94
        ],
        [
          2,
          91.76
        ],
        [
          3,
          91.85
        ],
        [
          4,
          97.04
        ],
        [
          5,
          86.64
        ],
        [
          6,
          85.7
        ],
        [
          7,
          83.29
        ],
        [
          8,
          78.57
        ],
        [
          9,
          84.27
        ],
        [
          10,
          88.67
        ],
        [
          11,
          97.37
        ],
        [
          12,
          95.44
        ],
        [
          13,
          91.92
        ],
        [
          14,
          95.89
        ],
        [
          15,
          97.65
        ],
        [
          16,
          96.47
        ],
        [
          17,
          98.03
        ]
      ]
    },
    {
      "name": "201109",
      "points": [
        [
          0,
          100.0
        ],
        [
          1,
          94.03
        ],
        [
          2,
          98.13
        ],
        [
          3,
          92.54
        ],
        [
          4,
          93.34
        ],
        [
          5,
          98.46
        ],
        [
          6,
          94.57
        ],
        [
          7,
          93.06
        ],
        [
          8,
          89.67
        ],
        [
          9,
          90.22
        ],
        [
          10,
          89.96
        ],
        [
          11,
          92.0
        ],
        [
          12,
          98.46
        ],
        [
          13,
          98.56
        ],
        [
          14,
          97.15
        ],
        [
          15,
          95.07
        ],
        [
          16,
          94.34
        ],
        [
          17,
          91.84
        ],
        [
          18,
          89.9
        ],
        [
          19,
          83.96
        ],
        [
          20,
          79.79
        ],
        [
          21,
          75.8
        ],
        [
          22,
          72.54
        ],
        [
          23,
          76.28
        ],
        [
          24,
          76.1
        ],
        [
          25,
          74.29
        ],
        [
          26,
          72.0
        ],
        [
          27,
          68.93
        ],
        [
          28,
          70.21
        ],
        [
          29,
          73.33
        ],
        [
          30,
          75.39
        ],
        [
          31,
          73.27
        ],
        [
          32,
          72.72
        ],
        [
          33,
          72.18
        ],
        [
          34,
          73.96
        ],
        [
          35,
          73.08
        ],
        [
          36,
          69.78
        ],
        [
          37,
          68.98
        ],
        [
          38,
          66.32
        ],
        [
          39,
          67.75
        ],
        [
          40,
          70.58
        ],
        [
          41,
          69.24
        ],
        [
          42,
          66.51
        ],
        [
          43,
          67.65
        ],
        [
          44,
          67.64
        ],
        [
          45,
          66.67
        ],
        [
          46,
          63.67
        ],
        [
          47,
          63.08
        ],
        [
          48,
          63.47
        ],
        [
          49,
          65.42
        ],
        [
          50,
          61.31
        ],
        [
          51,
          60.7
        ],
        [
          52,
          61.95
        ],
        [
          53,
          67.69
        ],
        [
          54,
          70.26
        ],
        [
          55,
          70.1
        ],
        [
          56,
          71.15
        ],
        [
          57,
          72.03
        ],
        [
          58,
          75.43
        ],
        [
          59,
          75.62
        ],
        [
          60,
          74.86
        ]
      ]
    }
  ],
  "reference_paths": [
    {
      "name": "196905",
      "points": [
        [
          0,
          100.0
        ],
        [
          1,
          95.35
        ],
        [
          2,
          96.09
        ],
        [
          3,
          94.55
        ],
        [
          4,
          94.04
        ],
        [
          5,
          93.05
        ],
        [
          6,
          86.06
        ],
        [
          7,
          80.92
        ],
        [
          8,
          80.4
        ],
        [
          9,
          80.51
        ],
        [
          10,
          80.74
        ],
        [
          11,
          81.96
        ],
        [
          12,
          82.72
        ],
        [
          13,
          81.5
        ],
        [
          14,
          81.27
        ],
        [
          15,
          81.41
        ],
        [
          16,
          83.27
        ],
        [
          17,
          86.33
        ],
        [
          18,
          86.15
        ],
        [
          19,
          86.15
        ],
        [
          20,
          87.16
        ],
        [
          21,
          89.14
        ],
        [
          22,
          89.44
        ],
        [
          23,
          89.76
        ],
        [
          24,
          93.24
        ],
        [
          25,
          92.27
        ],
        [
          26,
          94.22
        ],
        [
          27,
          98.27
        ],
        [
          28,
          96.71
        ],
        [
          29,
          97.79
        ],
        [
          30,
          98.62
        ]
      ]
    },
    {
      "name": "197412",
      "points": [
        [
          0,
          100.0
        ],
        [
          1,
          95.91
        ],
        [
          2,
          97.73
        ],
        [
          3,
          96.94
        ],
        [
          4,
          92.41
        ],
        [
          5,
          91.08
        ],
        [
          6,
          89.37
        ],
        [
          7,
          89.87
        ],
        [
          8,
          88.69
        ],
        [
          9,
          78.45
        ],
        [
          10,
          77.7
        ],
        [
          11,
          77.49
        ],
        [
          12,
          75.8
        ],
        [
          13,
          71.31
        ],
        [
          14,
          71.31
        ],
        [
          15,
          72.24
        ],
        [
          16,
          69.62
        ],
        [
          17,
          69.06
        ],
        [
          18,
          68.4
        ],
        [
          19,
          64.06
        ],
        [
          20,
          59.82
        ],
        [
          21,
          62.11
        ],
        [
          22,
          63.2
        ],
        [
          23,
          70.99
        ],
        [
          24,
          72.88
        ],
        [
          25,
          71.97
        ],
        [
          26,
          74.13
        ],
        [
          27,
          80.66
        ],
        [
          28,
          81.17
        ],
        [
          29,
          79.77
        ],
        [
          30,
          76.6
        ],
        [
          31,
          78.02
        ],
        [
          32,
          78.87
        ],
        [
          33,
          81.36
        ],
        [
          34,
          86.49
        ],
        [
          35,
          88.2
        ],
        [
          36,
          87.31
        ],
        [
          37,
          94.23
        ],
        [
          38,
          96.93
        ],
        [
          39,
          99.91
        ],
        [
          40,
          95.37
        ],
        [
          41,
          95.94
        ],
        [
          42,
          99.98
        ]
      ]
    },
    {
      "name": "198001",
      "points": [
        [
          0,
          100.0
        ],
        [
          1,
          98.52
        ],
        [
          2,
          81.97
        ],
        [
          3,
          76.62
        ],
        [
          4,
          76.08
        ],
        [
          5,
          88.95
        ],
        [
          6,
          95.26
        ],
        [
          7,
          92.87
        ],
        [
          8,
          99.75
        ],
        [
          9,
          97.9
        ],
        [
          10,
          92.52
        ],
        [
          11,
          79.71
        ],
        [
          12,
          82.54
        ],
        [
          13,
          74.0
        ],
        [
          14,
          73.91
        ],
        [
          15,
          73.42
        ],
        [
          16,
          71.03
        ],
        [
          17,
          68.28
        ],
        [
          18,
          60.58
        ],
        [
          19,
          60.74
        ],
        [
          20,
          65.71
        ],
        [
          21,
          64.82
        ],
        [
          22,
          61.21
        ],
        [
          23,
          60.73
        ],
        [
          24,
          56.88
        ],
        [
          25,
          55.4
        ],
        [
          26,
          48.9
        ],
        [
          27,
          51.87
        ],
        [
          28,
          49.42
        ],
        [
          29,
          46.64
        ],
        [
          30,
          50.19
        ],
        [
          31,
          53.94
        ],
        [
          32,
          64.76
        ],
        [
          33,
          62.51
        ],
        [
          34,
          61.44
        ],
        [
          35,
          65.82
        ],
        [
          36,
          71.27
        ],
        [
          37,
          72.72
        ],
        [
          38,
          62.15
        ],
        [
          39,
          64.1
        ],
        [
          40,
          64.86
        ],
        [
          41,
          61.13
        ],
        [
          42,
          59.66
        ],
        [
          43,
          61.63
        ],
        [
          44,
          60.98
        ],
        [
          45,
          58.28
        ],
        [
          46,
          56.52
        ],
        [
          47,
          57.51
        ],
        [
          48,
          54.92
        ],
        [
          49,
          57.15
        ],
        [
          50,
          58.38
        ],
        [
          51,
          56.47
        ],
        [
          52,
          55.89
        ],
        [
          53,
          55.93
        ],
        [
          54,
          51.49
        ],
        [
          55,
          51.49
        ],
        [
          56,
          50.38
        ],
        [
          57,
          50.5
        ],
        [
          58,
          50.64
        ],
        [
          59,
          47.32
        ],
        [
          60,
          44.84
        ]
      ]
    },
    {
      "name": "198302",
      "points": [
        [
          0,
          100.0
        ],
        [
          1,
          85.46
        ],
        [
          2,
          88.15
        ],
        [
          3,
          89.19
        ],
        [
          4,
          84.07
        ],
        [
          5,
          82.04
        ],
        [
          6,
          84.75
        ],
        [
          7,
          83.85
        ],
        [
          8,
          80.15
        ],
        [
          9,
          77.73
        ],
        [
          10,
          79.08
        ],
        [
          11,
          75.52
        ],
        [
          12,
          78.59
        ],
        [
          13,
          80.28
        ],
        [
          14,
          77.66
        ],
        [
          15,
          76.85
        ],
        [
          16,
          76.91
        ],
        [
          17,
          70.8
        ],
        [
          18,
          70.8
        ],
        [
          19,
          69.27
        ],
        [
          20,
          69.44
        ],
        [
          21,
          69.64
        ],
        [
          22,
          65.07
        ],
        [
          23,
          61.66
        ],
        [
          24,
          60.91
        ],
        [
          25,
          63.84
        ],
        [
          26,
          66.55
        ],
        [
          27,
          64.35
        ],
        [
          28,
          64.45
        ],
        [
          29,
          64.59
        ],
        [
          30,
          67.28
        ],
        [
          31,
          65.84
        ],
        [
          32,
          66.35
        ],
        [
          33,
          65.47
        ],
        [
          34,
          65.55
        ],
        [
          35,
          70.76
        ],
        [
          36,
          69.01
        ],
        [
          37,
          70.39
        ],
        [
          38,
          69.32
        ],
        [
          39,
          69.72
        ],
        [
          40,
          69.78
        ],
        [
          41,
          70.93
        ],
        [
          42,
          76.7
        ],
        [
          43,
          85.06
        ],
        [
          44,
          86.24
        ],
        [
          45,
          80.95
        ],
        [
          46,
          79.6
        ],
        [
          47,
          83.13
        ],
        [
          48,
          81.68
        ],
        [
          49,
          83.27
        ],
        [
          50,
          89.26
        ],
        [
          51,
          93.72
        ],
        [
          52,
          91.55
        ],
        [
          53,
          91.74
        ],
        [
          54,
          93.9
        ],
        [
          55,
          93.75
        ],
        [
          56,
          94.76
        ],
        [
          57,
          95.21
        ],
        [
          58,
          99.01
        ],
        [
          59,
          97.05
        ],
        [
          60,
          90.02
        ]
      ]
    },
    {
      "name": "199002",
      "points": [
        [
          0,
          100.0
        ],
        [
          1,
          94.3
        ],
        [
          2,
          89.79
        ],
        [
          3,
          88.54
        ],
        [
          4,
          84.53
        ],
        [
          5,
          86.98
        ],
        [
          6,
          94.7
        ],
        [
          7,
          93.4
        ],
        [
          8,
          91.35
        ],
        [
          9,
          91.58
        ],
        [
          10,
          90.44
        ],
        [
          11,
          92.04
        ],
        [
          12,
          87.29
        ],
        [
          13,
          87.17
        ],
        [
          14,
          85.98
        ],
        [
          15,
          85.64
        ],
        [
          16,
          87.98
        ],
        [
          17,
          88.22
        ],
        [
          18,
          85.48
        ],
        [
          19,
          83.67
        ],
        [
          20,
          86.06
        ],
        [
          21,
          86.41
        ],
        [
          22,
          86.79
        ],
        [
          23,
          85.04
        ],
        [
          24,
          84.91
        ],
        [
          25,
          82.61
        ],
        [
          26,
          81.24
        ],
        [
          27,
          80.91
        ],
        [
          28,
          81.77
        ],
        [
          29,
          84.62
        ],
        [
          30,
          82.31
        ],
        [
          31,
          82.87
        ],
        [
          32,
          82.62
        ],
        [
          33,
          80.38
        ],
        [
          34,
          80.33
        ],
        [
          35,
          78.94
        ],
        [
          36,
          79.01
        ],
        [
          37,
          79.19
        ],
        [
          38,
          82.09
        ],
        [
          39,
          88.09
        ],
        [
          40,
          89.22
        ],
        [
          41,
          94.09
        ],
        [
          42,
          90.89
        ],
        [
          43,
          85.24
        ],
        [
          44,
          87.37
        ],
        [
          45,
          89.69
        ],
        [
          46,
          91.96
        ],
        [
          47,
          92.82
        ],
        [
          48,
          91.63
        ],
        [
          49,
          92.16
        ],
        [
          50,
          90.51
        ],
        [
          51,
          91.51
        ],
        [
          52,
          92.52
        ],
        [
          53,
          92.49
        ],
        [
          54,
          91.26
        ],
        [
          55,
          93.95
        ],
        [
          56,
          93.51
        ],
        [
          57,
          92.22
        ],
        [
          58,
          91.0
        ],
        [
          59,
          90.82
        ],
        [
          60,
          90.36
        ]
      ]
    },
    {
      "name": "199910",
      "points": [
        [
          0,
          100.0
        ],
        [
          1,
          94.36
        ],
        [
          2,
          91.1
        ],
        [
          3,
          91.5
        ],
        [
          4,
          96.5
        ],
        [
          5,
          92.17
        ],
        [
          6,
          90.01
        ],
        [
          7,
          88.57
        ],
        [
          8,
          91.96
        ],
        [
          9,
          90.62
        ],
        [
          10,
          88.33
        ],
        [
          11,
          88.08
        ],
        [
          12,
          86.89
        ],
        [
          13,
          85.61
        ],
        [
          14,
          87.36
        ],
        [
          15,
          85.44
        ],
        [
          16,
          84.28
        ],
        [
          17,
          84.65
        ],
        [
          18,
          83.83
        ],
        [
          19,
          87.65
        ],
        [
          20,
          86.97
        ],
        [
          21,
          86.1
        ],
        [
          22,
          87.66
        ],
        [
          23,
          91.21
        ],
        [
          24,
          91.1
        ],
        [
          25,
          88.88
        ],
        [
          26,
          88.78
        ],
        [
          27,
          90.6
        ],
        [
          28,
          95.1
        ],
        [
          29,
          94.64
        ],
        [
          30,
          97.41
        ]
      ]
    }
  ],
  "support_at_horizon": 1,
  "fit_window": {
    "start": "2000-01",
    "end": "2016-11"
  },
  "reference_window": {
    "start": "1960-01",
    "end": "2000-01"
  },
  "curve": [
    {
      "t": 6,
      "month": "2026-11",
      "norm": 97.0,
      "price": 3200.0
    },
    {
      "t": 7,
      "month": "2026-12",
      "norm": 96.0,
      "price": 3167.0
    },
    {
      "t": 8,
      "month": "2027-01",
      "norm": 93.4,
      "price": 3083.0
    },
    {
      "t": 9,
      "month": "2027-02",
      "norm": 97.7,
      "price": 3225.0
    },
    {
      "t": 10,
      "month": "2027-03",
      "norm": 99.0,
      "price": 3267.0
    },
    {
      "t": 11,
      "month": "2027-04",
      "norm": 102.3,
      "price": 3377.0
    },
    {
      "t": 12,
      "month": "2027-05",
      "norm": 105.1,
      "price": 3468.0
    },
    {
      "t": 13,
      "month": "2027-06",
      "norm": 103.6,
      "price": 3417.0
    },
    {
      "t": 14,
      "month": "2027-07",
      "norm": 105.3,
      "price": 3474.0
    },
    {
      "t": 15,
      "month": "2027-08",
      "norm": 105.4,
      "price": 3478.0
    },
    {
      "t": 16,
      "month": "2027-09",
      "norm": 104.7,
      "price": 3454.0
    },
    {
      "t": 17,
      "month": "2027-10",
      "norm": 104.5,
      "price": 3447.0
    },
    {
      "t": 18,
      "month": "2027-11",
      "norm": 99.2,
      "price": 3274.0
    },
    {
      "t": 19,
      "month": "2027-12",
      "norm": 92.9,
      "price": 3067.0
    },
    {
      "t": 20,
      "month": "2028-01",
      "norm": 88.6,
      "price": 2924.0
    },
    {
      "t": 21,
      "month": "2028-02",
      "norm": 84.4,
      "price": 2786.0
    },
    {
      "t": 22,
      "month": "2028-03",
      "norm": 81.0,
      "price": 2674.0
    },
    {
      "t": 23,
      "month": "2028-04",
      "norm": 85.5,
      "price": 2820.0
    },
    {
      "t": 24,
      "month": "2028-05",
      "norm": 85.5,
      "price": 2822.0
    },
    {
      "t": 25,
      "month": "2028-06",
      "norm": 83.7,
      "price": 2763.0
    },
    {
      "t": 26,
      "month": "2028-07",
      "norm": 81.4,
      "price": 2686.0
    },
    {
      "t": 27,
      "month": "2028-08",
      "norm": 78.2,
      "price": 2579.0
    },
    {
      "t": 28,
      "month": "2028-09",
      "norm": 79.8,
      "price": 2635.0
    },
    {
      "t": 29,
      "month": "2028-10",
      "norm": 83.6,
      "price": 2760.0
    },
    {
      "t": 30,
      "month": "2028-11",
      "norm": 86.3,
      "price": 2846.0
    },
    {
      "t": 31,
      "month": "2028-12",
      "norm": 84.1,
      "price": 2775.0
    },
    {
      "t": 32,
      "month": "2029-01",
      "norm": 83.7,
      "price": 2762.0
    },
    {
      "t": 33,
      "month": "2029-02",
      "norm": 83.3,
      "price": 2750.0
    },
    {
      "t": 34,
      "month": "2029-03",
      "norm": 85.6,
      "price": 2826.0
    },
    {
      "t": 35,
      "month": "2029-04",
      "norm": 84.9,
      "price": 2801.0
    },
    {
      "t": 36,
      "month": "2029-05",
      "norm": 81.3,
      "price": 2682.0
    }
  ],
  "endpoint": {
    "t": 36,
    "month": "2029-05",
    "norm": 81.3,
    "price": 2682.0
  },
  "endpoint_drift0": {
    "t": 36,
    "month": "2029-05",
    "norm": 74.3,
    "price": 2452.0
  },
  "gain_pct": -16.2,
  "cycle_ends": [
    {
      "name": "200605",
      "norm": 110.7,
      "price": 3652.0
    },
    {
      "name": "200803",
      "norm": 121.4,
      "price": 4005.0
    },
    {
      "name": "201109",
      "norm": 78.3,
      "price": 2583.0
    }
  ],
  "sensitivity": {
    "anchor_minus1_price": 2687.0,
    "anchor_plus1_price": 2824.0,
    "low": 2682.0,
    "high": 2824.0,
    "spread_pct": 5.3
  },
  "provenance": {
    "source": "世界银行 Pink Sheet（Commodity Price Data）月度表 Gold 列",
    "url": "https://thedocs.worldbank.org/en/doc/5d903e848db1d1b83e0ec8f744e55570-0350012021/related/CMO-Historical-Data-Monthly.xlsx",
    "coverage": "1960-01 → 2024-12（月度金价 $/troy oz）",
    "method": "London fix 月均；周期按「±6 月局部高点 + prominence≥10% + 同episode归并 + 后续36月回撤≥10%（金价破裂）+ 早于当前周期起点」自动识别（无人工挑选）；拟合只取 2000-01 之后的周期，更早的进 reference_cycles（只展示、不进模板）",
    "updated": "Updated on January 03, 2025",
    "exported_at": "2026-11-18",
    "note": "当前周期用仓库自己的 COMEX 期货价（gold_price_daily/target=ny），与本模板的伦敦现货口径不同 ⇒ 只影响绝对价位，形状（归一后）可比"
  },
  "warnings": [],
  "generated_at": "2026-11-18T00:00:00Z"
};

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1352, height: 900 });
await page.setCacheEnabled(false);
await page.setBypassServiceWorker(true);
await page.setExtraHTTPHeaders({ "X-Forwarded-For": "198.51.100.81" });

const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push("pageerror: " + e.message));
page.on("console", (m) => {
  if (m.type() === "error" && !/Failed to load resource|favicon/i.test(m.text())) {
    pageErrors.push("console: " + m.text());
  }
});
const bad = [];
page.on("response", (r) => {
  if (r.status() >= 400) bad.push(`${r.status()} ${r.url()}`);
});

// ───────────────── 拦截：把 crisis-fit 接口替换成 mock ─────────────────
await page.setRequestInterception(true);
page.on("request", (req) => {
  const url = req.url();
  if (url.includes("/api/v1/forecast/crisis-fit")) {
    req.respond({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(MOCK),
    });
    return;
  }
  req.continue();
});

// ─── 1. 别名 + 页面渲染 ───
console.log("\n【1】独立页 /crisis-fit");
const alias = await fetch(BASE + "/crisis-fit", { redirect: "manual" });
ok("别名 307 重定向", alias.status === 307, `实际 ${alias.status}`);

await page.goto(BASE + "/crisis-fit", { waitUntil: "networkidle2", timeout: 60000 });
await page.waitForFunction(
  () => {
    const el = document.getElementById("cfRange");
    return el && el.textContent && el.textContent.trim() !== "\u2014" && /[0-9]/.test(el.textContent);
  },
  { timeout: 40000 },
);
await new Promise((r) => setTimeout(r, 1200));

const rangeText = await page.$eval("#cfRange", (el) => el.textContent || "");
ok("结论渲染出数字", /[0-9]/.test(rangeText), rangeText);
ok("结论无 undefined / NaN", !/undefined|NaN/.test(rangeText), rangeText);
const bodyText = await page.evaluate(() => document.body.innerText);
ok("页面无 undefined / NaN 泄漏", !/undefined|NaN/.test(bodyText));

// ─── 2. drift=0 对照（drift 是假设 ⇒ 必须并列）───
console.log("\n【2】drift 假设 vs drift=0 对照");
const driftCmp = await page.evaluate(() => {
  const meta = document.getElementById("cfMeta");
  const txt = meta ? meta.innerText : "";
  const nums = (txt.match(/[0-9][0-9,]*(\.[0-9]+)?/g) || []).map((s) => Number(s.replace(/,/g, "")));
  return { txt, nums, hasZero: /drift\s*=\s*0/i.test(txt) };
});
ok("页面上有 drift=0 对照行", driftCmp.hasZero, driftCmp.txt.replace(/\n/g, " | ").slice(0, 120));
ok("drift=0 对照与主结论是两个不同的数",
  driftCmp.nums.length >= 2 && driftCmp.nums[0] !== driftCmp.nums[1],
  JSON.stringify(driftCmp.nums));
ok("对照的数 = 接口的 endpoint_drift0.price",
  driftCmp.nums.some((n) => Math.abs(n - MOCK.endpoint_drift0.price) < 1),
  JSON.stringify({ nums: driftCmp.nums, expect: MOCK.endpoint_drift0.price }));

// ─── 3. 单周期终点区间 ───
console.log("\n【3】各轮周期的终点区间（离散度）");
const ends = await page.evaluate(() => {
  const el = document.getElementById("cfCycleEnds");
  return { text: el ? el.innerText : "", lis: el ? el.querySelectorAll("li").length : 0 };
});
ok("单周期终点区块有内容", ends.text.length > 0, ends.text.replace(/\n/g, " | ").slice(0, 120));
ok("列出每一轮周期", ends.lis === MOCK.cycle_ends.length, `实际 ${ends.lis} / 期望 ${MOCK.cycle_ends.length}`);
ok("区间含最小/最大终点",
  ends.text.includes(String(MOCK.cycle_ends[0].price).replace(/\B(?=(\d{3})+(?!\d))/g, ",")) ||
  ends.text.replace(/,/g, "").includes(String(Math.min(...MOCK.cycle_ends.map((e) => e.price)))),
  ends.text.replace(/\n/g, " | ").slice(0, 160));

// ─── 4. 锚点敏感性 ───
console.log("\n【4】锚点敏感性");
const sens = await page.evaluate(() => {
  const el = document.getElementById("cfSensitivity");
  return { text: el ? el.innerText : "", warn: el ? el.className.includes("cf-sens-warn") : false };
});
ok("锚点敏感性在页面上", sens.text.length > 0, sens.text.slice(0, 160));
ok("敏感度写的是接口给的 spread",
  sens.text.replace(/,/g, "").includes(String(MOCK.sensitivity.spread_pct)),
  `${sens.text.slice(0, 120)} / 期望 ${MOCK.sensitivity.spread_pct}`);

// ─── 5. 拟合图 ───
console.log("\n【5】拟合图");
const fit = await page.evaluate(() => {
  const c = document.getElementById("cfFitChart");
  if (!c) return null;
  const inst = Chart.getChart(c);
  if (!inst) return null;
  const ds = inst.data.datasets.map((d) => ({
    label: d.label,
    n: (d.data || []).length,
    vals: (d.data || []).map((p) => (p && typeof p === "object" ? p.y : p)),
  }));
  // 拟合线第一个非空值落在第几个类目（x 轴 = 距锚点月数 t ⇒ 应该是 t0）
  const fitVals = ds[1] ? ds[1].vals : [];
  let firstNonNull = -1;
  for (let i = 0; i < fitVals.length; i++) {
    if (fitVals[i] != null) { firstNonNull = i; break; }
  }
  // 终点散点的**实际像素位置**（category 轴：给数字 x 时 Chart.js 会自己解释，
  // ⚠ 断言必须比「解析后的像素」而不是原始值 —— 拿原始值比会自证（实测踩过））
  const scIdx = inst.data.datasets.findIndex((d) => d.type === "scatter");
  let scatterPx = [];
  let lastTickPx = null;
  if (scIdx >= 0) {
    const meta = inst.getDatasetMeta(scIdx);
    scatterPx = (meta.data || []).map((pt) => Math.round(pt.x));
    // ⚠ 参考点必须用 getPixelForValue（类目**索引** → 像素）；
    //   getPixelForTick 是「刻度序号」⇒ 索引超范围时返回 0（左边缘）⇒ 断言会失真。
    lastTickPx = Math.round(inst.scales.x.getPixelForValue(inst.data.labels.length - 1));
  }
  return {
    n: ds.length,
    ds: ds,
    labels: inst.data.labels.length,
    firstNonNull,
    scatterPx,
    lastTickPx,
    lastLabel: inst.data.labels[inst.data.labels.length - 1],
  };
});
ok("拟合图已渲染", !!fit, JSON.stringify(fit && fit.n));
if (fit) {
  ok("3 条 dataset（模板×缩放 / 拟合 / 各轮终点）", fit.n === 3, `实际 ${fit.n}`);
  const fitDs = fit.ds[1];
  ok("拟合曲线 31 个点", fitDs.vals.filter((v) => v != null).length === MOCK.curve.length,
    `实际 ${fitDs.vals.filter((v) => v != null).length}`);
  ok("拟合线与接口数值一致（起点 = 当前点）",
    Math.abs(fitDs.vals.filter((v) => v != null)[0] - MOCK.curve[0].price) < 1,
    `${fitDs.vals.filter((v) => v != null)[0]} / ${MOCK.curve[0].price}`);
  ok("终点散点 3 个", fit.ds[2].vals.filter((v) => v != null).length === MOCK.cycle_ends.length,
    `实际 ${fit.ds[2].vals.filter((v) => v != null).length}`);
  // ⚠ x 轴 = 距锚点月数 t ⇒ 拟合线只能从 t0（当前点）开始；
  //   画在轴首 = 月份错位（实测踩过：曲线整体左移 t0 个月）。
  ok("拟合线从当前点(t0)开始，不是画在轴首", fit.firstNonNull === MOCK.t0,
    `首个非空 index=${fit.firstNonNull} / t0=${MOCK.t0}`);
  // ⚠ category 轴上给数字 x ⇒ 散点可能被解析到别处（实测全挤在左边）。
  ok("各轮终点散点在曲线末端（像素位置 = 最后一个类目）",
    fit.scatterPx.length > 0 && fit.lastTickPx != null &&
    fit.scatterPx.every((px) => Math.abs(px - fit.lastTickPx) <= 2),
    `散点像素=${JSON.stringify(fit.scatterPx)} / 末端类目像素=${fit.lastTickPx}`);
}

// ─── 6. 模板图 + 支撑轮数 + clamp 边界 ───
console.log("\n【6】模板图与证据");
const tpl = await page.evaluate(() => {
  const c = document.getElementById("cfTemplateChart");
  const inst = c ? Chart.getChart(c) : null;
  const note = document.getElementById("cfTemplateNote");
  const fitNote = document.getElementById("cfFitNote");
  return {
    n: inst ? inst.data.datasets.length : 0,
    note: note ? note.innerText : "",
    fitNote: fitNote ? fitNote.innerText : "",
  };
});
ok("模板图有 dataset（每轮路径 + 等权模板）", tpl.n === MOCK.cycle_paths.length + 1, `实际 ${tpl.n}`);
ok("支撑轮数写在页面上", /[0-9]/.test(tpl.note), tpl.note.slice(0, 160));
ok("模板 clamp 边界在图注里标明", /t=\s*\d+/.test(tpl.fitNote), tpl.fitNote.slice(0, 200));

// ─── 6.5 拟合窗口（2000 年以后）+ 更早周期作参照 ───
console.log("\n【6.5】拟合窗口收窄 + 参照集");
const split = await page.evaluate(() => {
  const tpl = Chart.getChart(document.getElementById("cfTemplateChart"));
  const ref = Chart.getChart(document.getElementById("cfRefChart"));
  const sup = document.getElementById("cfSupport");
  const note = document.getElementById("cfTemplateNote");
  return {
    tplDatasets: tpl ? tpl.data.datasets.length : 0,
    refDatasets: ref ? ref.data.datasets.length : 0,
    supText: sup ? sup.textContent.trim() : "",
    supWarn: sup ? sup.className.includes("cf-sup-warn") : false,
    note: note ? note.textContent : "",
  };
});
// 模板图 = 拟合集每轮路径 + 等权模板；参照图 = 更早的周期（只展示）
ok("模板图只含拟合集的周期", split.tplDatasets === MOCK.cycle_paths.length + 1,
  `实际 ${split.tplDatasets} / 期望 ${MOCK.cycle_paths.length + 1}`);
ok("参照图含更早的周期（只展示、不进模板）", split.refDatasets === MOCK.reference_paths.length,
  `实际 ${split.refDatasets} / 期望 ${MOCK.reference_paths.length}`);
ok("图注写明拟合窗口起点", split.note.includes(MOCK.fit_window.start), split.note.slice(0, 160));
// ⚠ 外推终点支撑轮数薄 ⇒ 必须有告警（拟合窗口收窄后的真实后果）
ok("支撑轮数薄时给出告警", split.supWarn && /1|一/.test(split.supText), split.supText.slice(0, 160));

// ─── 7. a11y 兜底表不溢出容器（V0.127.2 判据）───
console.log("\n【7】a11y 数据表落点");
const a11y = await page.evaluate(() => {
  const ds = Array.from(document.querySelectorAll("details.pm-chart-fallback"));
  const over = ds.map((d) => {
    const host = d.parentElement;
    const hb = host.getBoundingClientRect();
    const db = d.getBoundingClientRect();
    return { host: host.id || host.className, over: db.bottom > hb.bottom + 1 || db.right > hb.right + 1 };
  }).filter((x) => x.over);
  const covered = [];
  const targets = document.querySelectorAll("canvas, table, h2, .cf-note, .cf-method, .panel-title");
  ds.forEach((d) => {
    d.open = true;
    const r = d.getBoundingClientRect();
    targets.forEach((t) => {
      if (d.contains(t)) return;
      const tr = t.getBoundingClientRect();
      if (!tr.width || !tr.height) return;
      const ix = Math.min(r.right, tr.right) - Math.max(r.left, tr.left);
      const iy = Math.min(r.bottom, tr.bottom) - Math.max(r.top, tr.top);
      if (ix > 2 && iy > 2) covered.push({ el: t.id || t.className || t.tagName });
    });
  });
  return { n: ds.length, over, covered };
});
ok("页面有 a11y 数据表兜底", a11y.n >= 2, `实际 ${a11y.n}`);
ok("a11y 数据表没有溢出图表容器", a11y.over.length === 0, JSON.stringify(a11y.over));
ok("a11y 数据表展开后不遮挡下方内容", a11y.covered.length === 0, JSON.stringify(a11y.covered));

// ─── 8. E8：形态拟合页不含扇形图；扇形图页不含形态拟合 ───
console.log("\n【8】E8 两个功能不混");
ok("形态拟合页没有扇形图 canvas", await page.evaluate(() => !document.getElementById("pfFanChart")));
await page.goto(BASE + "/price-forecast", { waitUntil: "networkidle2", timeout: 60000 });
await new Promise((r) => setTimeout(r, 1500));
ok("扇形图页没有形态拟合 canvas", await page.evaluate(() =>
  !document.getElementById("cfFitChart") && !document.getElementById("cfTemplateChart")));

// ─── 9. 无产物 ⇒ 待数据（**显式 mock 降级响应**）───
// ⚠ 不能靠「仓库里恰好没有产物文件」来测降级：V0.128.0 把真实产物入库后，
//   这条断言就会假红（实测踩过）⇒ 必须显式 mock 一个 available=false 的响应。
console.log("\n【9】无产物 ⇒ 待数据（不画假线）");
await page.setRequestInterception(true);
page.removeAllListeners("request");
page.on("request", (req) => {
  const url = req.url();
  if (url.includes("/api/v1/forecast/crisis-fit")) {
    req.respond({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        target: "ny", available: false, reason: "no_crisis_cycles_artifact",
        horizon_months: 30, drift: 0.003, curve: [], endpoint: null,
        endpoint_drift0: null, cycle_ends: [], template: [], template_counts: [],
        template_max_t: null, cycle_paths: [], sensitivity: null,
        provenance: {}, warnings: [],
      }),
    });
    return;
  }
  req.continue();
});
await page.goto(BASE + "/crisis-fit", { waitUntil: "networkidle2", timeout: 60000 });
await new Promise((r) => setTimeout(r, 2000));
const pending = await page.evaluate(() => {
  const r = document.getElementById("cfRange");
  const inst = document.getElementById("cfFitChart");
  return {
    text: r ? r.textContent : "",
    hasChart: !!(inst && Chart.getChart(inst)),
    body: document.body.innerText,
  };
});
ok("无产物时显示「待数据」", pending.text.includes("待数据"), pending.text);
ok("无产物时不画拟合图", pending.hasChart === false);
ok("无产物时说明了为什么不画",
  /不画|尚未入库|样本不足/.test(pending.body), pending.body.slice(0, 200));

// ─── 10. 首页磁贴 ───
console.log("\n【10】首页「形态拟合」磁贴");
await page.goto(BASE + "/home", { waitUntil: "networkidle2", timeout: 60000 });
await new Promise((r) => setTimeout(r, 2500));
const tile = await page.evaluate(() => {
  const a = document.querySelector(".home-scene.scene-forecast");
  const live = document.getElementById("cfTileRange");
  return {
    href: a ? a.getAttribute("href") : null,
    title: a ? a.querySelector(".scene-title")?.textContent?.trim() : null,
    live: live ? live.textContent.trim() : null,
    oldTile: !!document.getElementById("fcTileRange"),
  };
});
ok("磁贴指向 /crisis-fit", tile.href === "/crisis-fit", String(tile.href));
ok("磁贴标题是「形态拟合」", tile.title === "形态拟合", String(tile.title));
ok("磁贴实时行有内容", !!tile.live && tile.live.length > 0, String(tile.live));
ok("旧的金价区间磁贴已移除", tile.oldTile === false);

// ─── 11. 三语切换 ───
console.log("\n【11】三语切换");
for (const lang of ["en-US", "zh-TW", "zh-CN"]) {
  await page.goto(BASE + "/crisis-fit", { waitUntil: "networkidle2", timeout: 60000 });
  await page.waitForFunction(
    () => {
      const el = document.getElementById("cfRange");
      return el && el.textContent && /[0-9]|待/.test(el.textContent);
    },
    { timeout: 30000 },
  ).catch(() => {});
  await page.evaluate(async (l) => { await window.I18n.setLang(l); }, lang);
  await new Promise((r) => setTimeout(r, 900));
  const t = await page.evaluate(() => ({
    hero: document.querySelector(".hero h1")?.textContent?.trim() || "",
    body: document.body.innerText,
  }));
  ok(`${lang} 标题已翻译`, t.hero.length > 0 && !/^\s*$/.test(t.hero), t.hero);
  ok(`${lang} 无 undefined 泄漏`, !/undefined/.test(t.body));
}

// ─── 12. 网络 / 脚本 ───
console.log("\n【12】网络 / 脚本");
ok("无 4xx/5xx", bad.length === 0, bad.slice(0, 5).join(" | "));
ok("无 console error / pageerror", pageErrors.length === 0, pageErrors.slice(0, 3).join(" | "));

await browser.close();
console.log(`\n${"=".repeat(56)}`);
console.log(`  结果：${pass} passed, ${fail} failed`);
console.log("=".repeat(56));
process.exit(fail === 0 ? 0 : 1);
