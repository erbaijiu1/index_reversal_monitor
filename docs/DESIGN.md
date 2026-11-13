# 指数周线量价反转监控系统 — 详细设计 V1.0

> 状态：Codex 实施基线（2026-11-10）  
> 部署宿主：`/data/toc_service`，复用现有 Docker Compose `include` / `web` 网络 / Nginx / MySQL。  
> 范围：指数、行业、概念板块；**不含个股，不做自动交易**。  
> 核心：一根**周阳线实体完整吞没之前连续相邻的 N 根周 K 线实体**，被吞没的 K 线可阴阳交错，满足明确的下跌背景，成交量仅用于评级；**最新未完成周线可作为预警，完成后才能确认**。

## 0. 实施边界和优先级

1. 本文定义本业务逻辑、数据表、API、任务、测试与新增部署内容。**现有 `/data/toc_service/README.md` 为基础设施最高优先级**；不复制或改造既有 Nginx、MySQL、Redis、SSL 等基础设施。
2. V1 必做：指数维护、数据源适配/探测、历史及每日 OHLCV 同步、周线聚合（包含未完成本周）、形态扫描、历史信号、可视化、预警/确认、通知去重、管理接口、基础测试、部署文档。
3. V1 不做：MACD/均线筛选、个股、自动交易、实时逐笔行情、复杂组合回测；后续可扩展向下吞没。
4. 数据源文档**仅证明接口存在，不证明目前在部署机可用**。任何指数正式启用前必须做连接测试、字段/单位校验、历史深度和连续性验证。
5. 不向 Git 提交真实数据库密码、消息凭据、生产 env；不把当前基础设施 README 中的明文敏感参数复制到业务项目。

## 1. 产品目标与术语

### 1.1 使用场景

- 监控中证主要消费、恒生指数、中证机器人、沪深300，以及可配置的行业/概念板块。
- 周一至周四（或当周尚未结束时）已满足形态，显示/提醒“**反转形成中**”。
- 本周最后一个交易日行情采集完成后，重新确认“**反转已确认**”；若不再满足，留存预警记录并标记“**预警失效**”。
- 可以回看某指数历史所有信号，周 K 图标示每次信号、实际吞没根数、下跌背景、突破与量能情况。
- 通知仅作为研究观察线索，不输出交易建议、目标价或收益承诺。

### 1.2 状态定义

- `FORMING`：本周尚未完整结束；截至数据截止时间满足规则。
- `CONFIRMED`：本周的完整有效交易日数据已确认、满足规则。
- `INVALIDATED`：本周曾触发 FORMING，随后重新计算不满足规则，或周收盘形态失败。
- `DATA_PENDING`：当前行情缺失、数据源异常、交易日尚未完成；不按“未形成信号”处理。
- `NONE`：行情完整且未识别到形态。

周中最新价依赖当前交易日已完成日线或经核验的最新行情快照；**V1 默认只在交易日收盘后扫描**，因此“未完成周线”指周一至周四及非最后交易日收盘后的周线，不保证盘中实时预警。日内快照扩展留后续版本。

## 2. 量价形态规则（单一权威规范）

### 2.1 K 线定义

对于当前周 `K0=(O0,H0,L0,C0,V0)`，之前周按时间倒序为 `K1,K2,...,Kn`：

- 阳线：`C > O`；阴线：`C < O`；十字/平盘：`C == O`。
- 实体下边界：`body_low(K)=min(O,C)`；实体上边界：`body_high(K)=max(O,C)`。
- 历史 K1…Kn 必须是连续的**交易周**，可以包含阴线、阳线、十字星；不可跳过任意一周选取“有利”的 K 线。
- 缺少交易的完整自然周无需生成空 K 线；但不能跨越数据缺失周将不完整数据当成连续有效数据。

### 2.2 硬条件

1. `K0` 阳线：`C0 > O0`。
2. 当前周实体完整覆盖被识别区间内每一根 K 线的实体（允许边界相等）：
   `O0 <= min(body_low(Ki), i=1..N)` 且 `C0 >= max(body_high(Ki), i=1..N)`。
3. `N >= 2`，K1..KN 时间相邻，无跳选；中途**允许夹杂阳线，且夹杂阳线也必须被实体完全吞没**。
4. 在 K1..KN 内，阴线根数 `bearish_count >= 2`。
5. 下跌背景：`close(KN) > close(K1)`，即**最早的那周收盘价严格高于最近一周收盘价**。
6. K1..KN 都为已经完成的周线；K0 可为本周部分周线或完成周线；数据质量状态必须合格。

### 2.3 N 的确定（避免歧义）

- 从 K1 向历史扫描，逐根验证**该根 K 线的整个实体是否包含在 K0 实体内**；遇到第一根不能完整吞没的 K 线或缺失/不可验证数据立即停止。这得到最大连续可吞没长度 `M`（最多 `max_lookback_weeks`，默认 26）。
- 对所有 `N=2..M` 计算阴线数量与下跌背景，得到合法集合 `S`。
- `S` 非空则取 **最大的合法 N**，保存为 `engulfed_count`。`S` 为空则无信号。
- 保存 `max_engulfable_count=M`，便于解释为什么曾吞没更多 K 线，但最后只记为“一阳吞 N 线”。
- **不能**从窗口中任意选择不相邻的 2 根阴线形成信号；**不能**将“前 N 周总体下跌，本周收复跌幅”替代实体覆盖条件。

特别说明：若 N=2，且至少 2 根阴线，那么最早与最近一周收盘价是否下降仍须独立验证；仅仅两阴并不足以成立。

