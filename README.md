# 指数周线量价反转监控系统

适用范围：指数、行业、概念板块。不监控个股，不自动下单。

## 核心规则

当前周阳线实体必须完整覆盖前方相邻连续 N 根周 K 线的实体（N>=2），中间可以夹杂阳线，但都要完整吞没；前 N 根至少两根阴线，最早一周的收盘价严格高于最近一周。量能仅评级，周中未收盘为 FORMING、收盘后为 CONFIRMED，未成立为 INVALIDATED。

具体以 `docs/DESIGN.md` 为准。`backend/app/services/pattern.py` 是纯规则实现；`backend/tests/test_pattern.py` 覆盖主要边界。

## 本地验证

```bash
cd backend
python3.11 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=sqlite:///./local.db
uvicorn app.main:app --reload --port 8096
python -m app.cli seed
python -m app.cli probe
pytest -q
```

注意：seed 只生成**未启用**的候选指数；probe 不会自动启用。必须在实际部署机确认 provider symbol、接口返回、行情历史深度与成交量口径后，再正式启用。

前端：`cd frontend && npm install && npm run dev`，生产执行 `npm run build`。完整输出目录为 `frontend/dist/`。

## 接入现有 `/data/toc_service`

本项目只新增业务文件，严格以宿主 `/data/toc_service/README.md` 为基础设施规范。

1. 项目放在 `/data/toc_service/index_reversal_monitor/`。
2. 创建独立 MySQL schema `db_index_reversal`、最小权限用户；先执行 `sql/schema.sql`，再执行 `sql/backtest.sql` 和 `sql/price_center_v1.sql`；启用宏观估值模块时另执行 `sql/macro_cap_gdp.sql`。**不要在生产环境同时执行已有 schema SQL 和 ORM 自动迁移**，后续表改动用显式迁移。
   如果数据库已安装过早期回测草稿表，则不要重复执行 `backtest.sql`，先执行一次 `sql/backtest_v1_1_migration.sql`；所有已存在的回测数据库升级日线信号功能时，再执行一次 `sql/backtest_v1_2_daily_signal_migration.sql`。
   已安装价格中枢 V1 表但缺少份额折算取整字段时，执行一次 `sql/price_center_v1_1_share_change.sql`。
3. 新建 `/data/toc_service/env/index_reversal.env`，参照 `backend/.env.example`，权限 `chmod 600`。
4. **将 `deploy/docker-compose.yml` 复制到项目根目录**作为业务子 Compose（它的相对路径以项目根目录为准）。主 Compose `include:` 只新增 `./index_reversal_monitor/docker-compose.yml`。
5. 将 `deploy/index-reversal.conf` 复制到 `/data/toc_service/nginx/locations/index-reversal.conf`，检查共享 Nginx 的 `/usr/share/nginx/html` 是否正确挂载根目录 `dist/`。
6. `cd frontend && npm ci && npm run build`，把 `frontend/dist/` 文件内容复制到 `/data/toc_service/dist/index_reversal/`。
7. 在 `/data/toc_service` 执行 `docker compose config --quiet`，再 `docker compose build index_reversal_backend`、`docker compose up -d index_reversal_backend index_reversal_scheduler`。
8. Nginx `nginx -t` 通过再 reload；检查 `/index-reversal/api/v1/health` 和前端入口。
9. 后端容器执行 `python -m app.cli seed`、`python -m app.cli probe`，然后有选择地启用探测成功的指数，回填历史、扫描和核对样本。

### 部署重要限制

- 业务不创建任何公共 MySQL / Nginx / Redis 容器。
- Docker Compose 采用共享 `web` 网络；调度器仅一个实例。
- Python 应用使用源码只读挂载；依赖镜像固定版本。
- 管理 API 使用 `X-Admin-Token` 作为最小认证机制。公网部署时**应额外通过现有 Nginx / 内网访问策略限制管理路径**，不建议仅凭静态 Token 暴露高权限接口。
- 当前通知以通用 webhook POST `{"text":"..."}` 发送，需要按企业微信/其他渠道的真实格式进行适配和实测。不开启 `ALERT_ENABLED` 不会发送。
- 上线前需验证交易日历、港股半日市与特殊休市；当前周线正式确认采取谨慎策略（交易周最后一个交易日之后），不会在收盘当日即时确认。

## 主要端点

- `GET /index-reversal/api/v1/indices`、`GET /overview`、`GET /signals`
- `POST /index-reversal/api/v1/backtest/runs` 创建异步指数回测，`GET /backtest/runs/{id}` 查询状态
- 回测信号支持周线吞没、日线吞没和 `BREAKOUT_PULLBACK` 日线底部放量突破后回踩；后者等待回踩确认后再于下一交易日入场，以减少追高和交易次数。
- `GET /index-reversal/api/v1/backtest/runs/{id}/equity|trades|orders` 查询净值、交易和成交明细
- `GET /index-reversal/api/v1/backtest/compare?run_ids=1&run_ids=2` 对比回测任务
- `GET /index-reversal/api/v1/price-center/instruments` 查询指数/ETF 映射；`POST /price-center/runs` 创建长期价格中枢回测
- `GET /index-reversal/api/v1/price-center/runs/{id}/monthly|trades|equity` 查询月度决策、真实 ETF 成交和每日净值
- `GET /indices/{id}/candles?period=1w`、`GET /indices/{id}/signals`
- 管理（Header: `X-Admin-Token`）：`POST /indices`、`PATCH /indices/{id}`、`POST /indices/{id}/probe`、`POST /jobs/backfill`、`POST /jobs/scan`、`PUT /config`
- 文档：`/index-reversal/api/docs`

