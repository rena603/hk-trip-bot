"""HK Trip Bot - Slack bot that silently listens and responds when mentioned."""
import os
import re
import threading
import urllib.request
import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from config import SLACK_BOT_TOKEN, SLACK_APP_TOKEN, EXTERNAL_URL, PORT
from memory import init_db, store_message, get_all_messages_for_date, store_summary, get_message_count
from claude_client import generate_response, generate_daily_summary
from sheets import start_sheet_refresh_thread

# Initialize
init_db()
app = App(token=SLACK_BOT_TOKEN)

# Cache for Slack user names
_user_cache = {}


def get_user_name(user_id):
    if user_id in _user_cache:
        return _user_cache[user_id]
    try:
        info = app.client.users_info(user=user_id)
        name = (info['user'].get('profile', {}).get('display_name', '') or
                info['user'].get('real_name', '') or 'unknown')
        _user_cache[user_id] = name
        return name
    except Exception:
        return user_id


# --- Event: ALL messages (silent recording) ---
@app.event("message")
def handle_message(event, say):
    # Skip bot messages, message_changed, etc.
    subtype = event.get('subtype')
    if subtype in ('bot_message', 'message_changed', 'message_deleted'):
        return

    text = event.get('text', '')
    user_id = event.get('user', '')
    channel = event.get('channel', '')
    ts = event.get('ts', '')
    thread_ts = event.get('thread_ts')

    if not text or not user_id:
        return

    user_name = get_user_name(user_id)
    store_message(ts, channel, user_id, user_name, text, thread_ts)


# --- Event: @mention (respond with Claude) ---
@app.event("app_mention")
def handle_mention(event, say):
    text = event.get('text', '')
    user_id = event.get('user', '')
    ts = event.get('ts', '')
    thread_ts = event.get('thread_ts') or ts
    channel = event.get('channel', '')

    # Store the mention itself
    user_name = get_user_name(user_id)
    store_message(ts, channel, user_id, user_name, text, thread_ts)

    # Remove bot mention from question
    question = re.sub(r'<@[A-Z0-9]+>', '', text).strip()

    if not question:
        say(text="何か質問してください！香港旅行のことなら何でも聞いてくださいね。", thread_ts=thread_ts)
        return

    # Help command
    if question.lower() in ('help', 'ヘルプ', '使い方'):
        say(
            text=(
                "*HKガイド の使い方*\n"
                "`@hk-guide おすすめの観光スポットは？`\n"
                "`@hk-guide 前回の会議で何決まった？`\n"
                "`@hk-guide スケジュール教えて`\n"
                "`@hk-guide 持ち物リスト作って`\n\n"
                "このチャンネルの会話は全て覚えています。\n"
                "何でも気軽に聞いてください！"
            ),
            thread_ts=thread_ts,
        )
        return

    # Generate response with Claude
    try:
        # Show typing indicator via a temporary message
        response = generate_response(question, user_name)
        # Split into section blocks (Slack 3000 char limit per block)
        blocks = []
        chunk = ""
        for line in response.split("\n"):
            if len(chunk) + len(line) + 1 > 2900:
                blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chunk}})
                chunk = line
            else:
                chunk = chunk + "\n" + line if chunk else line
        if chunk:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chunk}})
        say(text=response, blocks=blocks, thread_ts=thread_ts)
    except Exception as e:
        say(text=f"すみません、エラーが発生しました: {str(e)[:100]}", thread_ts=thread_ts)


# --- Daily summary job ---
def daily_summary_job():
    """Run daily at midnight JST to summarize the day's conversations."""
    while True:
        now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))
        # Wait until next midnight JST
        tomorrow = now.replace(hour=0, minute=5, second=0, microsecond=0) + datetime.timedelta(days=1)
        wait_seconds = (tomorrow - now).total_seconds()
        threading.Event().wait(wait_seconds)

        # Summarize yesterday
        yesterday = (datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))) - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        messages = get_all_messages_for_date(yesterday)
        if messages:
            text = '\n'.join([f"[{m['user_name']}] {m['text']}" for m in messages])
            try:
                summary = generate_daily_summary(text)
                store_summary(yesterday, summary)
                print(f"[Summary] {yesterday}: done")
            except Exception as e:
                print(f"[Summary] {yesterday}: error - {e}")


# --- Health check server ---
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/status':
            import json
            count = get_message_count()
            self._json(200, {'status': 'ok', 'messages_stored': count})
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'OK')

    def _json(self, code, data):
        import json
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, *args):
        pass


def start_health_server():
    HTTPServer(('0.0.0.0', PORT), HealthHandler).serve_forever()


def keep_alive():
    """Self-ping to prevent free tier from sleeping."""
    if not EXTERNAL_URL:
        return
    while True:
        threading.Event().wait(300)
        try:
            urllib.request.urlopen(EXTERNAL_URL, timeout=10)
        except Exception:
            pass


# --- Backfill channel history on startup ---
def backfill_history():
    """On startup, fetch recent channel history to build initial memory."""
    try:
        # Get channels the bot is in
        result = app.client.conversations_list(types="public_channel")
        for ch in result['channels']:
            if ch.get('is_member'):
                history = app.client.conversations_history(channel=ch['id'], limit=200)
                for msg in reversed(history.get('messages', [])):
                    if msg.get('subtype') or not msg.get('user'):
                        continue
                    user_name = get_user_name(msg['user'])
                    store_message(
                        msg['ts'], ch['id'], msg['user'], user_name,
                        msg.get('text', ''), msg.get('thread_ts')
                    )
        print(f"[Backfill] Done. Total messages: {get_message_count()}")
    except Exception as e:
        print(f"[Backfill] Error: {e}")


# --- Main ---
if __name__ == '__main__':
    print("[HK Guide] Starting...")

    # Start background threads
    threading.Thread(target=start_health_server, daemon=True).start()
    threading.Thread(target=keep_alive, daemon=True).start()
    threading.Thread(target=daily_summary_job, daemon=True).start()
    start_sheet_refresh_thread()

    # Backfill existing messages
    backfill_history()

    print(f"[HK Guide] Health server on port {PORT}")
    print("[HK Guide] Connecting to Slack...")

    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
