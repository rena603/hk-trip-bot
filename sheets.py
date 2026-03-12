"""Google Sheets reader - caches trip planning data."""
import json
import base64
import threading
import time
import gspread
from google.oauth2.service_account import Credentials
from config import GOOGLE_CREDENTIALS_B64, HK_SHEET_ID, SHEETS_REFRESH_INTERVAL

_cache = {'data': None, 'last_refresh': 0}
_lock = threading.Lock()


def _get_client():
    if not GOOGLE_CREDENTIALS_B64 or not HK_SHEET_ID:
        return None
    scopes = ['https://www.googleapis.com/auth/spreadsheets.readonly']
    creds_json = json.loads(base64.b64decode(GOOGLE_CREDENTIALS_B64).decode())
    creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
    return gspread.authorize(creds)


def fetch_sheet_data():
    """Fetch all worksheet tabs and return formatted text."""
    gc = _get_client()
    if not gc:
        return "（スプレッドシート未接続）"

    try:
        sh = gc.open_by_key(HK_SHEET_ID)
        result = []
        for ws in sh.worksheets():
            title = ws.title
            rows = ws.get_all_values()
            if not rows:
                continue
            result.append(f"### {title}")
            # Header
            header = rows[0]
            result.append(' | '.join(header))
            result.append('|'.join(['---'] * len(header)))
            for row in rows[1:]:
                result.append(' | '.join(row))
            result.append('')
        return '\n'.join(result) if result else "（シートにデータなし）"
    except Exception as e:
        return f"（シート読み込みエラー: {e}）"


def get_cached_sheet_data():
    """Return cached sheet data, refresh if stale."""
    with _lock:
        now = time.time()
        if _cache['data'] is None or (now - _cache['last_refresh']) > SHEETS_REFRESH_INTERVAL:
            _cache['data'] = fetch_sheet_data()
            _cache['last_refresh'] = now
        return _cache['data']


def start_sheet_refresh_thread():
    """Background thread to refresh sheet data periodically."""
    def _loop():
        while True:
            time.sleep(SHEETS_REFRESH_INTERVAL)
            with _lock:
                _cache['data'] = fetch_sheet_data()
                _cache['last_refresh'] = time.time()

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