### 2.4 数值判定

- 原始行情用 DECIMAL 存库（建议 `DECIMAL(20,6)`）；计算保持 Decimal/数值精度，避免二进制浮点比较误差。
- 不设置任意百分比容差；“边界相等”按数据源返回的标准化价格精度比较。价格精度/单位变更须标记数据源变更并重跑。
- OHLC 必须满足 `H >= max(O,C)`、`L <= min(O,C)`、`H >= L`、价格为正；若异常拒绝本周形态判断。

### 2.5 量能评分（不是硬过滤）

用同一指数、同一供应商、同一单位口径的可比**完整周**成交量：

`volume_ratio_5 = V0 / average(V1..V5)`。

- `V1..V5` 需全部可用、非负且均值 > 0；否则量能状态=`UNAVAILABLE`。
- 量能等级：`<0.8` 缩量；`[0.8,1.2)` 常规；`[1.2,1.5)` 温和放量；`>=1.5` 显著放量。
- 对**部分周 K0**，累计量 `V0` 与 5 周平均**完整周**成交量之比只作 `cumulative_volume_ratio`，不可当成已完周量比。
- 周中另提供交易日进度调整量比：`pace_ratio = (V0 / completed_sessions_current_week) / (sum(Vj / sessions_j, j=1..5)/5)`，必须满足历史 5 周都完整且交易日数量已知。此项是按交易日均量比较的预测性指标，不代表最终放量结论。
- 若有有效港股指数成交额，但无成交量，可**独立**用成交额计算 `amount_ratio_5` / `amount_pace_ratio` 并标记 `volume_basis=AMOUNT`；不得跨口径拼接。
- 若标准指数无可信量能/成交额，可保留价格形态，`volume_basis=NONE`、等级=`UNAVAILABLE`；不能伪造 0 或借用无解释的 ETF 成交量。

### 2.6 信号分级与标签

- `BASE`：全部硬条件满足。
- `VOLUME_CONFIRMED`：确认的完整周线量/额比 `>=1.2`。
- `STRONG`：确认的完整周线量/额比 `>=1.5` **且** `C0 > max(H1..HN)`（严格高于此前 N 周所有最高价）。
- `BREAKOUT`：突破最高价的独立布尔标签；周中可计算但标为“暂态”。
- 周中始终带 `FORMING` 主状态，可根据 `pace_ratio` 显示“进度放量参考”，**不可称为已确认放量**。
- 如果未提供量能且价格强势突破，保持 `BASE + BREAKOUT + UNAVAILABLE`，不伪装成 STRONG。

### 2.7 示例及反例

- 早→晚：`阴, 阳, 阴, 阴`，当前大阳完全吞没 4 根实体，阴线 >= 2、首尾收盘下降 ⇒ “一阳吞4线”。
- 早→晚：`阴, 阴, 阳`，虽然都被吞没，但首周收盘价 <= 末周收盘价 ⇒ **当前 N=3 不合法**；只有其他合法 N 才可记信号。
- 当前大阳吞没 K1、K2，**没吞没 K3**，但吞没 K4 ⇒ 最多 M=2，不得跳过 K3。
- 当前周只有长上影线越过旧实体，但 `C0 < max(body_high(K1..KN))` ⇒ 不成立。
- 当前周未完成且今天收阳，次日回落至不满足 ⇒ FORMING → INVALIDATED；不应误记 CONFIRMED。
- 两根阴线没有实现首尾收盘下降 ⇒ 不成立。

## 3. 数据源与指数清单

### 3.1 源接入原则

- 先做 **source probe**：选取固定日期区间请求样本，验证真实返回数据、字段、日期、价格、量单位、历史长度、限流和近期更新时间；通过后才启用指数。
- 数据提供商接入抽象接口：`list_instruments()`（可选）、`get_daily_ohlcv(instrument,start,end)`、`get_quote_snapshot()`（V1 可不实现）、`probe()`。
- 必须有标准化映射：`index_code`（内部业务代码）、`market`（CN/HK）、`provider`（akshare_csindex/akshare_em_index/akshare_em_board/akshare_hk_index 等）、`provider_symbol`、`instrument_type`。
- 只按**确实可用**的历史/日线接口写入库，不承诺所有指数代码都能在同一种 API 内使用。明确记录价格、成交量和成交额的实际来源与单位。

### 3.2 候选接口（必须实测）

| 类别 | 优先验证的 Python AKShare 接口 | 注意 |
|---|---|---|
| 中证标准指数 | `stock_zh_index_hist_csindex(symbol,start_date,end_date)` | 可返回日线 OHLC，文档列有成交量（万手）及成交金额（亿元）；可用性逐指数核对。 |
| A 股常见指数 | `index_zh_a_hist(symbol,period='daily',start_date,end_date)` | 东财常见指数接口，成交量文档单位“手”、成交额“元”；校验覆盖范围。 |
| 东财概念板块 | `stock_board_concept_hist_em(symbol,period='日k',start_date,end_date,adjust='')` | 参数可能依具体 AKShare 版本而变化；读取当前安装版本签名。 |
| 东财行业板块 | `stock_board_industry_hist_em(symbol,period='日k',start_date,end_date,adjust='')` | 同上；板块代码应持久化，不仅保存名称。 |
| 港股指数 | `stock_hk_index_daily_em(symbol)` | 公开源代码表明只整理 `date/open/high/low/latest`，**无可靠成交量**；作为价格行情候选。 |
| 港股指数备份 | `stock_hk_index_daily_sina(symbol)`（若当前版本提供） | 探测可用性和历史深度；不要将港股个股接口 `stock_hk_hist` 误用于指数。 |