## 日线与周线吞没回测

回测请求支持 `signal_period`：`1w`（默认）使用已确认周线监控信号，`1d` 根据完整日 K 即时计算相同的连续实体吞没规则。`entry_timing` 可选 `NEXT_OPEN`（默认，下一交易日开盘）或 `SIGNAL_CLOSE`（信号 K 收盘价研究模拟）；后者依赖收盘数据确认，实际交易可执行性弱于次日开盘模式。`stop_buffer_ratio` 用于把初始止损设置为 `信号 K 最低点 × (1 - 缓冲比例)`，扩大后的止损距离会参与最大止损过滤和风险仓位计算。为避免日线噪声进一步加快退出，B/C 策略的移动止损仍使用完整周线低点。

策略 D 将退出分阶段处理：达到 2R 前不启用移动止损，信号周期收盘跌破原始信号 K 低点则下一交易日退出；达到 2R 时减仓 25% 并把硬止损抬到成本价，剩余仓位仅在完整周收盘跌破此前三根完整周 K 最低点后，于下一交易日退出。

## 长期价格中枢策略

`PRICE_CENTER_RECOVERY` 支持两种参考线：默认 SMA 使用指数完整月线计算 MA12/24/36/60/120；固定对数趋势线则对测试期前的历史月末指数收盘价做对数线性拟合，再将拟合线外推到测试区间。趋势线拟合截止点按测试开始月向前留空 1 年或 2 年，至少需要 60 个拟合月；拟合斜率和截距在测试期冻结，拟合斜率非正时明确失败，不会静默退回 SMA。两种参考线使用相同的偏离度、档位、仓位、执行和费用规则，结果记录趋势线拟合窗口、年化趋势增速和拟合质量，便于区分参考线变化带来的影响。

买入和卖出阶梯均为1至10项的可配置数组，每项包含偏离度和目标仓位。买入偏离度必须逐档降低、目标仓位逐档提高；卖出偏离度必须逐档提高、目标剩余仓位逐档降低，且最后一档必须清仓。卖出后的小幅回落不会自动买回，只有重新跌到买入档位且其目标仓位高于当前仓位时才加仓。每日指数收盘都相对所选参考线判断，订单只在下一只映射 ETF 的可交易日开盘执行，最多等待 5 个 ETF 交易日；状态只在真实成交后改变。结果同时展示平均权益仓位、最高权益仓位和满仓交易日。

决策表只持久化真正触发状态变化的信号及其成交/过期结果，不保存逐日 `NO_ACTION` 或等待重复记录。图表所需的完整指数收盘、中枢和偏离度序列在查看结果时从原始行情即时计算，避免为每个回测任务重复存储数千条相同行情派生数据。

成交与净值使用 ETF 原始日线，不用指数点位替代。现金分红计入现金，已知份额折算会同步调整策略与买入持有基准的持仓份额；当前映射为沪深300→510300、中证500→510500、科创50→588000。同步阶段会拒绝未登记公司行为导致的异常价格跳变，避免把拆分/合并误算成暴涨暴跌。基准与策略从 MA 预热完成后的同一 ETF 交易日开始，现金收益率假设为 0%。

## CAP/GDP 宏观估值与逆周期仓位策略（独立模块）

