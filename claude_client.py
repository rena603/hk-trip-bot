"""Claude API client - builds prompts from memory and generates responses."""
import os
import re
import anthropic
from config import ANTHROPIC_API_KEY
from memory import get_recent_messages, get_summaries, get_knowledge
from sheets import get_cached_sheet_data

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# Load knowledge base from file
_knowledge_base = ""
_knowledge_path = os.path.join(os.path.dirname(__file__), "knowledge", "hk_guide.txt")
try:
    with open(_knowledge_path, "r", encoding="utf-8") as f:
        _knowledge_base = f.read()
except FileNotFoundError:
    _knowledge_base = ""


def _find_relevant_sections(question, full_text):
    """Find relevant sections from the knowledge base based on the question."""
    if not full_text:
        return ""

    # Keywords to section mapping
    section_keywords = {
        "エリア別ガイド": ["エリア", "中環", "セントラル", "尖沙咀", "チムサーチョイ", "旺角", "モンコック", "銅鑼湾", "上環", "深水埗", "ランタオ", "南丫島", "ラマ島", "西營盤", "どこ", "場所", "地区"],
        "グルメ完全ガイド": ["グルメ", "食事", "レストラン", "飲茶", "ヤムチャ", "ワンタン", "麺", "焼味", "火鍋", "デザート", "スイーツ", "食べ", "おいしい", "美味", "名店", "ミシュラン", "屋台", "ストリートフード", "お店", "エッグタルト"],
        "交通完全ガイド": ["交通", "MTR", "地下鉄", "バス", "トラム", "フェリー", "タクシー", "空港", "オクトパス", "移動", "行き方", "アクセス", "乗り換え", "路線"],
        "入国・ビザ・税関": ["ビザ", "パスポート", "入国", "税関", "持ち込み", "入境", "検疫", "空港到着"],
        "買い物ガイド": ["買い物", "ショッピング", "お土産", "免税", "ブランド", "マーケット", "女人街"],
        "文化・マナー": ["文化", "マナー", "チップ", "タブー", "治安", "安全", "喫煙", "禁煙"],
        "4月の旅行ガイド": ["4月", "天気", "気温", "服装", "季節", "イベント", "雨"],
        "緊急時の対応": ["緊急", "病院", "警察", "大使館", "総領事館", "トラブル", "パスポート紛失", "保険"],
        "モデルコース": ["モデルコース", "プラン", "スケジュール", "日程", "2泊", "3泊", "何日", "旅程", "コース"],
        "穴場スポット": ["穴場", "隠れ", "地元", "インスタ", "おすすめ", "人気ない", "空いて"],
        "Wi-Fi・通信": ["Wi-Fi", "wifi", "eSIM", "SIM", "通信", "ネット", "データ"],
        "両替・支払い": ["両替", "お金", "現金", "クレジット", "カード", "支払", "通貨", "ドル", "レート", "AlipayHK"],
        "旅程スケジュール": ["旅程", "スケジュール", "日程", "いつ", "何日", "ホテル", "宿", "フライト", "飛行機", "到着", "出発", "帰国", "深圳", "マカオ", "展示会", "ハイテクツアー", "ツアー", "カオルーン", "華強", "NH965", "NH860", "UO862", "QR817", "EY768", "ANA", "部屋", "チェックイン", "チェックアウト", "予約番号", "空港", "移動", "集合"],
        "旅費・予算": ["旅費", "予算", "費用", "いくら", "お金", "合計", "支払", "領収書", "精算", "一人当たり", "AMEX", "会社負担", "割り勘", "立替"],
        "TODO・準備チェックリスト": ["TODO", "準備", "やること", "チェック", "持ち物", "Alipay", "SIM", "VPN", "オクトパス", "WeChat", "wechat", "百度", "DiDi", "まだ", "終わってない", "できてない", "未完了", "決めないと", "決めること", "未決定", "確認", "優先", "パスポート", "保険", "変換プラグ", "両替"],
    }

    question_lower = question.lower()
    matched_sections = []

    for section_title, keywords in section_keywords.items():
        for kw in keywords:
            if kw.lower() in question_lower:
                matched_sections.append(section_title)
                break

    # If no specific match, include a few general sections
    if not matched_sections:
        matched_sections = ["旅程スケジュール", "TODO・準備チェックリスト", "エリア別ガイド"]

    # Extract matched sections from the full text
    result_parts = []
    sections = full_text.split("■ ")
    for section in sections:
        for title in matched_sections:
            if title in section:
                # Limit each section to prevent token overflow
                lines = section.strip().split("\n")
                result_parts.append("\n".join(lines[:80]))
                break

    return "\n\n".join(result_parts) if result_parts else ""


