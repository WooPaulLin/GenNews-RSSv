import threading
import time
import logging
from datetime import datetime
import feedparser
import telebot
from googleapiclient.discovery import build
import os
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
import json

load_dotenv()

# Google Sheets 配置
SPREADSHEET_ID = os.getenv('SPREADSHEET_ID')
SEEDS_RANGE_NAME = 'monitor_list!B:B'
KEYWORDS_RANGE_NAME = 'keywords_list!A:B'
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')

# RSS 監控配置
RSS_CHECK_INTERVAL = 600  # RSS 檢查間隔（秒）
SHEET_REFRESH_INTERVAL = 600  # Sheet 更新間隔（秒）
RSS_REQUEST_DELAY = 1  # RSS 請求間隔（秒）

# 日誌配置
LOG_FORMAT = '%(asctime)s [%(levelname)s] %(message)s'
LOG_FILE = 'bot.log'

# 設置日誌配置
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Add OpenAI API configuration
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
CATEGORIES = [
    'License', 'Sanction', 'AML/CFT', 'Regulatory',
    'Benchmark Exchange License Update', 'Legal structure'
]

class GoogleSheetReader:
    def __init__(self):
        self.setup_google_sheets()

    def setup_google_sheets(self):
        try:
            self.service = build(
                'sheets', 
                'v4', 
                developerKey=GOOGLE_API_KEY
            )
            logger.info("Successfully connected to Google Sheets API")
        except Exception as e:
            logger.error(f"Failed to setup Google Sheets API: {e}")
            raise

    def get_rss_feeds(self):
        try:
            sheet = self.service.spreadsheets()
            result = sheet.values().get(spreadsheetId=SPREADSHEET_ID,
                                      range=SEEDS_RANGE_NAME).execute()
            values = result.get('values', [])
            feeds = [row[0] for row in values if row and 'http' in row[0].lower()]
            logger.info(f"Found {len(feeds)} RSS feeds in spreadsheet")
            return feeds
        except Exception as e:
            logger.error(f"Error fetching RSS feeds: {e}")
            return []
    
    def get_keywords(self):
        sheet = self.service.spreadsheets()
        result = sheet.values().get(spreadsheetId=SPREADSHEET_ID,
                                      range=KEYWORDS_RANGE_NAME).execute()
        values = result.get('values', [])
        keywords = {row[0]:row[1].split(', ') for row in values[1:] if row}
        return keywords

