import os
import sys as _sys

# Legacy module — kept so Zettelkasten & USB-monitor paths keep working until
# those features are ported into src/. New code should use main.py + src/ instead.
# Support both `python legacy/uploadToNotion.py` and `python -m legacy.uploadToNotion`.
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
if _here not in _sys.path:
    _sys.path.insert(0, _here)  # find sibling DBReader when run as a script
if _root not in _sys.path:
    _sys.path.insert(0, _root)  # find root-level zettelkasten_generator

import DBReader  # noqa: E402
from notion_client import Client
from datetime import datetime
import math
import requests
import logging
from logging.handlers import RotatingFileHandler
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import time
from threading import Lock
from functools import lru_cache
from notion_client.errors import APIResponseError
from typing import List, Optional

# Import Zettelkasten module
try:
    from zettelkasten_generator import (
        ZettelkastenCardGenerator,
        ZettelkastenCard,
        check_ollama_availability,
        check_gemini_availability
    )
    ZETTELKASTEN_AVAILABLE = True
except ImportError as e:
    ZETTELKASTEN_AVAILABLE = False
    print(f"Warning: Zettelkasten module not available: {e}")


# Rate Limiter for Notion API (recommended: ~3 requests per second)
class NotionRateLimiter:
    """Thread-safe rate limiter for Notion API calls"""
    def __init__(self, calls_per_second=3):
        self.min_interval = 1.0 / calls_per_second
        self.last_call = 0
        self.lock = Lock()

    def wait(self):
        with self.lock:
            elapsed = time.time() - self.last_call
            if elapsed < self.min_interval:
                time.sleep(self.min_interval - elapsed)
            self.last_call = time.time()


rate_limiter = NotionRateLimiter()

# 设置日志配置
def setup_logger():
    logger = logging.getLogger('kobo_notion_sync')
    
    # 避免重複添加handler
    if logger.handlers:
        return logger
        
    logger.setLevel(logging.INFO)  # 調整為INFO級別，減少冗餘日誌
    
    # 创建日志目录
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # 设置日志文件，指定 UTF-8 编码
    log_file = os.path.join(log_dir, 'kobo_notion_sync.log')
    file_handler = RotatingFileHandler(log_file, maxBytes=2*1024*1024, backupCount=3, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    
    # 设置控制台输出，指定 UTF-8 编码  
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # 设置详细的日志格式，包含函數名稱
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
    )
    file_handler.setFormatter(formatter)
    
    # 控制台使用簡化格式
    console_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

# 初始化日志记录器
logger = setup_logger()

# Load environment variables from a .env file
from dotenv import load_dotenv
load_dotenv()


# Get environment variables
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

# Zettelkasten configuration - Three-database architecture
NOTION_BOOKS_DATABASE_ID = os.getenv("NOTION_BOOKS_DATABASE_ID")  # Books database
NOTION_HIGHLIGHTS_DATABASE_ID = os.getenv("NOTION_HIGHLIGHTS_DATABASE_ID", NOTION_DATABASE_ID)  # Kobo highlights (default to main)
NOTION_ZETTELKASTEN_DATABASE_ID = os.getenv("NOTION_ZETTELKASTEN_DATABASE_ID")  # Zettelkasten cards

# Zettelkasten feature toggle
ENABLE_ZETTELKASTEN_CARDS = os.getenv("ENABLE_ZETTELKASTEN_CARDS", "false").lower() == "true"
ZETTELKASTEN_MAX_CARDS = int(os.getenv("ZETTELKASTEN_MAX_CARDS", "16"))
ZETTELKASTEN_MIN_HIGHLIGHTS = int(os.getenv("ZETTELKASTEN_MIN_HIGHLIGHTS", "10"))

# Initialize Notion client
notion = Client(auth=NOTION_TOKEN)
database = notion.databases.retrieve(NOTION_DATABASE_ID)

