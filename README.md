# Phoenix Insurance Telegram Bot

בוט טלגרם לשאילת שאלות על פוליסות ביטוח בריאות מחברת פניקס.

Bot for asking questions about Phoenix Insurance health policies in Hebrew.

## Features

- Secure login via OTP (one-time password)
- Automatic download of health insurance policy documents
- Upload documents to Google Gemini File Search
- Natural language Q&A about your coverage in Hebrew
- Per-user data isolation

## Prerequisites

- Python 3.10 or higher
- Telegram Bot Token (from [@BotFather](https://t.me/BotFather))
- Google Gemini API Key (from [AI Studio](https://aistudio.google.com/apikey))

## Installation

### 1. Clone the repository

```bash
git clone <repository-url>
cd phoenix-telegram-bot
```

### 2. Create virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Install Playwright browser

```bash
playwright install chromium
```

### 5. Configure environment

```bash
# Copy example config
cp .env.example .env

# Edit .env with your API keys
# Windows: notepad .env
# Linux/Mac: nano .env
```

Required settings in `.env`:
```
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
GEMINI_API_KEY=your_gemini_api_key
```

## Running the Bot

```bash
python -m bot.main
```

Or:

```bash
cd phoenix-telegram-bot
python -m bot.main
```

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Start connection to Phoenix account |
| `/status` | Show connection status |
| `/refresh` | Re-download documents |
| `/logout` | Disconnect and clear all data |
| `/help` | Show help message |

## Usage Flow

1. Start the bot with `/start`
2. Enter your Israeli ID number (9 digits)
3. Enter your phone number (05XXXXXXXX)
4. Enter the OTP code received via SMS
5. Wait for documents to download and upload
6. Ask questions about your coverage in Hebrew!

### Example Questions

- "האם יש לי כיסוי לריפוי בעיסוק?"
- "מה גובה הכיסוי לניתוחים?"
- "מהי ההשתתפות העצמית שלי?"
- "מה הכיסוי שלי לתרופות?"

## Project Structure

```
phoenix-telegram-bot/
├── bot/
│   ├── __init__.py
│   ├── main.py          # Entry point
│   ├── handlers.py      # Command handlers
│   ├── states.py        # Conversation states
│   └── messages.py      # Hebrew UI text
├── scraper/
│   ├── __init__.py
│   ├── phoenix_downloader.py  # Playwright scraper
│   └── progress_callback.py   # Progress reporting
├── gemini/
│   ├── __init__.py
│   ├── file_search.py   # File Search store management
│   └── chat.py          # Q&A with File Search
├── database/
│   ├── __init__.py
│   ├── models.py        # SQLAlchemy models
│   └── db.py            # Database operations
├── config.py            # Configuration
├── requirements.txt
├── .env.example
├── .env                 # Your config (not in git)
├── .gitignore
└── README.md
```

## Configuration Options

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | - | Bot token from BotFather |
| `GEMINI_API_KEY` | Yes | - | Google Gemini API key |
| `GEMINI_MODEL` | No | `gemini-2.5-flash` | Gemini model to use |
| `DATA_DIR` | No | `data` | Directory for downloads |
| `HEADLESS` | No | `true` | Run browser headless |
| `OTP_TIMEOUT` | No | `300` | OTP timeout in seconds |
| `SCRAPER_TIMEOUT` | No | `600` | Scraper timeout in seconds |

## Security Notes

- User credentials are never stored (only session state)
- OTP codes are not logged or persisted
- Each user's documents are isolated
- `/logout` command deletes all user data
- Browser sessions are closed after each operation

## Troubleshooting

### "Login failed"
- Verify your ID and phone number are correct
- Make sure the phone is registered with Phoenix
- Try again - OTP may have expired

### "No policies found"
- You may not have active health policies with Phoenix
- Contact Phoenix customer service to verify

### Browser not found
```bash
playwright install chromium
```

### Connection timeout
- Check your internet connection
- Phoenix website may be temporarily unavailable
- Try again later

## Development

### Running with visible browser (for debugging)

Set in `.env`:
```
HEADLESS=false
```

### Logging

Logs are printed to stdout. For file logging, modify `bot/main.py`.

## License

MIT License

## Disclaimer

This bot is not affiliated with Phoenix Insurance. Use at your own risk.
Always verify important insurance information directly with Phoenix or your insurance agent.