接口参考：
- AKShare 指数说明：https://github.com/akfamily/akshare/blob/main/docs/data/index/index.md
- 中证指数日线接口：https://akshare-hh.readthedocs.io/en/latest/data/index/index.html
- 港股指数实现：https://github.com/akfamily/akshare/blob/main/akshare/index/index_stock_hk.py
- 板块实现：https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_board_industry_em.py

**注意：** 上述是候选而不是已在生产主机验证成功的接口。Codex 应实现 `probe_sources` 命令并输出逐指数验证表，不通过则保留为 `DISABLED/PENDING_SOURCE`，不可默默生成空数据。

### 3.3 建议初期观察名单

- 中证主要消费 `000932`（CN/标准指数）
- 中证可选消费 `000931`（CN/标准指数）
- 沪深300 `000300`（CN/宽基）
- 中证500 `000905`（CN/宽基）
- 中证机器人 `H30590`（CN/主题；核验当前准确代码和供应商支持）
- 恒生指数 `HSI`（HK/宽基；必须探测实际 provider symbol）
- 恒生科技指数 `HSTECH`（HK/主题；必须探测实际 provider symbol）
- 东财“机器人概念”“食品饮料”等（CN/板块；从板块列表接口获取当前代码，不写死）

名单是初始化候选，不要求每个数据源都在 V1 支持；页面需显示“可用 / 数据不足 / 数据源失败 / 未验证”的状态。

### 3.4 质量控制

- 日线主键业务唯一：`instrument_id + trade_date`；先校验再 upsert。
- 明确 CN 使用 `Asia/Shanghai`，HK 使用 `Asia/Hong_Kong`；交易日历独立，处理节假日、临时休市、半日交易。
- 最新**已完成交易日**以交易所日历和安全延时判断，防止在收盘前把当日残缺行情记成正式日线。
- 周区间采用**当地自然周的周一日期**作 `week_start`；用该市场本周实际交易日组成周线。
- 周 OHLCV：周开=首个交易日开盘；周高=日高最大值；周低=日低最小值；周收=最后已取到交易日收盘；周量/额=当周有效日线累计。
- 周线 `is_complete=true` 要同时满足：已到该市场本周最后一个交易日收盘+延时；该周所有应有交易日数据完整；无未解决的数据异常。
- 每日重拉最近 10～20 个交易日（可配置）核对历史修订；发现历史变动时重算受影响的周和信号，标记 `recomputed_at`。
- 禁止混合不同提供商的价格和量能；切源须记录口径变化并决定是否重建历史。
- 每次采集保存运行日志和异常类型（超时、空响应、字段变化、限流、日期断档、单位不一致、港股无量）。

## 4. 数据库设计（MySQL 8 / 兼容性以现场数据库版本为准）

建议独立 schema `db_index_reversal`、独立最小权限账号；沿用现有 `mysql_db:3306`，不创建新数据库容器。数据库字符集 `utf8mb4`；所有日期以 DATE 存储，时间戳建议存 UTC 的 DATETIME(3) 并在 API 返回 ISO8601 时区信息。

### 4.1 完整建表 DDL