def retry_notion_update(update_function, max_retries=3, delay=1):
    """重試機制處理Notion API的409衝突錯誤和429 rate limit"""
    current_delay = delay
    for attempt in range(max_retries):
        try:
            rate_limiter.wait()  # Rate limiting
            return update_function()
        except APIResponseError as e:
            error_str = str(e)
            if "429" in error_str:
                # Rate limit hit - wait longer
                wait_time = current_delay * 2
                logger.warning(f"Rate limit (429) hit，等待 {wait_time} 秒...")
                time.sleep(wait_time)
                current_delay *= 2
            elif "409" in error_str and attempt < max_retries - 1:
                logger.warning(f"遇到409衝突錯誤，第 {attempt + 1} 次重試，等待 {current_delay} 秒...")
                time.sleep(current_delay)
                current_delay *= 2  # 指數退避
            else:
                logger.error(f"Notion API錯誤 (嘗試 {attempt + 1}/{max_retries}): {error_str}")
                raise
        except Exception as e:
            logger.error(f"未預期的錯誤: {str(e)}")
            raise

# Define your custom functions getTitleWithoutSubtitle, checkBookSyncStatus, addEntryByTitle,
# getUnSyncTarget, syncBookHighlights, updateBookLRTime, updateBookSpendTime as needed


def get_title_without_subtitle(title):
    logger.debug(f"Processing title: {title}")
    if ":" in title:
        result = title.split(":")[0].strip()
        logger.debug(f"Title after processing: {result}")
        return result
    return title.strip()

def check_target(title, isExportDone=True):
    try:
        logger.info(f"Checking target for title: {title}, isExportDone: {isExportDone}")
        filter_property = "Exported" if isExportDone else "Exported"
        filter_value = True if isExportDone else False

        rate_limiter.wait()  # Rate limiting
        target = notion.databases.query(
            database_id=NOTION_DATABASE_ID,
            filter={
                "and": [
                    {"property": "Title", "rich_text": {"contains": title}},
                    {"property": filter_property, "checkbox": {"equals": filter_value}},
                ],
            },
        )

        if not target or "results" not in target:
            logger.warning(f"Invalid response from Notion API for title: {title}")
            return {
                "is_target_valid": False,
                "pageId": None,
            }

        results = target.get("results", [])
        if not results:
            logger.info(f"No matching results found for title: {title}")
            return {
                "is_target_valid": False,
                "pageId": None,
            }

        if len(results) > 1:
            logger.warning(f"Multiple results found for title: {title}, using first result")
        
        is_target_valid = len(results) >= 1
        page_id = results[0].get("id") if is_target_valid else None
        
        logger.info(f"Target check result - valid: {is_target_valid}, pageId: {page_id}")
        return {
            "is_target_valid": is_target_valid,
            "pageId": page_id,
        }
    except Exception as e:
        logger.error(f"Error in check_target: {str(e)}", exc_info=True)
        return {
            "is_target_valid": False,
            "pageId": None,
        }

def update_book_time(page_id, time_property_name, time_value):
    if time_value is not None:
        rate_limiter.wait()  # Rate limiting
        notion.pages.update(
            page_id=page_id,
            properties={
                time_property_name: {
                    "date": {
                        "start": time_value,
                    },
                },
            },
        )
    else:
        logger.debug(f"No value provided for {time_property_name}, skipping update.")

def update_book_number(page_id, field_name, value):
    if value is not None:  # 檢查數值是否有提供
        rate_limiter.wait()  # Rate limiting
        notion.pages.update(
            page_id=page_id,
            properties={
                field_name: {
                    "number": value  # 使用 number 屬性來更新數字
                }
            }
        )
    else:
        logger.debug(f"No value provided for {field_name}, skipping update.")

def update_percentage(page_id, value):
    if value is not None:  # 檢查數值是否有提供
        rate_limiter.wait()  # Rate limiting
        notion.pages.update(
                page_id=page_id,
                properties={
                    "PercentageRead": {
                        "number": value  # 使用 number 屬性來更新數字
                    }
                }
            )
    else:
        logger.debug("No value provided for PercentageRead, skipping update.")

def clean_html_tags(text):
    """清理HTML標籤，保留純文本內容"""
    if not text:
        return text
    
    # 移除HTML標籤
    clean_text = re.sub(r'<[^>]+>', '', text)
    
    # 清理多餘的空白字符
    clean_text = re.sub(r'\s+', ' ', clean_text).strip()
    
    # 處理HTML實體
    clean_text = clean_text.replace('&amp;', '&')
    clean_text = clean_text.replace('&lt;', '<')
    clean_text = clean_text.replace('&gt;', '>')
    clean_text = clean_text.replace('&quot;', '"')
    clean_text = clean_text.replace('&#39;', "'")
    
    return clean_text

