# CAP/GDP 宏观估值配置策略（隔离功能）

## 边界

参考仓库：`erbaijiu1/stock_monitor`，但不复制其存在未来可知性与成交同日问题的回测逻辑。

新增模块为 `backend/app/macro/`，独立于形态识别 `services/pattern.py` 及原 `backtest/`。

- **数据同步**：`sync.py` 从上游 CAP/GDP API 拉原始总市值与上一年度 GDP，原始数据单独入库。
- **指标计算**：`indicator.py` 只根据原始市值与 GDP 重算 X，产生确定性的阶梯仓位。
- **回测**：`backtest.py` 独立账户，T 收盘信号、下一交易日开盘成交，含费用滑点；指数理论执行，非真实 ETF 成交。

## 数据口径与严肃限制

`X = 沪深两市股票总市值（亿元） / 上一年度名义 GDP（亿元）`。

上游 API 当前返回历史快照，但未证明历史数据属于 **point-in-time** 口径。GDP 可能事后修订，且年初上一年度完整 GDP 披露前不能先知。当前同步保留 `UPSTREAM_SNAPSHOT` 标签，并默认 **禁止直接拿未经验证的历史数据运行回测**；显式设置探索模式仅适合研究，不能用于实盘绩效声明。

总市值/GDP 是整个A股的宏观指标，不能解释为沪深300成分股市值/GDP。沪深总市值可能因为 IPO、上市公司数量和统计范围变化而漂移，固定阈值需要跨时期复核。

## API

统一前缀：`/index-reversal/api/v1/macro`。

| Method | Path | 用途 |
|---|---|---|
| POST | /sync | 从 `MACRO_CAP_GDP_SOURCE_URL` 同步原始数据 |
| POST | /indicators/recalculate | 计算并持久化 CAP/GDP |
| GET | /indicators | 查看比例和仓位映射 |
| POST | /backtests | 独立宏观仓位回测 |
| GET | /backtests | 查看回测结果 |
| GET | /backtests/{id}/equity | 日级净值与仓位 |
| GET | /backtests/{id}/trades | 逐笔调仓审计记录 |

写操作需要现有 `X-Admin-Token`。

### 部署环境

在服务环境变量中设置（宿主机服务地址不应写为容器的 127.0.0.1）：

`MACRO_CAP_GDP_SOURCE_URL=http://stock-monitor-service:8888/stock/api/cap-gdp/series`

只填写容器确实可访问、网络与安全边界允许的实际地址，不要直接使用上面的示例占位符。

使用 `sql/macro_cap_gdp.sql` 初始化新表，或在现有 SQLAlchemy 启动建表机制下创建（运行前先检查 MySQL 迁移）。

示例提交同步任务：

```json
{"start_date":"2016-01-01","end_date":"2026-11-27","market":"CN-A"}
```

执行顺序：

1. POST /sync
2. POST /indicators/recalculate
3. GET /indicators
4. POST /backtests：提供 `index_id`、日期范围和执行参数；若历史数据未经时间点校验，须显式 `allow_unverified_history=true` 才能运行探索性回测

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
- 当前同步为显式手动调用，不接入原周线监控定时调度。应先验证数据源可靠性，再加独立宏观同步任务。
- 尚未在真实 MySQL、上游 API 及前端构建环境执行端到端集成测试。提交前应运行 `pytest backend/tests/test_macro.py`（在适当 PYTHONPATH 环境），检查 SQL 与 ORM 一致并完成服务启动验证。