```sql
CREATE DATABASE IF NOT EXISTS db_index_reversal
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE db_index_reversal;

CREATE TABLE t_index_info (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  index_code VARCHAR(40) NOT NULL COMMENT '内部代码，如 CN:000932/HK:HSI',
  index_name VARCHAR(100) NOT NULL,
  market VARCHAR(8) NOT NULL COMMENT 'CN/HK',
  instrument_type VARCHAR(20) NOT NULL COMMENT 'BROAD/INDUSTRY/THEME/CONCEPT',
  provider VARCHAR(40) NOT NULL,
  provider_symbol VARCHAR(80) NOT NULL,
  data_status VARCHAR(24) NOT NULL DEFAULT 'PENDING_SOURCE',
  volume_basis VARCHAR(12) NOT NULL DEFAULT 'NONE' COMMENT 'VOLUME/AMOUNT/NONE',
  volume_unit VARCHAR(30) DEFAULT NULL,
  amount_unit VARCHAR(30) DEFAULT NULL,
  price_precision TINYINT UNSIGNED NOT NULL DEFAULT 4,
  enabled TINYINT(1) NOT NULL DEFAULT 0,
  last_success_date DATE DEFAULT NULL,
  last_error VARCHAR(500) DEFAULT NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_index_code (index_code),
  KEY idx_enabled_market (enabled,market)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE t_index_daily (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  index_id BIGINT UNSIGNED NOT NULL,
  trade_date DATE NOT NULL,
  open_price DECIMAL(20,6) NOT NULL,
  high_price DECIMAL(20,6) NOT NULL,
  low_price DECIMAL(20,6) NOT NULL,
  close_price DECIMAL(20,6) NOT NULL,
  volume DECIMAL(28,6) DEFAULT NULL,
  amount DECIMAL(28,6) DEFAULT NULL,
  session_complete TINYINT(1) NOT NULL DEFAULT 1,
  data_source VARCHAR(40) NOT NULL,
  fetched_at DATETIME(3) NOT NULL,
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_daily (index_id,trade_date),
  KEY idx_daily_date (trade_date),
  CONSTRAINT fk_daily_index FOREIGN KEY(index_id) REFERENCES t_index_info(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE t_index_weekly (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  index_id BIGINT UNSIGNED NOT NULL,
  week_start DATE NOT NULL COMMENT '市场当地时间周一',
  first_trade_date DATE NOT NULL,
  last_trade_date DATE NOT NULL,
  open_price DECIMAL(20,6) NOT NULL,
  high_price DECIMAL(20,6) NOT NULL,
  low_price DECIMAL(20,6) NOT NULL,
  close_price DECIMAL(20,6) NOT NULL,
  volume DECIMAL(28,6) DEFAULT NULL,
  amount DECIMAL(28,6) DEFAULT NULL,
  actual_sessions SMALLINT UNSIGNED NOT NULL,
  expected_sessions SMALLINT UNSIGNED NOT NULL,
  is_complete TINYINT(1) NOT NULL DEFAULT 0,
  data_revision INT UNSIGNED NOT NULL DEFAULT 1,
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_weekly (index_id,week_start),
  KEY idx_weekly_week (week_start),
  CONSTRAINT fk_weekly_index FOREIGN KEY(index_id) REFERENCES t_index_info(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE t_index_monitor_config (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  config_name VARCHAR(80) NOT NULL,
  enabled TINYINT(1) NOT NULL DEFAULT 1,
  timeframe VARCHAR(12) NOT NULL DEFAULT '1w',
  min_engulfed_count SMALLINT UNSIGNED NOT NULL DEFAULT 2,
  min_bearish_count SMALLINT UNSIGNED NOT NULL DEFAULT 2,
  max_lookback_weeks SMALLINT UNSIGNED NOT NULL DEFAULT 26,
  volume_lookback_weeks SMALLINT UNSIGNED NOT NULL DEFAULT 5,
  volume_warm_ratio DECIMAL(8,4) NOT NULL DEFAULT 1.2000,
  volume_strong_ratio DECIMAL(8,4) NOT NULL DEFAULT 1.5000,
  enable_forming_alert TINYINT(1) NOT NULL DEFAULT 1,
  enable_confirmed_alert TINYINT(1) NOT NULL DEFAULT 1,
  config_version INT UNSIGNED NOT NULL DEFAULT 1,
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_config_name (config_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE t_index_reversal_signal (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  index_id BIGINT UNSIGNED NOT NULL,
  week_start DATE NOT NULL,
  direction VARCHAR(8) NOT NULL DEFAULT 'UP',
  algorithm_version VARCHAR(32) NOT NULL,
  config_version INT UNSIGNED NOT NULL,
  status VARCHAR(20) NOT NULL COMMENT 'FORMING/CONFIRMED/INVALIDATED',
  engulfed_count SMALLINT UNSIGNED NOT NULL,
  max_engulfable_count SMALLINT UNSIGNED NOT NULL,
  bearish_count SMALLINT UNSIGNED NOT NULL,
  previous_first_close DECIMAL(20,6) NOT NULL,
  previous_last_close DECIMAL(20,6) NOT NULL,
  breakout_high TINYINT(1) NOT NULL DEFAULT 0,
  volume_basis VARCHAR(12) NOT NULL DEFAULT 'NONE',
  volume_ratio DECIMAL(12,5) DEFAULT NULL COMMENT '仅完整周',
  cumulative_volume_ratio DECIMAL(12,5) DEFAULT NULL,
  pace_ratio DECIMAL(12,5) DEFAULT NULL,
  volume_level VARCHAR(20) NOT NULL DEFAULT 'UNAVAILABLE',
  signal_level VARCHAR(24) NOT NULL DEFAULT 'BASE',
  current_open DECIMAL(20,6) NOT NULL,
  current_close DECIMAL(20,6) NOT NULL,
  quote_asof DATETIME(3) NOT NULL,
  first_detected_at DATETIME(3) NOT NULL,
  confirmed_at DATETIME(3) DEFAULT NULL,
  invalidated_at DATETIME(3) DEFAULT NULL,
  recomputed_at DATETIME(3) DEFAULT NULL,
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_signal (index_id,week_start,direction,algorithm_version,config_version),
  KEY idx_signal_status_week (status,week_start),
  CONSTRAINT fk_signal_index FOREIGN KEY(index_id) REFERENCES t_index_info(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE t_index_alert_log (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  signal_id BIGINT UNSIGNED NOT NULL,
  alert_phase VARCHAR(20) NOT NULL COMMENT 'FORMING/CONFIRMED/INVALIDATED',
  channel VARCHAR(24) NOT NULL,
  dedupe_key VARCHAR(180) NOT NULL,
  delivery_status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
  attempt_count SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  last_error VARCHAR(500) DEFAULT NULL,
  sent_at DATETIME(3) DEFAULT NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uk_dedupe (dedupe_key),
  KEY idx_alert_retry (delivery_status,created_at),
  CONSTRAINT fk_alert_signal FOREIGN KEY(signal_id) REFERENCES t_index_reversal_signal(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE t_index_job_run (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  job_type VARCHAR(40) NOT NULL,
  run_key VARCHAR(100) NOT NULL,
  status VARCHAR(16) NOT NULL,
  started_at DATETIME(3) NOT NULL,
  finished_at DATETIME(3) DEFAULT NULL,
  processed_count INT UNSIGNED NOT NULL DEFAULT 0,
  success_count INT UNSIGNED NOT NULL DEFAULT 0,
  failure_count INT UNSIGNED NOT NULL DEFAULT 0,
  error_summary TEXT,
  UNIQUE KEY uk_job_run (job_type,run_key),
  KEY idx_job_status (status,started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**DDL 设计备注：**
- “新业务独立 schema + 账号”不需要改主 MySQL 容器；账号权限仅授予 `db_index_reversal.*`。账号创建可由管理员单独执行，密码从 `/data/toc_service/env/index_reversal.env` 读取，不写入脚本/文档。
- `quote_asof` 当前为 UTC，无时区 DATETIME 需在应用严格统一约定。
- `t_index_reversal_signal` 保留本周最终/当前状态；FORMING 变 INVALIDATED 要保存事件历史时，可增加 `t_index_signal_event`（V1 建议实现，见下一节）。
- 如果重算后“曾确认的历史信号消失”，不能静默删库：需变更状态或记数据修订原因，并记录审计；可根据需要增加 `RETRACTED` 状态。
- 若相同信号跨参数版本变化，新版使用 `config_version` 新键重新计算；不可覆写旧版本历史。

### 4.2 建议补充的信号状态事件表

```sql
CREATE TABLE t_index_signal_event (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  signal_id BIGINT UNSIGNED NOT NULL,
  old_status VARCHAR(20) DEFAULT NULL,
  new_status VARCHAR(20) NOT NULL,
  event_type VARCHAR(30) NOT NULL COMMENT 'DETECTED/UPDATED/CONFIRMED/INVALIDATED/RETRACTED',
  event_payload JSON DEFAULT NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  KEY idx_signal_event (signal_id,created_at),
  CONSTRAINT fk_signal_event_signal FOREIGN KEY(signal_id) REFERENCES t_index_reversal_signal(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

## 5. 后端 API 设计

统一前缀：`/index-reversal/api/v1`。响应格式建议：`{ "code": 0, "message": "ok", "data": ..., "request_id": "..." }`；失败返回适合的 HTTP 状态码及业务错误码。前端和管理接口沿用现有网关方式访问。

| 方法 | 路径 | 功能 |
|---|---|---|
| GET | `/indices` | 分页检索：market/type/name/enabled/data_status；附最新周线状态/信号摘要。 |
| POST | `/indices` | 添加指数、provider 映射；默认不启用，须 probe 成功。 |
| PATCH | `/indices/{id}` | 修改监控状态、名称、数据源配置。 |
| POST | `/indices/{id}/probe` | 校验供应商及历史数据字段、日期与量能。 |
| GET | `/indices/{id}/candles?period=1w&start=&end=` | 周 K + 量柱 + `is_complete`、量能口径。 |
| GET | `/indices/{id}/signals?start=&end=&status=` | 单指数历史信号，供 K 线标记。 |
| GET | `/signals?week=&market=&level=&status=&min_engulfed_count=` | 全市场信号列表、分页筛选。 |
| GET | `/signals/{id}` | 形态解释：吞没 K 线范围、阈值、量比与价格明细。 |
| GET | `/overview` | 监控总数、数据源异常数、形成中/已确认数、最近信号。 |
| GET | `/config` | 查询当前全局规则与版本。 |
| PUT | `/config` | 更新规则并递增 `config_version`，不就地覆盖旧版信号。 |
| POST | `/jobs/probe-sources` | 执行数据源探测（管理员）。 |
| POST | `/jobs/backfill` | 发起历史补数（参数 index_ids/start/end）。 |
| POST | `/jobs/scan` | 发起指定日期/指数扫描（支持 dry_run）。 |
| GET | `/jobs` | 运行记录与失败详情。 |
| GET | `/alerts` | 通知日志与发送状态。 |
| POST | `/alerts/{id}/retry` | 仅重试失败通知，不产生新去重键。 |
| GET | `/health` | liveness。 |
| GET | `/ready` | 检查 MySQL + 必要运行配置，不依赖行情站点短时可用性。 |

### 5.1 API 示例

`GET /index-reversal/api/v1/signals?status=FORMING&market=CN&page=1&page_size=20`

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "items": [
      {
        "id": 123,
        "index_code": "CN:000932",
        "index_name": "中证主要消费",
        "week_start": "2026-11-09",
        "status": "FORMING",
        "engulfed_count": 3,
        "bearish_count": 2,
        "breakout_high": false,
        "volume_basis": "VOLUME",
        "pace_ratio": 1.34,
        "volume_ratio": null,
        "signal_level": "BASE",
        "quote_asof": "2026-11-10T08:00:00Z"
      }
    ],
    "total": 1,
    "page": 1,
    "page_size": 20
  },
  "request_id": "example-only"
}
```

> 仅为字段结构样例，不代表该指数对应日期真实存在信号。

### 5.2 安全与可用性

- 读接口可按项目实际需要设置访问控制；所有写接口、任务触发及通知重试**必须鉴权**（管理员身份/现有认证网关），不可公网裸露。
- API 入参校验：分页上限 <= 200；历史回填最大跨度可限制；日期区间和指数 ID 必须合法。
- 手动同步/扫描采用任务表或异步作业响应 `202 Accepted`，避免长 HTTP 阻塞；同一 `run_key` 不并发执行。
- 由后端代理拉取行情，不允许前端指定任意 URL，以免 SSRF。
- 所有 API 使用参数化 SQL、最小权限数据库用户；日志隐藏凭据。

## 6. 前端设计（Vue3 + Vite，可用 uni-app H5；以轻量方案为主）

生产入口：`https://www.yjhcai.cn/index-reversal/`（主域名是否有 www 取决于现网，最终以既有 Nginx server_name 为准）。构建静态资源前缀 `/index-reversal/`，由共享 Nginx 托管，不新建前端服务容器。

