# CAP/GDP 宏观估值配置策略（隔离功能）

## 边界

参考仓库：`erbaijiu1/stock_monitor`，但不复制其存在未来可知性与成交同日问题的回测逻辑。

新增模块为 `backend/app/macro/`，独立于形态识别 `services/pattern.py` 及原 `backtest/`。

- **数据同步**：`sync.py` 由本项目独立访问上交所/深交所公开市场数据及 AKShare GDP 数据；交易日期取本项目已经同步的指数日线，原始数据单独入库。
- **指标计算**：`indicator.py` 只根据原始市值与 GDP 重算 X，产生确定性的阶梯仓位。
- **回测**：`backtest.py` 独立账户，T 收盘信号、下一交易日开盘成交，含费用滑点；指数理论执行，非真实 ETF 成交。

## 数据口径与严肃限制

`X = 沪深两市股票总市值（亿元） / 上一年度名义 GDP（亿元）`。

独立抓取的宏观历史数据，但未证明历史数据属于 **point-in-time** 口径。GDP 可能事后修订，且年初上一年度完整 GDP 披露前不能先知。当前同步保留 `RETROSPECTIVE_GDP` 标签，并默认 **禁止直接拿未经验证的历史数据运行回测**；显式设置探索模式仅适合研究，不能用于实盘绩效声明。

总市值/GDP 是整个A股的宏观指标，不能解释为沪深300成分股市值/GDP。沪深总市值可能因为 IPO、上市公司数量和统计范围变化而漂移，固定阈值需要跨时期复核。

## API

统一前缀：`/index-reversal/api/v1/macro`。

| Method | Path | 用途 |
|---|---|---|
| POST | /sync | 从交易所与 GDP 数据源独立采集原始数据，需传 `calendar_index_id` |
| POST | /indicators/recalculate | 计算并持久化 CAP/GDP |
| GET | /indicators | 查看比例和仓位映射 |
| POST | /backtests | 独立宏观仓位回测 |
| GET | /backtests | 查看回测结果 |
| GET | /backtests/{id}/equity | 日级净值与仓位 |
| GET | /backtests/{id}/trades | 逐笔调仓审计记录 |

写操作需要现有 `X-Admin-Token`。

### 数据与部署隔离

**不再使用 `MACRO_CAP_GDP_SOURCE_URL`，也不读取 `stock_monitor` 的数据库。**

此策略数据全部存放在 `index_reversal_monitor` 自身的数据库（默认可用 `db_index_reversal`）。不必再部署第二套 MySQL 服务；需要隔离的是逻辑库、表及数据同步任务。

独立源：

- 上交所：公开市场概貌接口，提取“股票”总市值
- 深交所：AKShare `stock_szse_summary(date=YYYYMMDD)`，提取“股票”总市值
- GDP：AKShare `macro_china_gdp()`，取完整年度 GDP 总量
- 交易日：本项目 `t_index_daily` 内的完整日线日期

所有总市值、GDP 统一为“亿元”口径。交易所字段或单位发生变化时，宁可拒绝该日期，不做猜测换算。

GDP 按保守启用月份规则选取历史年度：当年 1—2 月使用前两年年度 GDP，3 月起可使用上一年 GDP。**这只是规避明显提前引用的近似规则，历史 GDP 修订仍会影响回测**，数据标记 `RETROSPECTIVE_GDP`。因此未经发布时点及数据版本校验，仍须显式允许探索性回测。

使用 `sql/macro_cap_gdp.sql` 建表；当前仅支持手动同步，不与原周线监控调度混合。

调用 `POST /sync` 的请求体示例：

```json
{
  "start_date": "2026-11-01",
  "end_date": "2026-11-27",
  "market": "CN-A",
  "calendar_index_id": 1
}
```

这里的 `calendar_index_id` 必须是已经同步日线的指数 ID（如沪深300），用于确定实际交易日；不是原项目的数据库 ID。

执行顺序：

1. POST /sync
2. POST /indicators/recalculate
3. GET /indicators
4. POST /backtests；历史数据未经时间点校验时，需 `allow_unverified_history=true`，仅供探索性回测

## 默认仓位参数

- 最低/中性/最高仓位：20% / 40% / 100%
- 买入档：X < 0.60, 0.55, 0.50, 0.45, 0.40；几何系数 2
- 卖出档：X >= 0.70, 0.75, 0.80, 0.85, 0.90
- 买卖非对称，采用无记忆目标仓位映射
- 手续费 0.03%，滑点 0.05%，现金年化默认 0（作为可配置假设）
- 指标 T 收盘后确定，T+1 开盘交易；未处理交易所 ETF 份额、流动性、分红追踪误差

## 验证与后续

已包含仓位计算、未来价格时序和费用测试。

第一版是**独立、可复查的宏观信号实验模块**，不是可以直接实盘的系统。要升级为可交易回测，必须实现：GDP 历史公布时间/修订版本、ETF 真实价格和分红、交易日历、源数据版本快照、资金对账与样本外检验。

严禁直接把探索性年化收益宣传为可交易收益。

## 当前实现状态与待验收项

- 已添加前端导航“CAP/GDP宏观估值”，可独立同步、计算、回测并查看净值及成交。
- 原主程序引用了 GitHub 当前分支未追踪的 `price_center` 包；启动逻辑已改为只有该包确实缺失时跳过其路由，避免阻塞其他模块。此兼容处理不代表价格中枢模块已恢复。
- 当前宏观回测是 **指数理论回测**；ETF 真实交易、交易日历和GDP公布时点审计尚未完成。不要据此判断已经可以实盘执行。
- 当前同步为显式手动调用，不接入原周线监控定时调度。应先验证交易所和GDP接口可靠性，再加入独立宏观同步任务。
- 尚未在真实 MySQL、官方源 / GDP 接口及前端构建环境执行端到端集成测试。提交前应运行 `pytest backend/tests/test_macro.py`（在适当 PYTHONPATH 环境），检查 SQL 与 ORM 一致并完成服务启动验证。
