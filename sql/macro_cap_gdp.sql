-- Isolated CAP/GDP data and backtest tables, MySQL 8+.
CREATE TABLE IF NOT EXISTS t_macro_cap_gdp_raw (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 market VARCHAR(20) NOT NULL, trade_date DATE NOT NULL,
 total_market_cap DECIMAL(24,4) NOT NULL, reference_gdp DECIMAL(24,4) NOT NULL,
 gdp_reference_year INT NOT NULL, source VARCHAR(120) NOT NULL,
 provenance VARCHAR(30) NOT NULL DEFAULT 'UPSTREAM_SNAPSHOT',
 fetched_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE KEY uq_macro_raw_market_day (market,trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS t_macro_cap_gdp_indicator (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 market VARCHAR(20) NOT NULL, trade_date DATE NOT NULL,
 cap_to_gdp DECIMAL(16,8) NOT NULL,
 version VARCHAR(24) NOT NULL DEFAULT 'v1',
 provenance VARCHAR(30) NOT NULL,
 calculated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE KEY uq_macro_indicator_day_version (market,trade_date,version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS t_macro_backtest_run (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 index_id INT NOT NULL, market VARCHAR(20) NOT NULL,
 start_date DATE NOT NULL, end_date DATE NOT NULL,
 parameters JSON NOT NULL, provenance VARCHAR(30) NOT NULL,
 summary JSON NOT NULL, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 KEY idx_macro_bt_index (index_id),
 CONSTRAINT fk_macro_backtest_index FOREIGN KEY (index_id) REFERENCES t_index_info(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS t_macro_backtest_daily (
 id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
 run_id INT NOT NULL, trade_date DATE NOT NULL,
 x DECIMAL(16,8) NOT NULL, target_weight DECIMAL(12,8) NOT NULL,
 actual_weight DECIMAL(12,8) NOT NULL, cash DECIMAL(22,6) NOT NULL,
 holding DECIMAL(22,6) NOT NULL, nav DECIMAL(22,6) NOT NULL,
 benchmark_nav DECIMAL(22,6) NOT NULL,
 fee DECIMAL(20,6) NOT NULL DEFAULT 0, action VARCHAR(20) NOT NULL DEFAULT 'HOLD',
 UNIQUE KEY uq_macro_bt_run_day (run_id,trade_date),
 CONSTRAINT fk_macro_bt_daily_run FOREIGN KEY (run_id) REFERENCES t_macro_backtest_run(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
