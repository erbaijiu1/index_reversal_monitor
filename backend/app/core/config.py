import os
class Settings:
    database_url = os.getenv('DATABASE_URL', 'sqlite:///./local.db')
    admin_token = os.getenv('ADMIN_TOKEN', 'CHANGE_ME')
    schedule_enabled = os.getenv('SCHEDULE_ENABLED', 'false').lower() == 'true'
    webhook_url = os.getenv('WEBHOOK_URL', '')
    alert_enabled = os.getenv('ALERT_ENABLED', 'false').lower() == 'true'
    sync_cron_hour = int(os.getenv('SYNC_CRON_HOUR', '19'))
    sync_cron_minute = int(os.getenv('SYNC_CRON_MINUTE', '15'))
    history_days = int(os.getenv('HISTORY_DAYS', '730'))
    timezone = os.getenv('TIMEZONE', 'Asia/Shanghai')
settings = Settings()
