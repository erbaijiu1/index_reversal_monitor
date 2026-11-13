-- Upgrade databases created by the initial backtest draft.
-- Run once before deploying the V1.1 application. Fresh installs only need backtest.sql.
ALTER TABLE t_backtest_run
  ADD COLUMN data_version VARCHAR(64) NULL AFTER signal_algorithm_version;

-- Kept nullable so historical draft orders without a trade link remain readable.
ALTER TABLE t_backtest_order
  ADD COLUMN signal_id BIGINT UNSIGNED NULL AFTER trade_id;

ALTER TABLE t_backtest_trade
  ADD COLUMN total_fee DECIMAL(20,6) NOT NULL DEFAULT 0 AFTER net_pnl,
  ADD COLUMN total_slippage DECIMAL(20,6) NOT NULL DEFAULT 0 AFTER total_fee;

ALTER TABLE t_backtest_equity
  ADD COLUMN benchmark_net_value DECIMAL(20,8) NULL AFTER net_value;
UPDATE t_backtest_equity SET benchmark_net_value = net_value WHERE benchmark_net_value IS NULL;
ALTER TABLE t_backtest_equity
  MODIFY COLUMN benchmark_net_value DECIMAL(20,8) NOT NULL;
