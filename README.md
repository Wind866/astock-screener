# A股事件筛选器

按 **股东增减持 · 定增 · 回购 · 分红** 四类事件筛选 A 股个股的轻量看板：纯静态前端（零依赖、手机电脑自适应）+ AKShare 数据采集 + 每日定时推送飞书，整体跑在一个 GitHub 仓库里。

![预览](docs/preview.png)

## 功能

- **四类事件统一筛选**：股东增持 / 减持（高管与股东持股变动）、定增（增发）、股票回购、分红送配（含送转与股息率）
- **多条件组合**：关键词（代码/名称/股东，空格分隔）、事件类型多选、板块、公告时间（7/30/90 天/全部）、金额下限、股息率下限、进度状态
- **排序**：侧栏排序 + 表头点击排序（公告日、金额、占比/股息率、数量、涨跌幅、名称）
- **交互**：KPI 卡片点击即筛选、行点击打开详情抽屉、星标自选股（本地保存）、筛选状态写入 URL 可直接分享、CSV 导出、深浅色主题
- **可视化**：近 14 日事件分布堆叠图、事件金额构成环形图（纯 SVG，无第三方库）
- **每日推送**：GitHub Actions 定时采集 → 飞书卡片（含统计与各类 TOP 榜）→ 数据快照回写仓库

## 数据来源

东方财富公开数据（经 [AKShare](https://github.com/akfamily/akshare) 接口）：

| 事件 | 接口 | 字段口径 |
| --- | --- | --- |
| 股东增减持 | `stock_ggcg_em` | 变动数量（万股）、占总股本比例、变动期间、公告日 |
| 定增 / 增发 | `stock_qbzf_em` | 发行价格、发行总数、发行方式、发行日期、锁定期 |
| 回购 | `stock_repurchase_em` | 已回购金额/股数、计划金额区间、实施进度 |
| 分红送配 | `stock_fhps_em` | 10派X元/送X股/转X股、股息率、除权除息日、方案进度 |

> 金额为披露值或按最新价/总股本估算（界面中以 `≈` 标注），仅作信息聚合，不构成投资建议。

## 本地运行

```bash
pip install -r requirements.txt

python scripts/fetch_data.py            # 采集真实数据
python scripts/fetch_data.py --demo     # 无网络时生成演示数据
python scripts/fetch_data.py --days 30  # 调整回看窗口

python -m http.server 8000              # 打开 http://localhost:8000
```

也可以直接双击 `index.html`（数据通过 `data/latest.js` 内嵌加载，无需服务器）。

## 飞书推送

1. 飞书群 → 设置 → 群机器人 → 添加「自定义机器人」，拿到 webhook 地址
2. 若开启了「签名校验」，记下签名密钥
3. 在仓库 **Settings → Secrets and variables → Actions** 添加：

| Secret | 说明 | 必填 |
| --- | --- | --- |
| `FEISHU_WEBHOOK` | 机器人 webhook 地址 | ✅ |
| `FEISHU_SECRET` | 签名密钥 | 开了签名时 |
| `PAGE_URL` | 部署后的站点地址，卡片里的「打开筛选器」按钮会跳到这里 | 建议 |

本地测试：

```bash
export FEISHU_WEBHOOK="https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
python scripts/notify_feishu.py --dry-run   # 预览卡片
python scripts/notify_feishu.py             # 实际发送
```

## 部署到 GitHub

```bash
git init && git add . && git commit -m "init: A股事件筛选器"
git remote add origin https://github.com/<你的用户名>/astock-screener.git
git push -u origin main
```

推送后：

1. **Settings → Pages → Source 选 GitHub Actions**，`pages.yml` 会把整个仓库作为静态站点发布，地址形如 `https://<用户名>.github.io/astock-screener/`
2. 把这个地址填到 `PAGE_URL` Secret，飞书卡片即可一键跳转
3. `daily.yml` 每个工作日 16:40（北京时间）自动采集、推送、回写 `data/` 快照；也可在 Actions 页面手动 Run

## 配置（config.json）

```json
{
  "lookbackDays": 90,      // 采集回看窗口
  "maxEvents": 2000,       // 数据文件事件上限
  "minAmountWan": 0,       // 全局金额下限（万元）
  "sources": { ... },      // 可单独关闭某类数据源
  "feishu": { "maxItemsPerSection": 6, "pageUrl": "" }
}
```

## 目录结构

```
├── index.html               # 前端页面（纯静态）
├── assets/                  # 样式与交互脚本
├── data/
│   ├── latest.json / .js    # 最新数据（脚本会同时生成两种格式）
│   └── history/             # 每日快照与索引
├── scripts/
│   ├── collectors.py        # 四类事件采集与归一化
│   ├── fetch_data.py        # 采集入口（--demo / --days）
│   ├── notify_feishu.py     # 飞书卡片推送（含签名）
│   └── demo_data.py         # 离线演示数据
├── .github/workflows/
│   ├── daily.yml            # 定时采集 + 推送 + 快照回写
│   └── pages.yml            # GitHub Pages 部署
└── config.json              # 运行配置
```

## 免责声明

本项目仅聚合公开信息，数据可能延迟或有口径差异，请以交易所公告为准；不构成任何投资建议。