### 6.1 页面

1. **监控总览 `/index-reversal/`**：监控指数数、当周 FORMING/CONFIRMED、数据源告警；市场/类型筛选、关键词检索、按信号最近时间排序。重要展示 `截至日期`、`是否完整周`。
2. **信号列表 `/index-reversal/signals`**：时间范围、形成中/确认/失效、吞没根数、量能等级筛选；支持跳转详情。
3. **指数详情 `/index-reversal/indices/:id`**：周 K + 成交量/成交额副图；叠加信号标记；鼠标/触摸展示每周 OHLC、完成状态、量比和形态解释；历史信号表。图表推荐 ECharts candlestick/bar，体积可接受，按需加载。
4. **指数管理 `/index-reversal/settings/indices`**：新增/修改代码、市场、来源、启用状态；数据源 probe 状态及最后更新时间。
5. **规则与任务 `/index-reversal/settings/rules`**：N、历史扫描深度、量比阈值、预警通知开关；任务日志/失败记录。

### 6.2 界面细节

- `FORMING`：橙色/中性“形成中”；`CONFIRMED`：绿色“已确认”；`INVALIDATED`：灰色“预警失效”。不要将部分周当已确认展示。
- 成交量缺失时显示“量能不可验证”，图上不能画 0 量柱误导用户。
- 只有实际有量/额源且单位一致时显示量比。
- 图表默认展示最近 104 周；支持缩放历史、点击标记查看计算依据。
- 移动端 H5 基础适配；无需第一期做小程序。