class RSSMonitor:
    def __init__(self, check_interval=RSS_CHECK_INTERVAL):
        self.check_interval = check_interval
        self.sheet_refresh_interval = SHEET_REFRESH_INTERVAL
        self.last_entries = {}
        self.is_running = False
        self.monitor_thread = None
        self.sheet_reader = GoogleSheetReader()
        self.feeds = []
        self.last_sheet_check = 0
        self.pending_entries = []
        self.max_batch_size = 5
        self.batch_timeout = 60
        self.last_batch_time = time.time()
        logger.info(f"RSSMonitor initialized with interval: {check_interval}s")

    def start_monitoring(self):
        self.is_running = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        logger.info("RSS monitoring started")

    def stop_monitoring(self):
        self.is_running = False
        if self.monitor_thread:
            self.monitor_thread.join()
        logger.info("RSS monitoring stopped")

    def _monitor_loop(self):
        while self.is_running:
            try:
                current_time = time.time()
                
                if current_time - self.last_sheet_check >= self.sheet_refresh_interval:
                    self.feeds = self.sheet_reader.get_rss_feeds()
                    self.last_sheet_check = current_time
                    logger.info(f"Updated RSS feed list, found {len(self.feeds)} feeds")

                for feed_url in self.feeds:
                    self._check_rss(feed_url)
                    time.sleep(RSS_REQUEST_DELAY)

                if (len(self.pending_entries) >= self.max_batch_size or 
                    (self.pending_entries and current_time - self.last_batch_time >= self.batch_timeout)):
                    self._process_pending_entries()

            except Exception as e:
                logger.error(f"Error in RSS monitoring: {str(e)}")
            
            time.sleep(min(self.check_interval, self.sheet_refresh_interval))

    def _check_rss(self, feed_url):
        try:
            # 先嘗試獲取原始內容
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(feed_url, headers=headers)
            response.raise_for_status()  # 檢查 HTTP 狀態碼
            
            # 記錄原始內容的前100個字符，用於診斷
            logger.debug(f"Raw content preview for {feed_url}: {response.text[:100]}")
            
            # 檢查內容類型
            content_type = response.headers.get('content-type', '')
            logger.info(f"Content-Type for {feed_url}: {content_type}")

            # 使用 feedparser 解析
            feed = feedparser.parse(feed_url)
            
            # 詳細的診斷信息
            logger.info(f"Feed parsing details for {feed_url}:")
            logger.info(f"Feed status: {getattr(feed, 'status', 'N/A')}")
            logger.info(f"Feed bozo: {getattr(feed, 'bozo', 'N/A')}")
            logger.info(f"Feed version: {getattr(feed, 'version', 'N/A')}")
            logger.info(f"Feed encoding: {getattr(feed, 'encoding', 'N/A')}")
            
            # 如果解析出錯
            if feed.bozo:
                logger.error(f"Feed parsing exception: {feed.bozo_exception}")
                
                # 如果是 Telegram 頻道，使用備用解析方法
                if 't.me/s/' in feed_url:
                    return self._parse_telegram_channel(response.text, feed_url)
                
                # 其他 RSS 源的錯誤處理
                if not feed.entries:
                    logger.warning(f"No entries found for feed: {feed_url}")
                    return
            
            # 正常的 RSS 處理邏輯
            latest_entry = feed.entries[0] if feed.entries else None
            if latest_entry:
                entry_id = latest_entry.id if 'id' in latest_entry else latest_entry.link
                
                if feed_url not in self.last_entries or self.last_entries[feed_url] != entry_id:
                    self.last_entries[feed_url] = entry_id
                    content = latest_entry.get('summary', '') or latest_entry.get('description', '')
                    
                    # 將條目添加到待處理列表
                    self.pending_entries.append({
                        'title': latest_entry.title,
                        'content': content,
                        'link': latest_entry.link,
                        'feed_url': feed_url
                    })

        except requests.exceptions.RequestException as e:
            logger.error(f"Request error for {feed_url}: {str(e)}")
        except Exception as e:
            logger.error(f"Error checking feed {feed_url}: {str(e)}")

    def _process_pending_entries(self):
        """批量處理待處理的條目"""
        if not self.pending_entries:
            return

        try:
            from openai import OpenAI
            client = OpenAI(api_key=OPENAI_API_KEY)
            
            # 準備批量請求的提示
            entries_text = ""
            for i, entry in enumerate(self.pending_entries, 1):
                entries_text += f"\nEntry {i}:\nTitle: {entry['title']}\nContent: {entry['content'][:500]}...\n"

            prompt = f"""Categorize each of the following news entries into one of these categories:
            {', '.join(CATEGORIES)}
            
            If an entry is not related to any category, respond with 'None'.
            
            {entries_text}
            
            Respond with a JSON array where each element is the category name or 'None' for each entry in order.
            Example response: ["License", "None", "AML/CFT"]"""

            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}]
            )
            
            # 解析回應
            categories = json.loads(response.choices[0].message.content.strip())
            
            # 處理每個條目
            for entry, category in zip(self.pending_entries, categories):
                if category and category != 'None':
                    message = (
                        f"🔔 New Update\n\n"
                        f"📂 Category: {category}\n"
                        f"📰 Title: {entry['title']}\n"
                        f"🔗 Link: {entry['link']}\n"
                        f"🕒 Published: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    self.send_telegram_message(message)
                    logger.info(f"New entry found for {entry['feed_url']}: {entry['title']} (Category: {category})")

        except Exception as e:
            logger.error(f"Error in batch processing: {str(e)}")
        finally:
            # 清空待處理列表並更新時間戳
            self.pending_entries = []
            self.last_batch_time = time.time()

    def categorize_with_chatgpt(self, title, content):
        """Use ChatGPT to categorize the news content"""
        try:
            from openai import OpenAI
            client = OpenAI(api_key=OPENAI_API_KEY)
            
            prompt = f"""Given the following news title and content, categorize it into one of these categories:
            {', '.join(CATEGORIES)}
            
            If the content is not related to any of these categories, respond with 'None'.
            
            Title: {title}
            Content: {content}
            
            Respond with only the category name or 'None'."""

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}]
            )
            
            category = response.choices[0].message.content.strip()
            return None if category == 'None' or category not in CATEGORIES else category
        except Exception as e:
            logger.error(f"Error in ChatGPT categorization: {str(e)}")
            return None

    def _parse_telegram_channel(self, html_content, feed_url):
        """特別處理 Telegram 頻道的解析"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            messages = soup.find_all('div', class_='tgme_widget_message')
            
            if not messages:
                logger.warning(f"No messages found in Telegram channel: {feed_url}")
                return
            
            latest_message = messages[0]
            message_link = latest_message.find('a', class_='tgme_widget_message_date')
            message_text = latest_message.find('div', class_='tgme_widget_message_text')
            
            if message_link and message_text:
                entry_id = message_link['href']
                
                if feed_url not in self.last_entries or self.last_entries[feed_url] != entry_id:
                    self.last_entries[feed_url] = entry_id
                    content = message_text.text
                    
                    # 將 Telegram 消息添加到待處理列表
                    self.pending_entries.append({
                        'title': content[:100],  # 使用內容前100個字符作為標題
                        'content': content,
                        'link': entry_id,
                        'feed_url': feed_url,
                        'is_telegram': True
                    })

        except Exception as e:
            logger.error(f"Error parsing Telegram channel {feed_url}: {str(e)}")

class TelegramBot:
    def __init__(self):
        self.bot = telebot.TeleBot(os.getenv('TELEGRAM_BOT_TOKEN'))
        self.bot.threaded = False
        self.bot.num_retries = 3
        logger.info("Telegram bot initialized")


    def start(self):
        """Start bot polling with error handling"""
        while True:
            try:
                logger.info("Starting bot polling...")
                self.bot.infinity_polling(timeout=60, long_polling_timeout=30)
            except requests.exceptions.ReadTimeout:
                logger.warning("Telegram API timeout occurred, restarting polling...")
                time.sleep(5)  # Wait before retrying
            except requests.exceptions.ConnectionError:
                logger.error("Connection error occurred, retrying in 30 seconds...")
                time.sleep(30)
            except Exception as e:
                logger.error(f"Unexpected error in bot polling: {str(e)}")
                time.sleep(10)

def load_chat_ids(filename="chat_ids.txt"):
    try:
        with open(filename, "r") as file:
            return [int(line.strip()) for line in file.readlines()]
    except FileNotFoundError:
        return []

def save_chat_id(chat_id, filename="chat_ids.txt"):
    with open(filename, "a") as file:
        file.write(f"{chat_id}\n")

def send_telegram_message(message):
    bot = telebot.TeleBot(os.getenv('TELEGRAM_BOT_TOKEN'))
    chat_ids = load_chat_ids()
    
    for chat_id in chat_ids:
        try:
            bot.send_message(chat_id, message)
            logger.info(f"Message sent to chat ID: {chat_id}")
        except Exception as e:
            logger.error(f"Failed to send message to chat ID {chat_id}: {e}")

def collect_chat_id(message):
    chat_id = message.chat.id
    chat_type = message.chat.type
    chat_ids = load_chat_ids()
    logger.info(f"Collecting chat ID: {chat_id}, Type: {chat_type}")
    
    if chat_type in ['group', 'supergroup']:
        if chat_id not in chat_ids:
            save_chat_id(chat_id)
            logger.info(f"New group chat ID saved: {chat_id}, Type: {chat_type}")
            bot = telebot.TeleBot(os.getenv('TELEGRAM_BOT_TOKEN'))
            bot.reply_to(message, "Bot has been added to this group successfully!")
        else:
            logger.debug(f"Group chat ID already exists: {chat_id}")
    else:
        logger.debug(f"Ignored non-group chat: {chat_id}, Type: {chat_type}")

def main():
    logger.info("=== Starting application ===")
    
    # Initialize RSS monitor
    rss_monitor = RSSMonitor(check_interval=RSS_CHECK_INTERVAL)
    
    # Initialize Telegram bot
    telegram_bot = TelegramBot()
    
    # Start RSS monitoring
    rss_monitor.start_monitoring()
    
    try:
        # Start Telegram bot with the new error handling method
        telegram_bot.start()
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
        rss_monitor.stop_monitoring()
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        rss_monitor.stop_monitoring()
    finally:
        logger.info("=== Application shutdown complete ===")

if __name__ == "__main__":
    main()