def update_book_textinfo(page_id, text_property_name, text_value):
    if text_value:
        # 清理HTML標籤
        clean_text = clean_html_tags(text_value)
        
        # 添加重試機制處理409錯誤
        retry_notion_update(
            lambda: notion.pages.update(
                page_id=page_id,
                properties={
                    text_property_name: {
                        "rich_text": [
                        {
                            "text": {
                                    "content": clean_text
                            }
                        }
                        ]
                    },
                },
            )
        )
    else:
        logger.debug(f"No value provided for {text_property_name}, skipping update.")

def update_book_spend_time(page_id, bookSpendingTime):
    hours = math.floor(bookSpendingTime / 3600)
    minutes = math.floor((bookSpendingTime % 3600) / 60)
    seconds = bookSpendingTime % 60
    formatted_time = f"{hours:02}:{minutes:02}:{seconds:02}"

    rate_limiter.wait()  # Rate limiting
    notion.pages.update(
        page_id=page_id,
        properties={
            "SpendReadingTime": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {
                            "content": formatted_time,
                        },
                    },
                ],
            },
        },
    )

def update_time_related(page_id, book):
    update_book_spend_time(page_id, book.get_time_spent_reading())
    update_book_time(page_id,"LastReadDate", book.get_date_last_read())
    update_book_time(page_id,"LastFinishedReadTime", book.get_last_time_finished_reading())
    update_percentage(page_id, book.get_percent_read())
    logger.info("Finish Update Time")

def update_book_people(page_id, publisher_name=None, author_name=None):
    properties_to_update = {}

    # 檢查 publisher_name 是否有值
    if publisher_name:
        properties_to_update["Publisher"] = {
            "rich_text": [
                {
                    "text": {
                            "content": publisher_name
                    }
                }
            ]
        }
    
    # 檢查 author_name 是否有值
    if author_name:
        properties_to_update["Author"] = {
            "rich_text": [
                {
                    "text": {
                            "content": author_name
                    }
                }
            ]
        }
    
    # 如果有需要更新的欄位才進行 API 調用
    if properties_to_update:
        retry_notion_update(
            lambda: notion.pages.update(
                page_id=page_id,
                properties=properties_to_update
            )
        )
    else:
        logger.debug("No publisher or author name provided, skipping update.")

def update_book_subtitle(page_id, subtitle):
    if subtitle:  # 檢查 subtitle 是否有值
        retry_notion_update(
            lambda: notion.pages.update(
                page_id=page_id,
                properties={
                    "Subtitle": {
                        "rich_text": [
                            {
                                "text": {
                                    "content": subtitle
                                }
                            }
                        ]
                    },
                },
            )
        )
    else:
        logger.debug("No subtitle provided, skipping update.")


def build_page_properties(book, include_time=True, include_metadata=True):
    """構建完整的頁面屬性字典，合併多個更新為單一 API 調用"""
    properties = {}

    if include_time:
        # SpendReadingTime
        time_spent = book.get_time_spent_reading()
        if time_spent is not None:
            hours = math.floor(time_spent / 3600)
            minutes = math.floor((time_spent % 3600) / 60)
            seconds = time_spent % 60
            properties["SpendReadingTime"] = {
                "rich_text": [{"type": "text", "text": {"content": f"{hours:02}:{minutes:02}:{seconds:02}"}}]
            }

        # LastReadDate
        last_read = book.get_date_last_read()
        if last_read:
            properties["LastReadDate"] = {"date": {"start": last_read}}

        # LastFinishedReadTime
        last_finished = book.get_last_time_finished_reading()
        if last_finished:
            properties["LastFinishedReadTime"] = {"date": {"start": last_finished}}

        # PercentageRead
        percent = book.get_percent_read()
        if percent is not None:
            properties["PercentageRead"] = {"number": percent}

    if include_metadata:
        # Subtitle
        subtitle = book.get_subtitle()
        if subtitle:
            properties["Subtitle"] = {
                "rich_text": [{"text": {"content": subtitle}}]
            }

        # Publisher
        publisher = book.get_publisher()
        if publisher:
            properties["Publisher"] = {
                "rich_text": [{"text": {"content": publisher}}]
            }

        # Author
        author = book.get_author()
        if author:
            properties["Author"] = {
                "rich_text": [{"text": {"content": author}}]
            }

        # Description
        description = book.get_description()
        if description:
            clean_desc = clean_html_tags(description)
            properties["Description"] = {
                "rich_text": [{"text": {"content": clean_desc}}]
            }

        # ISBN
        isbn = book.get_isbn()
        if isbn:
            properties["ISBN"] = {
                "rich_text": [{"text": {"content": isbn}}]
            }

    return properties


