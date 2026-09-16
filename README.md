# Daily World News Bot 🗞️

Fetches global headlines every morning, uses a free LLM (Groq) to dedupe,
rank, and summarize the top 20 stories, and sends them to you on Telegram.
Runs automatically and for free via GitHub Actions — no server required.

## How it works

1. **Fetch** — pulls headlines from Google News RSS (no API key needed,
   covers World/Business/Tech/Science/Health + optional country editions),
   plus GNews.io / NewsData.io if you add their free keys later.
2. **Dedupe** — collapses near-identical stories reported by multiple outlets.
3. **Rank & summarize** — sends the combined headline list to Groq's free
   `openai/gpt-oss-120b` model, which picks the 20 most globally
   significant, diverse stories and writes a short summary for each.
4. **Deliver** — posts a formatted digest to your Telegram chat, plus a
   spoken-word audio briefing (MP3, generated with a free neural
   text-to-speech voice — no API key needed).
5. **Schedule** — a GitHub Actions workflow runs the script every morning
   automatically, for free, forever (within GitHub's generous free tier).

## One-time setup (about 10 minutes)

### 1. Get a free Groq API key
- Go to https://console.groq.com → sign up (no credit card)
- Create an API key

### 2. Create a Telegram bot
- Open Telegram, message **@BotFather**
- Send `/newbot`, follow the prompts → you'll get a **bot token**
- Start a chat with your new bot (send it any message, e.g. "hi")
- Find your **chat ID**: message **@userinfobot** on Telegram, or visit
  `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` after messaging
  your bot, and read the `"chat":{"id": ...}` field

### 3. Put the code on GitHub
- Create a new **private** GitHub repo
- Push these files to it (`news_bot.py`, `requirements.txt`,
  `.github/workflows/daily_news.yml`, `README.md`)

### 4. Add your secrets
In the repo: **Settings → Secrets and variables → Actions → New repository secret**

| Secret name          | Value                          |
|-----------------------|---------------------------------|
| `GROQ_API_KEY`        | your Groq key                  |
| `TELEGRAM_BOT_TOKEN`  | your bot token from BotFather   |
| `TELEGRAM_CHAT_ID`    | your chat ID                   |

(Optional, to add more news sources later: `GNEWS_API_KEY`, `NEWSDATA_API_KEY`)

### 5. Set your morning time
Edit the `cron` line in `.github/workflows/daily_news.yml`.
Cron runs in **UTC**, so convert your local morning time.
Example: 7:30 AM IST = 02:00 UTC → `cron: "0 2 * * *"` (already set).

### 6. Test it
Go to the **Actions** tab in your repo → "Daily News Bot" → **Run workflow**
(the `workflow_dispatch` trigger lets you fire it manually any time).
You should get a Telegram message within a minute.

After that, it just runs itself every morning. ✅

## Running locally (optional)

```bash
pip install -r requirements.txt
export GROQ_API_KEY="..."
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
python news_bot.py
```

## Customizing

- **Number of stories**: set env var `TOP_N` (default 20)
- **News topics/regions**: edit `GOOGLE_NEWS_FEEDS` in `news_bot.py`
  (add feeds for any country: change `gl=US&ceid=US:en` to e.g.
  `gl=IN&ceid=IN:en` for India, `gl=GB&ceid=GB:en` for UK, etc.)
- **LLM model**: set env var `GROQ_MODEL` (default `openai/gpt-oss-120b`);
  swap in another Groq model, or point `GROQ_URL`/logic at Gemini later
- **Message style**: edit `format_message()` for a different layout
- **Audio briefing**: set `ENABLE_AUDIO=false` to turn it off entirely, or
  change the voice with `TTS_VOICE` (default `en-IN-NeerjaNeural`). Other
  good free options: `en-IN-PrabhatNeural` (Indian English, male),
  `en-US-AriaNeural` (US English, female), `en-GB-RyanNeural` (UK, male).
  Full voice list: run `edge-tts --list-voices` after installing, or see
  the `edge-tts` PyPI page. Uses Microsoft's free neural TTS via the
  `edge-tts` library — no API key, no cost.

## Ideas for later enhancements

- Add sentiment/bias tagging per story
- Group stories by category with sub-headers
- Add an inline "summarize this in more detail" Telegram button per story
- Personalize topics per user (e.g. multiple chat IDs with different interests)
- Store sent stories in a small DB to avoid repeats across days
- Add a weekly "biggest stories of the week" digest
- Swap Groq for Gemini (bigger context, can read full articles not just
  headlines) when you want deeper analysis
