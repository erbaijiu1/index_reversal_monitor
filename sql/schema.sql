
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