def update_book_properties_batch(page_id, properties):
    """批次更新頁面屬性，合併多個更新為單一 API 調用"""
    if not properties:
        logger.debug("No properties to update, skipping.")
        return

    retry_notion_update(
        lambda: notion.pages.update(page_id=page_id, properties=properties)
    )
    logger.info(f"Updated {len(properties)} properties in single API call")




def sync_book_highlights(page_id, highlights_list):
    # print(f"Start Sync Highlights for pageId: {page_id}")
    blocks = []

    blocks.append({
        "object": "block",
        "type": "heading_1",
        "heading_1": {
            "rich_text": [{"type": "text", "text": {"content": "Highlights"}}],
        },
    })
    logger.debug("Append Title")
    logger.debug(f"Highlights count: {len(highlights_list)}")

    for highlight in highlights_list:
        if highlight is not None:
            # print(highlight)
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": highlight}}],
                },
            })

        # 調整批次大小以符合Notion API限制，更保守的設置
        if len(blocks) > 80:  # 更保守的批次大小，避免超過API限制
            logger.info(f"達到批次限制 {len(blocks)}，先上傳這批blocks")
            append_blocks_to_page(page_id, blocks)
            blocks.clear()
            logger.info(f"清除blocks列表，目前大小: {len(blocks)}")

    append_blocks_to_page(page_id, blocks)

    rate_limiter.wait()  # Rate limiting
    notion.pages.update(
        page_id=page_id,
        properties={"Exported": {"checkbox": True}},
    )

# 新增：处理带章节信息的高亮内容
def sync_book_highlights_with_chapter(page_id, highlights_with_chapter):
    """同步带章节信息的高亮内容到Notion，使用智能排序和改進的標題驗證"""
    blocks = []

    blocks.append({
        "object": "block",
        "type": "heading_1",
        "heading_1": {
            "rich_text": [{"type": "text", "text": {"content": "Highlights"}}],
        },
    })
    logger.info(f"開始同步書籍高亮，總共 {len(highlights_with_chapter)} 個高亮")

    # 使用智能排序獲取正確的章節順序
    sorted_highlights = DBReader.smart_sort_highlights_by_chapter(highlights_with_chapter)
    
    # 重新按章節分組（現在已經是正確順序）
    chapter_groups = {}
    chapter_order = {}
    order_counter = 0
    
    for highlight_info in sorted_highlights:
        chapter_name = highlight_info['chapter_name']
        if chapter_name not in chapter_groups:
            chapter_groups[chapter_name] = []
            chapter_order[chapter_name] = order_counter
            order_counter += 1
        chapter_groups[chapter_name].append(highlight_info)

    # 按預定順序排序章節
    sorted_chapters = sorted(chapter_groups.items(), key=lambda x: chapter_order[x[0]])

    # 按章節順序處理高亮內容
    for chapter_name, highlights in sorted_chapters:
        # 清理和驗證章節標題
        display_chapter_name = chapter_name
        
        # 避免顯示"未知章節"
        if chapter_name == "未知章節" or chapter_name == "未知章节":
            # 嘗試從第一個高亮的ContentID提取更好的章節名稱
            if highlights:
                first_highlight = highlights[0]
                content_id = first_highlight.get('content_id', '')
                if content_id:
                    fallback_chapter = DBReader.extract_chapter_name(content_id)
                    if fallback_chapter != "未知章节":
                        display_chapter_name = fallback_chapter
                    else:
                        display_chapter_name = "其他內容"
        
        # 限制標題長度，避免過長
        if len(display_chapter_name) > 50:
            display_chapter_name = display_chapter_name[:47] + "..."
        
        logger.info(f"處理章節: {display_chapter_name} ({len(highlights)} 個高亮)")
        
        # 添加章节标题（使用單層級標題）
        blocks.append({
            "object": "block",
            "type": "heading_1",
            "heading_1": {
                "rich_text": [{"type": "text", "text": {"content": f"📖 {display_chapter_name}"}}],
            },
        })

        # 添加该章节的所有高亮内容（使用列表格式）
        for highlight_info in highlights:
            text = highlight_info['text']
            
            if text is not None:
                # 创建列表項目，使用 * 表示畫線內容
                blocks.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [{"type": "text", "text": {"content": text}}],
                    },
                })

        # 添加章节分隔符
        blocks.append({
            "object": "block",
            "type": "divider",
            "divider": {},
        })

        # 調整批次大小以符合Notion API限制，更保守的設置
        if len(blocks) > 80:  # 更保守的批次大小，避免超過API限制
            logger.info(f"達到批次限制 {len(blocks)}，先上傳這批blocks")
            append_blocks_to_page(page_id, blocks)
            blocks.clear()

    append_blocks_to_page(page_id, blocks)

    rate_limiter.wait()  # Rate limiting
    notion.pages.update(
        page_id=page_id,
        properties={"Exported": {"checkbox": True}},
    )


