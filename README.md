# A股事件筛选器

<p>
  <img alt="CI" src="https://img.shields.io/github/actions/workflow/status/Wind866/astock-screener/ci.yml?label=CI">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.11-3776AB">
  <img alt="License" src="https://img.shields.io/badge/License-MIT-3DA639">
  <img alt="Push" src="https://img.shields.io/badge/push-Feishu-00B0F0">
</p>

> 把 A 股的**股东增减持、定增、回购、分红**四类公告采集下来，做成一个手机/电脑自适应的静态看板，每工作日 20:33（北京时间）更新并推送飞书。

看板：<https://wind866.github.io/astock-screener/>

![看板预览](docs/preview.png)

## 它做什么

- **五类事件统一成一张表**：增持 / 减持 / 定增 / 回购 / 分红，按公告日倒序，金额统一换算成万元。
- **每天算出「新增事件」**：与上一份快照做 id 差分，飞书卡片只列当天新出现的条目，不重复刷屏。
- **可选交叉选股池**：拉到 BIGApush 的收盘选股结果后，前端会多一个「只看选股池内」的筛选维度；拉不到就自动隐藏，不影响主流程。
- **纯静态交付**：数据写成 `data/latest.js`，双击 `index.html` 也能打开，不需要后端。

## 快速开始

### 1. 拿到代码

```bash
git clone https://github.com/Wind866/astock-screener.git
cd astock-screener
```

必须包含隐藏目录 `.github/workflows/`，否则定时任务不会生效。

### 2. 配置 Secrets

飞书群 → 添加自定义机器人 → 记下 Webhook（开了「加签」就连密钥一起记下）。
仓库 **Settings → Secrets and variables → Actions** 添加：

| Secret | 必填 | 用途 |
| --- | --- | --- |
| `FEISHU_WEBHOOK` | 是 | 业务机器人 Webhook |
| `FEISHU_SECRET` | 否 | 业务机器人加签密钥，开启加签时必填 |
| `PAGES_URL` | 建议 | 看板地址，用于卡片按钮跳转（旧名 `PAGE_URL` 仍兼容） |
| `ALERT_WEBHOOK` | 建议 | 独立告警机器人，业务通道故障时仍能报警 |
| `ALERT_SECRET` | 否 | 告警机器人加签密钥，未配时回落 `FEISHU_SECRET` |

### 3. 打开 Pages

**Settings → Pages → Source** 选择 **GitHub Actions**；
**Settings → Actions → Workflow permissions** 选择 **Read and write**（工作流要把数据提交回仓库）。

### 4. 手动验证一次

**Actions → 每日事件采集与飞书推送 → Run workflow**。首次跑通即写入 `data/latest.json` 与当日快照。

## 运行节奏

| 北京时间 | 任务 | 触发方式 |
| --- | --- | --- |
| 20:33（工作日） | 采集 + 推送 + 回写数据 | BIGApush 的 Cloudflare Worker 派发 `daily.yml` |
| 21:33 / 22:33 / 23:33 | cron 兜底 | GitHub 定时，按「运行当日 + slot=2033」台账判重 |

- 准点调度统一在 [BIGApush 的 Worker](https://github.com/Wind866/BIGApush/tree/main/cloudflare)；仓库内 `schedule` 只作兜底，且全部收敛在当天——台账按运行日期记档期，跨午夜会被算成新档重复推送。
- `daily.yml` 内置 deploy job：用 `GITHUB_TOKEN` 产生的提交不会触发 `pages.yml`，所以数据回写后必须在同一 run 内重新发布 Pages。
- 非交易日由 `scripts/is_trading_day.py` 直接跳过，不会推昨天的榜单。

## 目录结构

```text
index.html           看板入口（单页，无构建）
assets/              app.js / styles.css
scripts/
  collectors.py      四类事件采集（akshare）
  fetch_data.py      主流程：采集 → 归一化 → 去重 → 写 latest + 历史快照
  fetch_selection.py 拉 BIGApush 选股池（可选，失败静默降级）
  merge_extra.py     并入外部 JSON（data/extra/*.json）
  notify_feishu.py   飞书卡片推送
  push_ledger.py     推送幂等台账
  is_trading_day.py  交易日闸门
  alert.py           失败告警
data/
  latest.json/.js    最新数据（js 版供 file:// 直接打开）
  history/           每日快照 + index.json（保留最近 180 份）
  extra/             外部 JSON 投喂位
docs/                预览图、BIGApush 联动说明
.github/workflows/   ci.yml / daily.yml / pages.yml
```

## 本地开发

```bash
pip install -r requirements.txt

python scripts/fetch_data.py            # 真实数据（需要联网）
python scripts/fetch_data.py --demo     # 演示数据，验证前端
python -m http.server 8000              # 起本地服务看页面
python -m unittest discover -s tests    # 守护测试
```

## 数据口径与已知上限

| 项 | 说明 |
| --- | --- |
| 回看窗口 | `config.json` 的 `lookbackDays`，默认 90 天 |
| 事件上限 | `maxEvents` 默认 5000 条，按公告日倒序截断。90 天四类事件实测约 3167 条，正常不会触发；真触发时日志会打 warning，此时「数据源」那行报的采集条数与列表实际条数会不一致 |
| 金额 | 统一换算为万元；外部投喂的 JSON 由 `extraAmountUnit` 指定原始单位 |
| 快照保留 | 最近 180 个交易日，超出自动清理 |

## 安全说明

- Webhook 与加签密钥**只**通过 Secrets / 环境变量提供；`config.json` 里的 `feishu.pageUrl` 是唯一允许入库的展示类配置。
- CI 内置 webhook 泄露扫描（`tests/test_guardrails.py::test_no_real_webhook_committed`），误提交会直接判红。
- 加签要么两个机器人都开，要么都不开：只开一半会导致业务推送与告警**同时静默**。
- 未配置 Webhook 时任务判红，不会把「没推送」记成成功。
- 所有 Action 固定到 commit SHA，并由 dependabot 每周提升级 PR。

## 排错

| 症状 | 原因 | 处理 |
| --- | --- | --- |
| 看板 404 | Pages Source 未选 GitHub Actions | 改完要重新 Run，不能用旧 run 的 Re-run |
| 收到重复卡片 | `.push-state/ledger.json` 被清除或未提交 | 台账跨运行共享，必须随快照一起提交 |
| 接口取数失败 | 上游字段/接口变更 | 先 `--demo` 验前端，再排查 akshare 版本是否被改动 |
| 卡片没有跳转按钮 | 未配 `PAGES_URL` | 补配（旧名 `PAGE_URL` 仍生效） |
| 收不到失败告警 | 只配了业务机器人 | 单独配 `ALERT_WEBHOOK` |

## 相关文档

- [与 BIGApush 选股池联动接入](docs/bigapush-integration/README.md)
- [统一调度 Worker](https://github.com/Wind866/BIGApush/tree/main/cloudflare)

## 免责声明

本工具仅用于信息聚合与研究复盘，不构成投资建议。数据来自公开接口，可能存在延迟、缺失或口径差异。市场有风险，投资需谨慎。

## License

MIT
