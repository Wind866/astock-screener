# A股事件筛选器

按 **股东增减持 · 定增 · 回购 · 分红** 四类事件筛选 A 股个股的轻量看板：纯静态前端（零依赖、手机电脑自适应）+ AKShare 数据采集 + 每日定时推送飞书，整体跑在一个 GitHub 仓库里。

![预览](docs/preview.png)

## 功能

- **四类事件统一筛选**：股东增持 / 减持（高管与股东持股变动）、定增（增发）、股票回购、分红送配（含送转与股息率）
- **多条件组合**：关键词（代码/名称/股东，空格分隔）、事件类型多选、板块、公告时间（7/30/90 天/全部）、金额下限、股息率下限、进度状态
- **排序**：侧栏排序 + 表头点击排序（公告日、金额、占比/股息率、数量、涨跌幅、名称）
- **交互**：KPI 卡片点击即筛选、行点击打开详情抽屉、星标自选股（本地保存）、筛选状态写入 URL 可直接分享、CSV 导出、深浅色主题
- **选股 × 事件交叉**（可选）：对接 [BIGApush](https://github.com/Wind866/BIGApush) 收盘选股池——表格里出现 `⌖` 徽标标记当天被形态策略选中的个股，「只看选股池内」一键交叉，详情抽屉展示命中策略/评分/排名；接法见 [docs/bigapush-integration](docs/bigapush-integration/README.md)，没接时自动隐藏
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
| `ALERT_WEBHOOK` | 独立告警机器人，业务机器人挂掉时告警还能发出去 | 可选 |
| `ALERT_SECRET` | 告警机器人签名密钥（未配时回落 `FEISHU_SECRET`） | 可选 |

变量名与 [BIGApush](https://github.com/Wind866/BIGApush) 完全一致，**直接复用同一个机器人即可**，不用新建。

本地测试：

```bash
export FEISHU_WEBHOOK="https://open.feishu.cn/open-apis/bot/v2/hook/xxx"
python scripts/notify_feishu.py --dry-run            # 预览卡片
python scripts/notify_feishu.py --no-ledger          # 实际发送（不写台账）
python scripts/notify_feishu.py --force              # 已推送也强制再发
```

### 推送可靠性（照 BIGApush 的实战结论做的）

| 机制 | 解决什么 |
| --- | --- |
| 加签 + **业务码校验** | 机器人开加签后飞书返回 `{"code":19021}` 但 HTTP 仍是 200，只看 HTTP 会误判成功，告警就此静默。现在 19021 / 19024 会打印可照做的提示 |
| 网络重试 | 飞书偶发 502 / 连接重置，自动重试 2 次（4xx 不重试，重试无意义） |
| **多档 cron 兜底** | GitHub `schedule` 实测延迟 4h 以上、偶有整档丢弃；主档 16:40 之后每 2 小时补一档，铺到 +6h |
| **推送台账** `.push-state/ledger.json` | 补档会重复推同一档期，按 `workflow+日期+档期` 判重；**推成功才记账**，失败留给下一档重试 |
| 交易日预检 | 节假日不把昨天的榜单再推一遍（akshare 交易日历，取不到时退化为工作日判断） |
| 失败告警 | 任务失败 / 被取消时发到告警机器人，附 run 链接 |

## 部署到 GitHub

```bash
git init && git add . && git commit -m "init: A股事件筛选器"
git remote add origin https://github.com/<你的用户名>/astock-screener.git
git push -u origin main
```

推送后：

1. **Settings → Pages → Source 选 GitHub Actions**，`pages.yml` 会把整个仓库作为静态站点发布，地址形如 `https://<用户名>.github.io/astock-screener/`
2. 把这个地址填到 `PAGE_URL` Secret，飞书卡片即可一键跳转
3. `daily.yml` 自动采集→推送→回写 `data/` 与台账；也可在 Actions 页面手动 Run（勾 `force` 可强制重推）

> CI（`ci.yml`）会在每次 push 时跑守护测试：**扫描是否误提交了真实 webhook**、数据结构是否合法、外部数据归一化是否回归、工作流 YAML 是否可解析。

## 接入你已有的项目数据

不用改旧项目代码，把它的输出 JSON 丢进 `data/extra/` 就会被自动识别并并入事件表（每日定时任务也会带上）。

```bash
cp /path/to/旧项目/dist/ledger.json data/extra/
python scripts/merge_extra.py --dry-run   # 先看识别结果
python scripts/merge_extra.py             # 确认后写回 data/latest.json
```

识别规则（`scripts/merge_extra.py`）：

| 能力 | 说明 |
| --- | --- |
| 结构 | 顶层数组、`{"events"/"items"/"rows"/"data"/"list": [...]}`、日期分组的字典 |
| 字段 | 中英文别名模糊匹配：代码/名称/股东/数量/金额/占比/公告日期/进度/备注…… |
| 类型 | 优先取 `type` 字段，否则按关键词推断（增持/减持/定增/回购/分红，含英文） |
| 单位 | 金额默认按万元；字符串自带 `亿/万/元` 自动折算；整体单位可用 `--amount-unit yuan\|auto` 调整 |
| 去重 | 按 类型+代码+日期+主体+数量 生成指纹，重复运行不会重复入库 |

常见坑：金额字段若是「元」，加 `--amount-unit yuan`（或写进 `config.json` 的 `extraAmountUnit`）；分红行的股息率若存成小数（`0.0287`）会自动转成 `2.87%`。合并后的条目在前端「状态」列显示为「外部数据」，来源显示「外部项目」，方便和数据源数据区分。

## 配置（config.json）

```json
{
  "lookbackDays": 90,      // 采集回看窗口
  "maxEvents": 2000,       // 数据文件事件上限
  "minAmountWan": 0,       // 全局金额下限（万元）
  "extraAmountUnit": "wan", // data/extra 里金额字段的单位：wan / yuan / auto
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
│   ├── extra/               # 旧项目/外部 JSON 投喂目录
│   └── history/             # 每日快照与索引
├── .push-state/ledger.json  # 推送幂等台账（需提交，跨运行共享）
├── scripts/
│   ├── collectors.py        # 五类事件采集与归一化
│   ├── fetch_data.py        # 采集入口（--demo / --days）
│   ├── fetch_selection.py   # 拉取 BIGApush 选股池（选股 × 事件交叉）
│   ├── merge_extra.py       # 外部 JSON 归一化与合并
│   ├── feishu_webhook.py    # 飞书发送层（加签/重试/业务码校验）
│   ├── notify_feishu.py     # 事件卡片推送
│   ├── push_ledger.py       # 推送幂等台账
│   ├── is_trading_day.py    # 交易日预检
│   ├── alert.py             # 失败告警
│   └── demo_data.py         # 离线演示数据
├── tests/test_guardrails.py # webhook 泄露扫描 / 数据结构 / 归一化回归
├── .github/workflows/
│   ├── daily.yml            # 多档 cron 采集 + 推送 + 台账 + 告警
│   ├── pages.yml            # GitHub Pages 部署
│   └── ci.yml               # 守护测试
└── config.json              # 运行配置
```

## 免责声明

本项目仅聚合公开信息，数据可能延迟或有口径差异，请以交易所公告为准；不构成任何投资建议。