def sync_zettelkasten_cards(
    book_page_id: str,
    highlights_page_id: str,
    cards: List['ZettelkastenCard'],
    book_title: str = ""
) -> int:
    """
    Sync Zettelkasten cards to Notion database.

    Creates card pages in the Zettelkasten database with relations to:
    - Source Book (books database)
    - Source Highlights Page (kobo highlights database)

    Args:
        book_page_id: The page ID in the books database (can be None if not using separate books DB)
        highlights_page_id: The page ID in the kobo highlights database
        cards: List of ZettelkastenCard objects to sync
        book_title: Title of the source book

    Returns:
        Number of cards successfully synced
    """
    if not NOTION_ZETTELKASTEN_DATABASE_ID:
        logger.warning("NOTION_ZETTELKASTEN_DATABASE_ID not configured, skipping Zettelkasten sync")
        return 0

    if not cards:
        logger.info("No cards to sync")
        return 0

    logger.info(f"Syncing {len(cards)} Zettelkasten cards for '{book_title}'")

    success_count = 0

    for i, card in enumerate(cards):
        try:
            # Build the properties for the card page
            properties = {
                "Title": {
                    "title": [{"text": {"content": card.title}}]
                },
                "Content": {
                    "rich_text": [{"text": {"content": card.content}}]
                },
                "Source Highlight Text": {
                    "rich_text": [{"text": {"content": card.source_highlight[:2000]}}]  # Notion limit
                },
                "Source Chapter": {
                    "rich_text": [{"text": {"content": card.chapter_reference}}]
                },
                "Created Date": {
                    "date": {"start": datetime.now().isoformat()}
                }
            }

            # Add relation to Source Book if book_page_id is provided
            if book_page_id and NOTION_BOOKS_DATABASE_ID:
                properties["Source Book"] = {
                    "relation": [{"id": book_page_id}]
                }

            # Add relation to Source Highlights Page
            if highlights_page_id:
                properties["Source Highlights Page"] = {
                    "relation": [{"id": highlights_page_id}]
                }

            # Create the card page in Zettelkasten database
            def create_card():
                return notion.pages.create(
                    parent={"database_id": NOTION_ZETTELKASTEN_DATABASE_ID},
                    properties=properties
                )

            retry_notion_update(create_card)
            success_count += 1
            logger.info(f"Created card {i+1}/{len(cards)}: {card.title}")

        except Exception as e:
            logger.error(f"Failed to create card '{card.title}': {str(e)}")

    logger.info(f"Zettelkasten sync complete: {success_count}/{len(cards)} cards created")
    return success_count


