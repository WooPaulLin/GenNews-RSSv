# News & Telegram Monitoring Bot (GenNews)

A Python-based monitoring bot that automatically tracks news and Telegram channels for policy updates, regulatory changes, and other important announcements. The bot checks sources every 10 minutes and sends notifications through Telegram.

## Features

- 🔄 Monitors RSS feeds and Telegram channels
- 🤖 Uses ChatGPT for intelligent content categorization
- 📊 Google Sheets integration for managing tracking sources
- 📱 Telegram notifications for updates
- ⏱️ Batch processing of updates
- 🔍 Automatic categorization of news into:
  - License
  - Sanction
  - AML/CFT
  - Regulatory
  - Benchmark Exchange License Update
  - Legal structure

## Setup

### Prerequisites

- Python 3.11
- Google Sheets API access
- OpenAI API key
- Telegram Bot token

### Environment Variables

Create a `.env` file with the following variables:
Google Sheet ID containing RSS sources 
- SPREADSHEET_ID=your_google_sheet_id

Google API key for accessing Sheets
- **GOOGLE_API_KEY=your_google_api_key** 

OpenAI API key for content categorization
- **OPENAI_API_KEY=your_openai_api_key** 

Telegram Bot token for notifications
- **TELEGRAM_BOT_TOKEN=your_bot_token** 

### Files

- `chat_ids.txt` - Automatically stores Telegram group IDs where the bot is added
- `bot.log` - Contains detailed operation logs

### Google Sheet Structure

The bot expects two sheets:
1. `monitor_list` - Column B contains RSS/Telegram channel URLs
2. `keywords_list` - Columns A & B contain keyword configurations

### Installation

1. Clone the repository
2. Install dependencies:


pip install -r requirements.txt


## Usage

1. Set up your Google Sheet with monitoring sources
2. Configure your environment variables
3. Run the bot: `python app.py`


## Features in Detail

### RSS Monitoring
- Checks sources every 10 minutes
- Supports both RSS feeds and Telegram channels
- Implements rate limiting and error handling

### Content Processing
- Batches updates (max 5 entries)
- Uses ChatGPT for intelligent categorization
- Filters irrelevant content automatically

### Telegram Integration
- Supports group chats
- Automatic chat ID collection and storage in chat_ids.txt
- Error-resistant message delivery
- Maintains list of authorized groups for notifications

## Logging

The bot maintains detailed logs in `bot.log`, including:
- Connection status
- Content processing results
- Error messages
- Monitoring activities

## Error Handling

The bot includes comprehensive error handling for:
- Network issues
- API timeouts
- Parse errors
- Connection interruptions