## 7. 调度任务与通知

### 7.1 任务表

| 任务 | 建议频率（市场当地时间） | 行为 |
|---|---|---|
| 初始历史补数 | 新指数通过 probe 后一次性 | 下载 3–5 年（能取多少以实际为准），校验后生成周线并扫历史。 |
| 日线同步 | CN 工作日 16:30 后；HK 工作日 17:30 后 | 对监控指数批量采集，失败退避重试；时刻可配置。 |
| 周线增量更新 | 日线采集成功后紧随执行 | 更新最近若干周 K 和状态；校验该周交易日完整度。 |
| 形态扫描 | 每次周线更新成功后 | 包含本周部分周线：形成中、变更、失效；最后交易日确认。 |
| 补偿任务 | 每日夜间（市场本地时区） | 对照日历补缺日、重扫受影响区间。 |
| 通知发送 | 有待发送事件时立即或每 1–5 分钟 | 去重、失败重试、记录结果。 |
| 周收盘确认兜底 | 本周最后交易日数据同步完成后 | 统一确认所有指数；只对本周有数据的指数处理。 |

**任务依赖**：采集成功 → 聚合成功 → 扫描成功 → 出通知事件；任何一步异常时不误发“无信号”。

### 7.2 通知规则

- 同指数、同周、同算法版本+参数版本、同通知渠道：`FORMING` 首次满足只提醒 1 次；`CONFIRMED` 正式成立再提醒 1 次。
- 如果此前 FORMING 后最终失败，数据库必须记 `INVALIDATED`；**默认不推失效消息**（可以在页面查看），未来可配置。
- 如果本周周三第一次触发，周四暂时失效，周五又触发：仍不重复发送 `FORMING`，但周五满足并完整则推 `CONFIRMED`。
- 去重键建议 `signal_id + phase + channel`；消息重试沿用同一个键。通知成功后重放任务也不可重复发送。
- 数据修订导致历史信号撤销时保留审计，不自动补发旧日期通知。
- 消息模板包含指数名/代码、周区间、形成中或确认、实际吞没根数、阴线根数、首尾收盘变化、量能口径/进度量比、是否突破高点、数据截至日期和详情链接。
- V1 先做 `WebhookNotifier`（基于现有可用通知服务的 webhook 或企业微信机器人），未配置通知凭据时仍可页面使用、写通知待配置状态。避免给未确认渠道硬编码密钥。

### 7.3 并发与幂等

- 调度服务**单独进程/容器**，不能同时在多个 Uvicorn/Gunicorn worker 内启动 APScheduler。
- 单机一个 scheduler 副本；`t_index_job_run` `run_key` 保证任务去重，还需数据库/应用锁避免竞态；崩溃中的 RUNNING 超时可恢复。
- 行情抓取限速、超时、指数级重试/退避和随机抖动。给不同来源独立并发上限。
- 写入原始日线、周线和信号使用 upsert；信号事务内写状态事件与待发送通知，保证事件不丢失。
- 通知送达可能存在“成功发送但来不及更新数据库”的不可消除重复风险；外部渠道若支持幂等 ID 就透传 `dedupe_key`，否则说明采用尽力去重。

## 8. 推荐代码目录

```text
index_reversal_monitor/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app
│   │   ├── core/                   # config/db/logger/auth
│   │   ├── api/v1/                 # indices, candles, signals, jobs, config
│   │   ├── models/                 # SQLAlchemy ORM
│   │   ├── schemas/                # Pydantic I/O
│   │   ├── data_sources/           # base, csindex, eastmoney, hk
│   │   ├── services/               # collect, aggregate, scan, notify
│   │   ├── patterns/               # engulfing.py (纯函数)
│   │   ├── scheduler/              # jobs / locks / runner
│   │   └── backtest/               # 预留扩展
│   ├── tests/
│   ├── requirements.txt           # 固定/锁定版本
│   └── Dockerfile
├── frontend/                      # Vue3+Vite 或 uni-app H5
├── sql/001_init.sql
├── deploy/docker-compose.yml
├── docs/DESIGN.md
├── .env.example
└── README.md
```

重点：`patterns/engulfing.py` 是无数据库和网络依赖的纯函数，接受按日期排序的周 K 与参数，输出 `MatchResult | None`；前端和调度绝不复制一份独立计算逻辑。