本分支新增 **CAP/GDP 宏观估值策略**，参考 [stock_monitor](https://github.com/erbaijiu1/stock_monitor) 中的“总市值/GDP → 目标仓位”思路，但**不共享其数据库、不调用其 API，也不依赖其服务运行**。

### 模块划分与数据流

```text
上交所公开市场概貌 ─┐
                    ├─> 独立采集/校验 ─> t_macro_cap_gdp_raw
深交所市场概貌 ─────┤                              │
国家统计局 GDP 数据 ─┘                              ▼
                                      t_macro_cap_gdp_indicator
                                                  │
                                     CAP/GDP 与目标仓位计算
                                                  │
                                                  ▼
                                   宏观仓位回测（独立于形态回测）
                                                  │
                                   任务 / 日净值 / 逐笔成交
```

- **数据同步**：`backend/app/macro/native_source.py`、`sync.py`，分别采集沪深交易所“股票”总市值与年度 GDP；交易日依据本项目已有的指数日线，缺少任一来源时跳过并记录错误，不拼凑数据。
- **指标计算**：`backend/app/macro/indicator.py`，使用 `X = 沪深股票总市值（亿元）/ 上一年度 GDP（亿元）`，单独生成每日宏观估值指标及目标仓位。
- **回测**：`backend/app/macro/backtest.py`，按指标区间动态配置指数理论权益仓位；与原有周线量价形态、价格中枢及 A/B/C/D 回测隔离。
- **数据存储**：所有宏观数据进入 `index_reversal_monitor` 自己的数据库及 `t_macro_*` 表。可以复用服务器上的 MySQL **实例**，但独立使用 `db_index_reversal` 逻辑库，无需另建 MySQL 实例。

### 仓位规则（初始参数）

- 常态目标权益仓位 **40%**，最低 **20%**，最高 **100%**。
- 当 X 低于 **0.60、0.55、0.50、0.45、0.40** 时，按几何权重逐档提高仓位（`buy_ratio=2`）。
- 当 X 达到 **0.70、0.75、0.80、0.85、0.90** 时，分档降低目标仓位。
- 默认按 T 日收盘确认的指标，在下一交易日开盘进行理论调仓；计入模拟手续费及滑点。
- **注意**：本模块当前为**指数理论回测**，不是 ETF 实际可交易回测；不得将模拟成交视为 ETF 实盘收益。

### 启用和操作

1. 先确认本项目已同步沪深300等指数的日线；宏观同步使用所选指数的日线日期确定交易日。
2. 在当前逻辑数据库中执行 `sql/macro_cap_gdp.sql` 创建宏观模块表。
3. 打开前端 **“CAP/GDP宏观估值”** 页面，依次执行 **①同步原始数据 → ②重新计算指标 → ③创建策略回测**。
4. 回测完成后查看账户净值、买入持有基准、目标仓位与成交明细；需要管理权限的操作使用现有 `X-Admin-Token`。

后端 API 前缀：`/index-reversal/api/v1/macro`。

| 方法 | 路径 | 功能 |
|---|---|---|
| POST | `/sync` | 独立采集市场总市值和年度 GDP，传 `start_date`、`end_date`、`calendar_index_id` |
| POST | `/indicators/recalculate` | 由原始数据重算 CAP/GDP |
| GET | `/indicators` | 查询历史指标和目标仓位 |
| POST | `/backtests` | 创建宏观仓位理论回测 |
| GET | `/backtests` | 查询回测历史 |
| GET | `/backtests/{id}/equity` | 查询日级净值与仓位 |
| GET | `/backtests/{id}/trades` | 查询逐笔模拟成交 |

同步请求示例：

```json
{
  "start_date": "2026-11-01",
  "end_date": "2026-11-27",
  "market": "CN-A",
  "calendar_index_id": 1
}
```

`calendar_index_id` 是**本项目**数据库里已同步日线的指数 ID；示例值 `1` 需根据实际数据替换。无需配置 `MACRO_CAP_GDP_SOURCE_URL`。

### 数据可信度与当前限制

- 历史 GDP 源可能包含**事后修订值**。当前保守跳过每年 1—2 月，3 月起才采用上一年度 GDP，但这**不等于**已经核实历史披露日期及版本。
- 采集到的数据标记为 `RETROSPECTIVE_GDP`；未经历史时点审计，默认禁止正式回测，需要显式设置 `allow_unverified_history=true` 才能做探索性研究。
- 尚未完成真实 MySQL、交易所历史接口及前端构建的端到端验收；数据源字段或单位变化需要先核对再使用。
- 宏观同步目前**手动触发**，不混入原周线监控定时任务。后续如需定时同步，应使用独立任务。
- 若要评估真实可交易收益，后续还须引入 ETF 实际行情、交易单位、分红、交易日历及数据版本校验。

更详细的设计、接口与操作说明见 [docs/CAP_GDP_INTEGRATION.md](docs/CAP_GDP_INTEGRATION.md)。

## 已知实施限制

- AKShare 数据源依赖公网，尚未在你的 Debian 主机上实测，候选 provider symbol 需要逐个验证。
- 港股接口可能没有成交量，届时只输出价格形态并标记 `UNAVAILABLE`，不能虚构量能。
- 没有提供实际企业微信机器人 URL，因此通知模块只提供通用 webhook。
- V1 为完整可运行的初版工程，不等于已完成生产环境验收。见 `docs/DESIGN.md` 的验收清单。

## 行情稳定同步策略

- 调度器每天执行一次30天重叠窗口的增量同步；重复日期按唯一键更新，因此可安全重跑，也能补齐数据源延迟发布或短暂漏掉的行情。
- 数据源请求默认指数退避重试3次；单个指数失败只记录该指数错误，不回滚其他指数的成功结果，也不删除既有行情。
- 周K在交易日历覆盖范围内严格按交易所日历判断完整性；超出日历包的未来覆盖范围时，以官方行情实际返回日期为准，且当前周始终保持未完成。
- 沪深300和中证500使用 `akshare_csindex`，量能口径为 `VOLUME`。该官方源可能延迟约1至2个交易日，系统通过每日重叠同步自动追补，不与其他来源拼接同一根K线。
- 指数管理页支持单指数探测、五年补采、历史扫描和启停，并显示日线、周线、信号数量及最后数据日。
