-- Theoretical index backtest schema. Existing index and signal tables are reused.
CREATE TABLE IF NOT EXISTS t_backtest_run (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  index_id BIGINT UNSIGNED NOT NULL,
  strategy VARCHAR(8) NOT NULL,
  execution_mode VARCHAR(24) NOT NULL DEFAULT 'INDEX_THEORETICAL',
  start_date DATE NOT NULL,
  end_date DATE NOT NULL,
  initial_capital DECIMAL(20,6) NOT NULL,
  parameters JSON NOT NULL,
  signal_algorithm_version VARCHAR(32) NOT NULL DEFAULT '1.0',
  data_version VARCHAR(64) NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'QUEUED',
  error_message TEXT NULL,
  summary JSON NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  finished_at DATETIME(3) NULL,
  PRIMARY KEY (id),
  CONSTRAINT fk_backtest_run_index FOREIGN KEY (index_id) REFERENCES t_index_info(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS t_backtest_order (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  run_id BIGINT UNSIGNED NOT NULL,
  trade_id BIGINT UNSIGNED NULL,
  signal_id BIGINT UNSIGNED NOT NULL,
  side VARCHAR(8) NOT NULL,
  order_type VARCHAR(24) NOT NULL,
  trade_date DATE NOT NULL,
  trigger_price DECIMAL(20,6) NOT NULL,
  fill_price DECIMAL(20,6) NOT NULL,
  quantity DECIMAL(28,8) NOT NULL,
  notional DECIMAL(20,6) NOT NULL,
  fee DECIMAL(20,6) NOT NULL DEFAULT 0,
  slippage DECIMAL(20,6) NOT NULL DEFAULT 0,
  reason VARCHAR(64) NOT NULL,
  PRIMARY KEY (id),
  KEY idx_backtest_order_run (run_id),
  CONSTRAINT fk_backtest_order_run FOREIGN KEY (run_id) REFERENCES t_backtest_run(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS t_backtest_trade (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  run_id BIGINT UNSIGNED NOT NULL,
  signal_id BIGINT UNSIGNED NOT NULL,
  entry_date DATE NOT NULL,
  exit_date DATE NULL,
  entry_price DECIMAL(20,6) NOT NULL,
  exit_price DECIMAL(20,6) NULL,
  quantity DECIMAL(28,8) NOT NULL,
  initial_stop DECIMAL(20,6) NOT NULL,
  exit_reason VARCHAR(64) NULL,
  gross_pnl DECIMAL(20,6) NULL,
  net_pnl DECIMAL(20,6) NULL,
  total_fee DECIMAL(20,6) NOT NULL DEFAULT 0,
  total_slippage DECIMAL(20,6) NOT NULL DEFAULT 0,
  return_ratio DECIMAL(12,6) NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'OPEN',
  PRIMARY KEY (id),
  KEY idx_backtest_trade_run (run_id),
  CONSTRAINT fk_backtest_trade_run FOREIGN KEY (run_id) REFERENCES t_backtest_run(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS t_backtest_equity (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  run_id BIGINT UNSIGNED NOT NULL,
  trade_date DATE NOT NULL,
  cash DECIMAL(20,6) NOT NULL,
  position_value DECIMAL(20,6) NOT NULL,
  total_equity DECIMAL(20,6) NOT NULL,
  net_value DECIMAL(20,8) NOT NULL,
  benchmark_net_value DECIMAL(20,8) NOT NULL,
  drawdown DECIMAL(12,8) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_backtest_equity_run_date (run_id, trade_date),
  CONSTRAINT fk_backtest_equity_run FOREIGN KEY (run_id) REFERENCES t_backtest_run(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
