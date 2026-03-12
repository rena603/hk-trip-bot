"""Claude API client - builds prompts from memory and generates responses."""
import anthropic
from config import ANTHROPIC_API_KEY
from memory import get_recent_messages, get_summaries, get_knowledge
from sheets import get_cached_sheet_data

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT_TEMPLATE = """あなたは「HKガイド」です。5人のチームの香港社員旅行（2026年4月上旬）をサポートする専属アシスタントです。

## あなたの役割
1. **旅行アシスタント**: 香港の観光スポット・グルメ・交通（MTR/バス/フェリー/タクシー）・文化・天気・両替・Wi-Fi・持ち物など、プロの旅行ガイドとしてアドバイス
2. **チームの記憶係**: このチャンネルの会話を全て記憶しており、過去の議論・決定事項・経緯を正確に把握
3. **スケジュール管理**: 旅程・予約・準備タスクの状況を把握し、聞かれたら即答

## ルール
- 日本語で回答する
- 簡潔に答える（長文は箇条書きで整理）
- 過去の会話で決まったことは「〇月〇日に△△さんが提案して決まりました」のように経緯付きで回答
- わからないことは正直に「まだチャンネルでは話題に出ていません」と言う
- 香港の最新情報（2024-2025年時点の知識）をベースにアドバイスする

## 香港基本情報
- 通貨: 香港ドル (HKD)、1HKD ≒ 19-20円
- 言語: 広東語・英語（観光地は英語OK、ローカル店は広東語メイン）
- 交通: オクトパスカード必須（MTR・バス・コンビニ・一部レストラン）
- ビザ: 日本人は90日以内の観光はビザ不要
- 時差: 日本 -1時間
- 電圧: 220V（BFタイプ、変換プラグ必要）
- 4月の気温: 22-27℃、湿度高め、雨の可能性あり（折り畳み傘推奨）

## スプレッドシートの情報
{sheet_data}

## これまでの会話まとめ（日別サマリー）
{summaries}

## 直近のチャンネル会話
{recent_messages}
"""


def _format_messages(messages):
    if not messages:
        return "（まだ会話はありません）"
    lines = []
    for m in messages:
        lines.append(f"[{m['user_name']}] {m['text']}")
    return '\n'.join(lines)


def _format_summaries(summaries):
    if not summaries:
        return "（まだサマリーはありません）"
    lines = []
    for s in summaries:
        lines.append(f"**{s['date']}**\n{s['summary']}")
    return '\n\n'.join(lines)


def _estimate_tokens(text):
    """Rough token estimate for Japanese text."""
    return len(text) // 2


def generate_response(user_question, user_name="someone"):
    recent = get_recent_messages(limit=50)
    summaries = get_summaries()
    sheet_data = get_cached_sheet_data()

    # Build system prompt
    formatted_recent = _format_messages(recent)
    formatted_summaries = _format_summaries(summaries)

    system = SYSTEM_PROMPT_TEMPLATE.format(
        sheet_data=sheet_data,
        summaries=formatted_summaries,
        recent_messages=formatted_recent,
    )

    # Token budget check - trim recent messages if too long
    total_estimate = _estimate_tokens(system) + _estimate_tokens(user_question)
    if total_estimate > 12000:
        # Reduce recent messages
        recent = get_recent_messages(limit=20)
        formatted_recent = _format_messages(recent)
        system = SYSTEM_PROMPT_TEMPLATE.format(
            sheet_data=sheet_data,
            summaries=formatted_summaries,
            recent_messages=formatted_recent,
        )

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        system=system,
        messages=[
            {"role": "user", "content": f"{user_name}さんからの質問: {user_question}"}
        ],
    )

    return response.content[0].text


def generate_daily_summary(messages_text):
    """Generate a summary of the day's conversations."""
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        system="あなたはチームの会話を要約するアシスタントです。以下の会話から、決定事項・TODO・重要な情報を簡潔にまとめてください。日本語で箇条書きにしてください。",
        messages=[
            {"role": "user", "content": f"今日の会話:\n{messages_text}"}
        ],
    )
    return response.content[0].text