def get_book_page_from_books_database(book_title: str) -> Optional[str]:
    """
    Query the books database to find a matching book page.

    Returns the page ID if found, None otherwise.
    """
    if not NOTION_BOOKS_DATABASE_ID:
        return None

    try:
        # Clean the title for searching
        search_title = get_title_without_subtitle(book_title)

        rate_limiter.wait()
        response = notion.databases.query(
            database_id=NOTION_BOOKS_DATABASE_ID,
            filter={
                "property": "Title",
                "rich_text": {"contains": search_title}
            }
        )

        results = response.get("results", [])
        if results:
            return results[0].get("id")

        return None

    except Exception as e:
        logger.warning(f"Error querying books database: {str(e)}")
        return None


def generate_and_sync_zettelkasten_cards(
    book,
    highlights_with_chapter: List[dict],
    highlights_page_id: str
) -> int:
    """
    Generate and sync Zettelkasten cards for a book.

    This is the main entry point for Zettelkasten card generation.
    It handles:
    1. Feature toggle check
    2. Card generation with dual-layer LLM
    3. Syncing to Notion

    Args:
        book: Book object with metadata
        highlights_with_chapter: List of highlight dictionaries
        highlights_page_id: The Notion page ID for the highlights

    Returns:
        Number of cards successfully synced
    """
    if not ENABLE_ZETTELKASTEN_CARDS:
        logger.debug("Zettelkasten cards disabled")
        return 0

    if not ZETTELKASTEN_AVAILABLE:
        logger.warning("Zettelkasten module not available")
        return 0

    if not NOTION_ZETTELKASTEN_DATABASE_ID:
        logger.warning("NOTION_ZETTELKASTEN_DATABASE_ID not configured")
        return 0

    book_title = book.get_title()
    logger.info(f"Starting Zettelkasten generation for '{book_title}'")

    # Check service availability
    if not check_ollama_availability():
        logger.warning("Ollama service not available, skipping Zettelkasten generation")
        return 0

    try:
        # Initialize generator
        generator = ZettelkastenCardGenerator(
            max_cards=ZETTELKASTEN_MAX_CARDS,
            min_highlights=ZETTELKASTEN_MIN_HIGHLIGHTS
        )

        # Generate cards
        cards = generator.generate_cards(highlights_with_chapter, book_title)

        if not cards:
            logger.info(f"No cards generated for '{book_title}'")
            return 0

        # Try to find book in books database (for relation)
        book_page_id = get_book_page_from_books_database(book_title)

        # Sync cards to Notion
        synced_count = sync_zettelkasten_cards(
            book_page_id=book_page_id,
            highlights_page_id=highlights_page_id,
            cards=cards,
            book_title=book_title
        )

        return synced_count

    except Exception as e:
        logger.error(f"Error in Zettelkasten generation: {str(e)}", exc_info=True)
        return 0


def add_entry_by_title(book_title):
    """創建新的 Notion 頁面並直接返回 page_id，避免額外的查詢"""
    try:
        rate_limiter.wait()  # Rate limiting
        # Create a new entry in the Notion database
        response = notion.pages.create(
            parent={
                "database_id": NOTION_DATABASE_ID,
            },
            properties={
                "title": {
                    "title": [
                        {
                            "text": {
                                "content": book_title,
                            },
                        },
                    ],
                },
            },
        )
        page_id = response["id"]
        logger.info(f"Entry {book_title} added successfully! Page ID: {page_id}")
        return page_id  # 直接返回 page_id，避免額外查詢
    except Exception as error:
        logger.error(f"Error adding entry: {error}")
        return None