## 9. 与现有 `/data/toc_service` 的业务部署增量

> **只增加本业务文件**；不改既有服务、不重复创建 MySQL/Nginx/Redis；网络名称由根 Compose 合并，遵照现有 README。实际路径可定为 `/data/toc_service/index_reversal_monitor`，以减少对 `toCom` 其他业务的耦合。

### 9.1 新增文件（宿主路径）

```text
/data/toc_service/
├── index_reversal_monitor/
│   ├── deploy/docker-compose.yml
│   ├── backend/...
│   ├── frontend/...
│   ├── sql/001_init.sql
│   ├── docs/DESIGN.md
│   ├── .env.example
│   └── README.md
├── env/index_reversal.env                   # 真正配置，仅宿主，chmod 600
├── nginx/locations/index-reversal.conf      # 新增网关
├── dist/index_reversal/                     # 前端打包产物
└── server_data/index_reversal/logs/         # 业务可变日志（可选）
```

### 9.2 子 Compose（示例，可交 Codex 落地）

子文件在 `index_reversal_monitor/deploy/docker-compose.yml`，相对路径因此从 `deploy/` 开始解析。现有 `web` 网络由根 Compose 通过 include 合并，**不在子文件声明外部网络**。

```yaml
services:
  index_reversal_api:
    build:
      context: ../backend
      dockerfile: Dockerfile
    image: index-reversal-api:1.0
    container_name: index_reversal_api
    restart: unless-stopped
    env_file:
      - /data/toc_service/env/index_reversal.env
    environment:
      APP_ROLE: api
    volumes:
      - ../backend/app:/app/app:ro
      - /data/toc_service/server_data/index_reversal/logs:/app/logs
    networks:
      - web
    expose:
      - "8080"
    # 不映射公网端口；通过共享 nginx_proxy 访问

  index_reversal_scheduler:
    image: index-reversal-api:1.0
    container_name: index_reversal_scheduler
    restart: unless-stopped
    command: ["python", "-m", "app.scheduler.runner"]
    env_file:
      - /data/toc_service/env/index_reversal.env
    environment:
      APP_ROLE: scheduler
    volumes:
      - ../backend/app:/app/app:ro
      - /data/toc_service/server_data/index_reversal/logs:/app/logs
    networks:
      - web
```

注意：示例假定 Dockerfile 默认 `WORKDIR /app` 且启动 API 命令已在镜像中定义。首次构建后，纯 `app/` 源码修改可以分别 `docker compose restart index_reversal_api index_reversal_scheduler`；修改 requirements/Dockerfile/镜像时必须重新 build。生产环境若更改镜像 tag，两个服务应共同更新。日志可统一 stdout，由 Compose 查阅；如果不用文件日志可删除 `logs` bind mount。

### 9.3 主 Compose 接入（只增一条 include）

在 `/data/toc_service/docker-compose.yml` 原有 `include:` 列表加入：

```yaml
  - ./index_reversal_monitor/deploy/docker-compose.yml
```

**此处是配置片段，不要覆盖已有 include 列表。**

### 9.4 Nginx 新增 location

创建 `/data/toc_service/nginx/locations/index-reversal.conf`，放在现有主 Nginx 已 include 的 HTTPS server 内，**不复制 server、SSL、监听和已有兜底路由**：

```nginx
# API 优先于静态资源；尾斜杠保证 upstream 路由为 /index-reversal/api/...
location ^~ /index-reversal/api/ {
    proxy_pass http://index_reversal_api:8080/index-reversal/api/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_connect_timeout 5s;
    proxy_read_timeout 60s;
}

# 静态页面；先确保共享 nginx 容器已把宿主 dist 根目录挂到 /usr/share/nginx/html
location ^~ /index-reversal/ {
    alias /usr/share/nginx/html/index_reversal/;
    index index.html;
    try_files $uri $uri/ /index-reversal/index.html;
}
```

前端 Vite `base='/index-reversal/'`；若用 Vue Router history mode，上述 `try_files` 应在上线前用任意深链（例如 `/index-reversal/signals`）进行容器内 curl 测试。若采用 uni-app hash 路由则无需 history fallback 复杂度。不要因为本业务修改其他 Nginx 业务路由。

### 9.5 环境变量模板

只提交 `.env.example`：

```dotenv
APP_ENV=production
APP_HOST=0.0.0.0
APP_PORT=8080
DB_HOST=mysql_db
DB_PORT=3306
DB_NAME=db_index_reversal
DB_USER=index_reversal_app
DB_PASSWORD=REPLACE_IN_HOST_ENV_ONLY
TZ=Asia/Shanghai
SCHEDULER_ENABLED=true
COLLECT_CN_AFTER=16:30
COLLECT_HK_AFTER=17:30
MAX_LOOKBACK_WEEKS=26
VOLUME_LOOKBACK_WEEKS=5
VOLUME_WARM_RATIO=1.2
VOLUME_STRONG_RATIO=1.5
ALERT_WEBHOOK_URL=
ALERT_WEBHOOK_TOKEN=
ADMIN_API_TOKEN=REPLACE_IN_HOST_ENV_ONLY
```

`DB_PASSWORD` 和管理员 Token 需实际生成并且只保存到 `/data/toc_service/env/index_reversal.env`，`chmod 600`；`/data/toc_service/env` 建议 `chmod 700`。生产环境应复用现有鉴权能力；示例 Token 只作为最低限度备选方案，不得放前端源码。

### 9.6 上线顺序（不影响其他容器）

