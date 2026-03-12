"""Configuration - loads from environment variables."""
import os

SLACK_BOT_TOKEN = os.environ.get('SLACK_BOT_TOKEN', '')
SLACK_APP_TOKEN = os.environ.get('SLACK_APP_TOKEN', '')
ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
GOOGLE_CREDENTIALS_B64 = os.environ.get('GOOGLE_CREDENTIALS', '')
HK_SHEET_ID = os.environ.get('HK_SHEET_ID', '')

# SQLite path - use /data for Railway volume, fallback to local
DB_PATH = os.environ.get('DB_PATH', '/data/memory.db')

# Self-ping URL
EXTERNAL_URL = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')
if EXTERNAL_URL and not EXTERNAL_URL.startswith('http'):
    EXTERNAL_URL = f'https://{EXTERNAL_URL}'
PORT = int(os.environ.get('PORT', 8080))

# Sheets cache refresh interval (seconds)
SHEETS_REFRESH_INTERVAL = 600  # 10 minutes