def append_blocks_to_page(page_id, blocks):
    """安全地批次添加blocks到Notion頁面，遵守API限制並支持重試機制"""
    if not blocks:
        return
    
    # Notion API限制：每次最多100個blocks
    MAX_BLOCKS_PER_REQUEST = 100
    MAX_RETRIES = 3
    RETRY_DELAY = 1  # 秒
    
    try:
        for i in range(0, len(blocks), MAX_BLOCKS_PER_REQUEST):
            batch = blocks[i:i + MAX_BLOCKS_PER_REQUEST]
            batch_num = i//MAX_BLOCKS_PER_REQUEST + 1
            
            logger.info(f"上傳第 {batch_num} 批，包含 {len(batch)} 個blocks")
            
            # 重試機制
            for attempt in range(MAX_RETRIES):
                try:
                    rate_limiter.wait()  # Rate limiting
                    notion.blocks.children.append(
                        block_id=page_id,
                        children=batch,
                    )
                    logger.info(f"成功上傳第 {batch_num} 批 ({len(batch)} 個blocks)")
                    break
                    
                except APIResponseError as e:
                    if "should be ≤" in str(e) and "instead was" in str(e):
                        # 批次大小錯誤，進一步拆分
                        logger.warning(f"批次大小 {len(batch)} 仍然太大，嘗試拆分為更小批次")
                        smaller_batch_size = min(50, len(batch) // 2)
                        for j in range(0, len(batch), smaller_batch_size):
                            small_batch = batch[j:j + smaller_batch_size]
                            logger.info(f"上傳小批次: {len(small_batch)} 個blocks")
                            rate_limiter.wait()  # Rate limiting
                            notion.blocks.children.append(
                                block_id=page_id,
                                children=small_batch,
                            )
                        break
                    else:
                        logger.warning(f"第 {attempt + 1} 次嘗試失敗: {str(e)}")
                        if attempt < MAX_RETRIES - 1:
                            time.sleep(RETRY_DELAY)
                        else:
                            raise
                except Exception as e:
                    logger.warning(f"第 {attempt + 1} 次嘗試出現未預期錯誤: {str(e)}")
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(RETRY_DELAY)
                    else:
                        raise
            
    except Exception as e:
        logger.error(f"上傳blocks時發生錯誤: {str(e)}")
        logger.error(f"嘗試上傳的總blocks數量: {len(blocks)}")
        logger.error(f"失敗的頁面ID: {page_id}")
        raise

def get_google_books_cover(title):
    """透過 Google Books API 查詢書籍封面（高解析度）"""
    url = f"https://www.googleapis.com/books/v1/volumes?q=intitle:{title.replace(' ', '+')}&maxResults=1"
    response = requests.get(url)
    logger.debug(f"Google Books API Response: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        logger.debug(f"Google Books API Data: {data}")
        if "items" in data and len(data["items"]) > 0:
            volume_info = data["items"][0]["volumeInfo"]
            if "imageLinks" in volume_info:
                thumbnail_url = volume_info["imageLinks"].get("thumbnail")
                if thumbnail_url:
                    # 替換 `zoom=1` 為 `zoom=3` 取得較高清封面
                    high_res_url = thumbnail_url.replace("&zoom=1", "&zoom=3")
                    logger.debug(f"Found High-Res Cover: {high_res_url}")
                    return high_res_url
    logger.debug("No Google Books cover found.")
    return None

def get_openlibrary_cover(isbn):
    """透過 Open Library API 取得封面"""
    cover_url = f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg"
    logger.debug(f"Trying Open Library cover: {cover_url}")
    return cover_url

def get_best_book_cover(title, isbn):
    """優先使用 Google Books API，若失敗則使用 Open Library API"""
    logger.debug(f"Searching cover for: {title} (ISBN: {isbn})")
    cover_url = get_google_books_cover(title)
    if cover_url:
        return cover_url
    if isbn:
        return get_openlibrary_cover(isbn)
    logger.debug("No cover found from any source.")
    return None

def update_notion_cover_and_icon(page_id, cover_url):
    """更新 Notion 頁面的封面與圖示為書籍封面"""
    logger.debug(f"Updating Notion cover and icon for page {page_id} with URL: {cover_url}")
    if cover_url:
        rate_limiter.wait()  # Rate limiting
        notion.pages.update(
            page_id=page_id,
            icon={
                "type": "external",
                "external": {"url": cover_url}
            },
            cover={
                "type": "external",
                "external": {"url": cover_url}
            }
        )
        logger.info(f"Updated cover and icon for page {page_id}.")
    else:
        logger.debug("No cover image found.")


@lru_cache(maxsize=100)
def get_cached_page_info(page_id):
    """快取頁面資訊，避免重複請求"""
    rate_limiter.wait()  # Rate limiting
    return notion.pages.retrieve(page_id)


def check_notion_icon(page_id):
    """檢查 Notion 頁面是否已有封面圖示"""
    page = get_cached_page_info(page_id)
    icon = page.get("icon") or {}  # 確保 icon 為 dict
    has_icon = isinstance(icon, dict) and icon.get("type") == "external" and "url" in icon.get("external", {})
    logger.debug(f"Page {page_id} has icon: {has_icon}")
    return has_icon

def add_book_cover_to_notion(title, isbn, page_id):
    if not check_notion_icon(page_id):
        cover_url = get_best_book_cover(title, isbn)
        if cover_url:
            update_notion_cover_and_icon(page_id, cover_url)
        else:
            logger.debug("No cover image available.")
    else:
        logger.debug("Notion page already has a cover icon.")

def process_single_book(book):
    """处理单本书籍的函数 - 優化版本，減少 API 調用次數"""
    logger.info(f"Processing book: {book.get_title()}")
    try:
        title = get_title_without_subtitle(book.get_title())
        bookStatus = check_target(title, True) or {}

        if bookStatus["is_target_valid"]:
            # 已導出的書籍：只更新時間相關屬性（使用批次更新）
            logger.info(f"Book {title} already exported, updating reading time")
            page_id = bookStatus["pageId"]
            # 使用批次更新取代多個獨立調用
            time_properties = build_page_properties(book, include_time=True, include_metadata=False)
            if time_properties:
                update_book_properties_batch(page_id, time_properties)
            add_book_cover_to_notion(book.get_title(), book.get_isbn(), page_id)
            return True
        else:
            unDoneObj = check_target(title, False)
            page_id = unDoneObj["pageId"]

            if not unDoneObj["is_target_valid"]:
                logger.info(f"Book {title} doesn't exist, creating new entry")
                # 直接使用返回的 page_id，避免額外查詢
                page_id = add_entry_by_title(title)
                if not page_id:
                    logger.error(f"Failed to create entry for {title}")
                    return False
            else:
                logger.info(f"Book {title} exists, appending highlights")
                return True

            # 使用新的带章节信息的高亮内容函数
            highlights_with_chapter = DBReader.getHLWithChapterFromDB(book.get_id())
            logger.info(f"Found {len(highlights_with_chapter)} highlights with chapter info for book {title}")
            sync_book_highlights_with_chapter(page_id, highlights_with_chapter)

            # 批次更新所有屬性（時間 + 元數據），減少 API 調用
            all_properties = build_page_properties(book, include_time=True, include_metadata=True)
            if all_properties:
                update_book_properties_batch(page_id, all_properties)
                logger.info(f"Batch updated all properties for {title}")

            add_book_cover_to_notion(book.get_title(), book.get_isbn(), page_id)

            # Generate and sync Zettelkasten cards (if enabled)
            if ENABLE_ZETTELKASTEN_CARDS and ZETTELKASTEN_AVAILABLE:
                logger.info(f"Starting Zettelkasten card generation for {title}")
                cards_synced = generate_and_sync_zettelkasten_cards(
                    book=book,
                    highlights_with_chapter=highlights_with_chapter,
                    highlights_page_id=page_id
                )
                if cards_synced > 0:
                    logger.info(f"Successfully created {cards_synced} Zettelkasten cards for {title}")

            return True

    except Exception as error:
        logger.error(f"Error processing book {book.get_title()}: {str(error)}", exc_info=True)
        return False

def export_highlights():
    logger.info("Starting export highlights process")
    bookList = DBReader.getBookInfoFromDB()
    logger.info(f"Found {len(bookList)} books to process")
    
    # 使用线程池进行并行处理
    max_workers = min(10, len(bookList))  # 最多10个线程，或书籍数量（取较小值）
    success_count = 0
    fail_count = 0
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有任务
        future_to_book = {executor.submit(process_single_book, book): book for book in bookList}
        
        # 处理完成的任务
        for future in as_completed(future_to_book):
            book = future_to_book[future]
            try:
                if future.result():
                    success_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                logger.error(f"Error processing book {book.get_title()}: {str(e)}", exc_info=True)
                fail_count += 1
    
    logger.info(f"Export completed. Success: {success_count}, Failed: {fail_count}")

def main():
    logger.info("Starting Kobo to Notion sync process")
    try:
        export_highlights()
        logger.info("Sync process completed successfully")
    except Exception as e:
        logger.error(f"Fatal error in main process: {str(e)}", exc_info=True)

if __name__ == "__main__":
    main()