1. 创建业务目录、env 文件和日志目录；新建独立数据库及最小权限账号。
2. 执行 `sql/001_init.sql`；运行 `probe_sources`，将不可用指数保持禁用。
3. 加主 Compose `include`，先运行 `docker compose config --quiet` 校验（在 `/data/toc_service` 下）。
4. `docker compose build index_reversal_api index_reversal_scheduler`；`docker compose up -d index_reversal_api index_reversal_scheduler`。
5. 构建前端并将生产构建产物放至 `/data/toc_service/dist/index_reversal/`。
6. 检查 Nginx 容器确实挂载了新的 dist 目录；新增 Nginx location；执行 `docker exec nginx_proxy nginx -t` 后 `docker exec nginx_proxy nginx -s reload`。
7. 检查 `/index-reversal/api/v1/health`、`/ready`、静态首页、深链以及 MySQL 连通性。
8. 先补历史数据、人工核对 2～3 次历史形态；再打开正式通知发送。

**风险提示**：现有 Nginx 是否已挂载 `dist/` 根目录，需实际检查；如果未挂载，应通过现有根 Compose 的 Nginx 卷配置作**最小增量调整**，不得假定新建宿主 `dist/index_reversal/` 后容器立刻可见。

## 10. 测试验收清单（要求 Codex 实现）

### 10.1 识别单测

- 当前阴线、十字星 → 无信号。
- 相邻 2 阴且实体全吞没、首尾下跌 → BASE。
- `阴-阳-阴-阴` 全实体吞没、至少2阴、首尾下跌 → 正确识别 4 线。
- 中途阳线实体有任何部分不被吞没 → 在该 K 处停止，不跨过继续扫描。
- `M=5` 但 `N=5` 不满足首尾下降，而 `N=3` 满足 → 返回 3，且 `max_engulfable_count=5`。
- K0 刚好与过去实体上下边界相等 → 允许。
- K0 仅上影突破但收盘未越过过去实体顶部 → 不成立。
- 两阴但首尾下跌不满足 → 不成立。
- 无成交量/成交额 → 保留价格信号、量能不可验证；不能除零。
- 未完成周线满足 → FORMING；完成后仍满足 → CONFIRMED；完成后不满足 → INVALIDATED。
- 非交易周/节假日周、缺失交易日、周五假期、半日交易、历史数据更正、源切换后量能单位变化。

### 10.2 API / 调度 / 部署验收

- `GET /candles` 正确区分完整周/部分周，正确返回最近日线截至日。
- 全局配置调整生成新 `config_version`，不污染老信号。
- 同一周同一个信号的 3 次重复扫描只生成 1 条 `FORMING` 提醒；完成确认后最多再 1 条 `CONFIRMED`。
- 发送失败重试，不丢事件、不重复新增日志；任务中断后可恢复。
- 数据采集失败不可当作无信号；页面显示数据不完整状态。
- 代码通过纯函数单测和数据库集成测试；新增服务不会创建第二个 MySQL/Nginx。
- 前端页面、K线和量能指标正常；无量指数不显示虚假量比。
- Nginx 静态首页/子路径刷新/API/鉴权校验成功；容器中 `mysql_db` 可解析。

## 11. Codex 分步实施任务（推荐顺序）

1. 创建项目骨架、文档、SQL、环境配置、健康检查、Dockerfile/Compose（不要碰既有其他服务）。
2. 实现源适配和 `probe_sources`；输出指数支持矩阵及样例数据校验报告，禁止在 probe 前批量启用。
3. 实现日线入库、市场日历、周线聚合、完整性校验、增量回补、失败任务记录。
4. **先写形态识别纯函数与测试用例**；以本文第2节为唯一判断标准。
5. 实现信号落库、状态迁移、事件历史与通知幂等。
6. 实现 FastAPI 读写接口、管理员权限、请求校验。
7. 实现前端总览、K线详情、信号列表、配置/数据状态页面。
8. 实现独立 scheduler 容器与通知适配器；用模拟 webhook 测试形成中/确认/失效。
9. 按第9节嵌入 `/data/toc_service` 共享基础设施，上线后先关通知进行历史比对。

## 12. 交付物要求

Codex 最终交付：

- 可运行完整源码、固定依赖、`Dockerfile`、业务子 `deploy/docker-compose.yml`、`.env.example`。
- `sql/001_init.sql` 和必要迁移脚本；无硬编码生产密码。
- `docs/DESIGN.md`（本设计实现版）、`README.md`（仅本业务运行/部署增量，不复制主 README）。
- 数据源探测命令与真实运行结果报告（哪些指数有 OHLC、哪些有量/额、哪些无法取得）。
- 完整接口 OpenAPI、前端构建脚本、基本单测、样例数据和验收命令。
- 明确列出 V1 未解决的问题，尤其港股量能口径、个别主题指数覆盖范围和公开数据源稳定性。

---

## 13. 必须注意的三个实现决定

1. **吞没判定统一**：前 N 根可以阴阳交错，但每根都必须被当前阳线**实体完整吞没**，并且从 K1 连续向前计算，不跳选。
2. **下跌背景强制**：合法 N 内至少 2 阴、最早一周收盘价 > 最近一周收盘价；从所有可吞没连续区间中选**最大合法 N**。
3. **本周允许未完成**：周中只发 FORMING，收盘才 CONFIRMED；量能周中使用进度口径，不将累计量误记为完整周放量。

以上三条优先于先前任何草稿中的“连续阴线”“只吞没阴线”“不允许未完成周线”等定义。