SYSTEM_PROMPT_TEMPLATE = """あなたは「HKガイド」です。5人のチームの香港社員旅行（2026年4月上旬）をサポートする専属アシスタントです。

## あなたの役割
1. **旅行アシスタント**: 香港の観光スポット・グルメ・交通・文化・天気・両替・Wi-Fi・持ち物など、プロの旅行ガイドとしてアドバイス
2. **チームの記憶係**: このチャンネルの会話を全て記憶しており、過去の議論・決定事項・経緯を正確に把握
3. **スケジュール管理**: 旅程・予約・準備タスクの状況を把握し、聞かれたら即答

## ルール
- 日本語で回答する
- 簡潔に答える（長文は箇条書きで整理）
- 以下の専門ガイド情報を積極的に活用して、具体的な店名・場所・料金・コツを含めた実践的な回答をする
- 過去の会話で決まったことは「〇月〇日に△△さんが提案して決まりました」のように経緯付きで回答
- わからないことは正直に「まだチャンネルでは話題に出ていません」と言う

## Slack書式ルール（最重要・必ず守ること）
あなたの回答はSlackに投稿されます。SlackはMarkdownに対応していません。以下を厳守してください。

絶対に使ってはいけないもの:
- # ## ### などの見出し記法 → Slackでは「# テキスト」がそのまま表示される
- **ダブルアスタリスク** → Slackでは「**テキスト**」がそのまま表示される
- | --- | のMarkdown表 → Slackでは崩れる

代わりに使うもの:
- 太字: *テキスト* （アスタリスク1個ずつで囲む）
- 見出し: *🎯 セクション名* や *【セクション名】* （太字＋絵文字 or 墨括弧）
- 表: 箇条書きで代替。例: 「*出発:* 15:15 関西空港」
- リンク: <URL|表示テキスト>
- 箇条書き: 「•」「-」どちらもOK
- 区切り: ———
- コードブロック: ```で囲む（等幅表示したい場合）
- 絵文字OK: :airplane: :hotel: 等

回答例（良い例）:
*🎯 予約必須セミナー*

*1. Asian Electronics Forum*
- 日程: 4/13 (初日)
- 時間: 通常午前中
- 内容: アジア電子産業の最新トレンド

## 専門ガイド情報（プロ監修）
{knowledge}

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

    # Find relevant knowledge sections based on the question
    relevant_knowledge = _find_relevant_sections(user_question, _knowledge_base)

    # Build system prompt
    formatted_recent = _format_messages(recent)
    formatted_summaries = _format_summaries(summaries)

    system = SYSTEM_PROMPT_TEMPLATE.format(
        knowledge=relevant_knowledge if relevant_knowledge else "（該当するガイド情報なし）",
        sheet_data=sheet_data,
        summaries=formatted_summaries,
        recent_messages=formatted_recent,
    )

    # Token budget check - trim recent messages if too long
    total_estimate = _estimate_tokens(system) + _estimate_tokens(user_question)
    if total_estimate > 15000:
        recent = get_recent_messages(limit=20)
        formatted_recent = _format_messages(recent)
        system = SYSTEM_PROMPT_TEMPLATE.format(
            knowledge=relevant_knowledge if relevant_knowledge else "（該当するガイド情報なし）",
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

    return _strip_markdown(response.content[0].text)


def _strip_markdown(text):
    """Strip all Markdown formatting, return clean plain text."""
    # Remove heading markers (###, ##, #)
    text = re.sub(r'^#{1,3}\s+', '', text, flags=re.MULTILINE)

    # Remove **bold** markers → just the text inside
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)

    # Remove remaining stray **
    text = text.replace('**', '')

    # Remove *italic* markers → just the text inside (but not list bullets like "* item")
    text = re.sub(r'(?<!\n)\*([^\s*][^*]*[^\s*])\*', r'\1', text)

    # --- horizontal rules → blank line
    text = re.sub(r'^-{3,}$', '', text, flags=re.MULTILINE)

    # [text](url) → text (url)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1 (\2)', text)

    # Clean up excessive blank lines (3+ → 2)
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


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
