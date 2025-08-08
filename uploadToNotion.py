import os
import DBReader
from notion_client import Client
from datetime import datetime
import math
import requests
import logging
from logging.handlers import RotatingFileHandler
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import time
from notion_client.errors import APIResponseError

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

# Initialize Notion client
notion = Client(auth=NOTION_TOKEN)
database = notion.databases.retrieve(NOTION_DATABASE_ID)

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
        print(f"No value provided for {time_property_name}, skipping update.")

def update_book_number(page_id, field_name, value):
    if value is not None:  # 檢查數值是否有提供
        notion.pages.update(
            page_id=page_id,
            properties={
                field_name: {
                    "number": value  # 使用 number 屬性來更新數字
                }
            }
        )
    else:
        print(f"No value provided for {field_name}, skipping update.")

def update_percentage(page_id, value):
    if value is not None:  # 檢查數值是否有提供
        notion.pages.update(
                page_id=page_id,
                properties={
                    "PercentageRead": {
                        "number": value  # 使用 number 屬性來更新數字
                    }
                }
            )
    else:
        print(f"No value provided for PercentageRead, skipping update.")

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
        
        notion.pages.update(
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
    else:
        print(f"No value provided for {text_property_name}, skipping update.")

def update_book_spend_time(page_id, bookSpendingTime):
    hours = math.floor(bookSpendingTime / 3600)
    minutes = math.floor((bookSpendingTime % 3600) / 60)
    seconds = bookSpendingTime % 60
    formatted_time = f"{hours:02}:{minutes:02}:{seconds:02}"

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
    print("Finish Update Time")

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
        notion.pages.update(
            page_id=page_id,
            properties=properties_to_update
        )
    else:
        print("No publisher or author name provided, skipping update.")

def update_book_subtitle(page_id, subtitle):
    if subtitle:  # 檢查 subtitle 是否有值
        notion.pages.update(
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
    else:
        print("No subtitle provided, skipping update.")




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
    print("Append Title")
    print(len(highlights_list))

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

    notion.pages.update(
        page_id=page_id,
        properties={"Exported": {"checkbox": True}},
    )

# 新增：处理带章节信息的高亮内容
def sync_book_highlights_with_chapter(page_id, highlights_with_chapter):
    """同步带章节信息的高亮内容到Notion，使用簡潔的markdown語法格式"""
    blocks = []

    blocks.append({
        "object": "block",
        "type": "heading_1",
        "heading_1": {
            "rich_text": [{"type": "text", "text": {"content": "Highlights"}}],
        },
    })
    print("Append Title")
    print(len(highlights_with_chapter))

    # 按章节分组高亮内容
    chapter_groups = {}
    for highlight_info in highlights_with_chapter:
        chapter_name = highlight_info['chapter_name']
        if chapter_name not in chapter_groups:
            chapter_groups[chapter_name] = []
        chapter_groups[chapter_name].append(highlight_info)

    # 按章节进度排序（階層式排列）
    sorted_chapters = sorted(chapter_groups.items(), key=lambda x: 
        max([h['chapter_progress'] for h in x[1]]) if x[1] else 0)

    # 按章节顺序处理高亮内容
    for chapter_name, highlights in sorted_chapters:
        # 添加章节标题（使用單層級標題，不顯示進度）
        blocks.append({
            "object": "block",
            "type": "heading_1",
            "heading_1": {
                "rich_text": [{"type": "text", "text": {"content": f"📖 {chapter_name}"}}],
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

    notion.pages.update(
        page_id=page_id,
        properties={"Exported": {"checkbox": True}},
    )


def add_entry_by_title(book_title):
    try:
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
        print(f"Entry {book_title} added successfully!")
        return True
    except Exception as error:
        print("Error adding entry:", error)
        return False

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
    print(f"Google Books API Response: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"Google Books API Data: {data}")
        if "items" in data and len(data["items"]) > 0:
            volume_info = data["items"][0]["volumeInfo"]
            if "imageLinks" in volume_info:
                thumbnail_url = volume_info["imageLinks"].get("thumbnail")
                if thumbnail_url:
                    # 替換 `zoom=1` 為 `zoom=3` 取得較高清封面
                    high_res_url = thumbnail_url.replace("&zoom=1", "&zoom=3")
                    print(f"Found High-Res Cover: {high_res_url}")
                    return high_res_url
    print("No Google Books cover found.")
    return None

def get_openlibrary_cover(isbn):
    """透過 Open Library API 取得封面"""
    cover_url = f"https://covers.openlibrary.org/b/isbn/{isbn}-L.jpg"
    print(f"Trying Open Library cover: {cover_url}")
    return cover_url

def get_best_book_cover(title, isbn):
    """優先使用 Google Books API，若失敗則使用 Open Library API"""
    print(f"Searching cover for: {title} (ISBN: {isbn})")
    cover_url = get_google_books_cover(title)
    if cover_url:
        return cover_url
    if isbn:
        return get_openlibrary_cover(isbn)
    print("No cover found from any source.")
    return None

def update_notion_cover_and_icon(page_id, cover_url):
    """更新 Notion 頁面的封面與圖示為書籍封面"""
    print(f"Updating Notion cover and icon for page {page_id} with URL: {cover_url}")
    if cover_url:
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
        print(f"Updated cover and icon for page {page_id}.")
    else:
        print("No cover image found.")


def check_notion_icon(page_id):
    """檢查 Notion 頁面是否已有封面圖示"""
    page = notion.pages.retrieve(page_id)
    icon = page.get("icon") or {}  # 確保 icon 為 dict
    has_icon = isinstance(icon, dict) and icon.get("type") == "external" and "url" in icon.get("external", {})
    print(f"Page {page_id} has icon: {has_icon}")
    return has_icon

def add_book_cover_to_notion(title, isbn, page_id):
    if not check_notion_icon(page_id):
        cover_url = get_best_book_cover(title, isbn)
        if cover_url:
            update_notion_cover_and_icon(page_id, cover_url)
        else:
            print("No cover image available.")
    else:
        print("Notion page already has a cover icon.")

def process_single_book(book):
    """处理单本书籍的函数"""
    logger.info(f"Processing book: {book.get_title()}")
    try:
        title = get_title_without_subtitle(book.get_title())
        bookStatus = check_target(title, True) or {}
        
        if bookStatus["is_target_valid"]:
            logger.info(f"Book {title} already exported, updating reading time")
            update_time_related(bookStatus["pageId"], book)
            add_book_cover_to_notion(book.get_title(), book.get_isbn(), bookStatus["pageId"])
            return True
        else:
            unDoneObj = check_target(title, False)
            page_id = unDoneObj["pageId"]
            
            if not unDoneObj["is_target_valid"]:
                logger.info(f"Book {title} doesn't exist, creating new entry")
                valid = add_entry_by_title(title)
                newObj = check_target(title, False)
                page_id = newObj["pageId"]
            else:
                logger.info(f"Book {title} exists, appending highlights")
                return True
                
            # 使用新的带章节信息的高亮内容函数
            highlights_with_chapter = DBReader.getHLWithChapterFromDB(book.get_id())
            logger.info(f"Found {len(highlights_with_chapter)} highlights with chapter info for book {title}")
            sync_book_highlights_with_chapter(page_id, highlights_with_chapter)
            update_time_related(page_id, book)
            update_book_subtitle(page_id, book.get_subtitle())
            update_book_people(page_id, book.get_publisher(), book.get_author())
            update_book_textinfo(page_id, "Description", book.get_description())
            update_book_textinfo(page_id, "ISBN", book.get_isbn())
            add_book_cover_to_notion(book.get_title(), book.get_isbn(), page_id)
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