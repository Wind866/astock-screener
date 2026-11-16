# 把 BIGApush 的选股结果接进事件筛选器

> **状态：已接入**（2026-11-16）。`Wind866/BIGApush` 的 `main` 已包含 `scripts/export_selection.py`
> 与 `selection.yml` 的导出步骤（提交 `6158566`，CI 通过）。截图器侧零配置，等 BIGApush 下一次
> 收盘选股（北京 19:33）跑完，`exports/selection-latest.json` 一出现，表格里就会自动出现 `⌖` 徽标。
> 下面的步骤留作换仓库 / 重新搭建时的参考。

事件面（增减持/定增/回购/分红）和选股面（15 种形态策略）在两边各算各的，
接起来才有「**这只票今天形态突破，同时大股东在增持**」这种交叉信号。

```
BIGApush 收盘选股 ──► data/stock_selection.db ──► export_selection.py
                                                    │
                                          exports/selection-latest.json（提交到 BIGApush）
                                                    │  raw.githubusercontent.com
                                                    ▼
                                    astock-screener ──► fetch_selection.py
                                                    └─► 表格标注 / 只看选股池 / 详情抽屉
```

原因：BIGApush 的 `data/stock_selection.db` 靠 `actions/cache` 持久化，**不在 git 里**，
所以需要它每天主动导出一个 JSON；筛选器只认这个 JSON，两边不耦合。

## 三步接上

### 1. 复制导出脚本

```bash
# 在 BIGApush 仓库根目录
mkdir -p scripts exports
cp <本目录>/export_selection.py scripts/export_selection.py
```

`.gitignore` 里 `data/` 被忽略，但 `exports/` 不在忽略范围内，无需改动。本地先验一次：

```bash
python scripts/export_selection.py
cat exports/selection-latest.json | head -20
```

### 2. 在 `.github/workflows/selection.yml` 末尾加一步

放在「运行收盘选股并推送」之后、失败告警之前：

```yaml
      - name: 导出选股结果（供事件筛选器联动）
        if: steps.trading.outputs.is_trading == 'true' || inputs.force == true
        run: |
          python scripts/export_selection.py
          if [ -f exports/selection-latest.json ]; then
            git config user.name "github-actions[bot]"
            git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
            git add exports/selection-latest.json
            if git diff --cached --quiet; then
              echo "选股结果无变化"
            else
              git commit -m "data: 选股结果 $(TZ=Asia/Shanghai date +%F)" --no-verify
              git push
            fi
          fi
```

`selection.yml` 已有 `permissions: contents: write`，能直接推。

### 3. 筛选器侧什么都不用改

`astock-screener/config.json` 已指向：

```
https://raw.githubusercontent.com/Wind866/BIGApush/main/exports/selection-latest.json
```

改名或换仓库时改这一行即可。本地联调可把 JSON 放到 `data/extra/selection.json`，
`fetch_selection.py` 会优先读本地文件。

## 联动后能看到什么

| 位置 | 表现 |
| --- | --- |
| 表格「名称」列 | 该股在选股池时显示 `⌖` 徽标，悬停看命中策略数 |
| 左侧筛选 | 「只看选股池内」开关 |
| 详情抽屉 | 单独一块「选股信号」：策略名、评分、排名、选入价、行业/板块 |
| KPI | 命中事件里有多少只同时在选股池 |

## 字段约定

筛选器只依赖这几个字段，导出脚本已按此产出：

```json
{
  "source": "BIGApush",
  "asOf": "2026-11-16",
  "count": 12,
  "picks": [
    {
      "code": "600519", "name": "贵州茅台", "date": "2026-11-16",
      "strategies": ["启明星", "碗口反弹"], "strategyCount": 2,
      "score": 85.5, "rank": 1, "price": 1680.5,
      "industry": "白酒", "sector": "消费"
    }
  ]
}
```

拿不到这个文件时（还没接、或当天没跑），筛选器自动隐藏选股维度，其余功能不受影响。
