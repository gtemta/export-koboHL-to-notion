import sqlite3
import re
import threading

# 資料庫檔案路徑
DB_PATH = "KoboReader.sqlite"

def get_db_connection():
    """獲取執行緒安全的資料庫連接"""
    return sqlite3.connect(DB_PATH)


getBookListQuery = (
    "SELECT DISTINCT content.ContentId, content.Title, content.Subtitle, content.Attribution AS Author, " +
    "content.DateLastRead, content.TimeSpentReading, content.Description, " +
    "content.Publisher, content.___PercentRead, content.LastTimeFinishedReading, " +
    "content.ISBN " +
    "FROM Bookmark " +
    "INNER JOIN content ON Bookmark.VolumeID = content.ContentID " +
    "ORDER BY content.Title"
)


getHighlightsQuery = (
    "SELECT Bookmark.Text FROM Bookmark " +
    "INNER JOIN content ON Bookmark.VolumeID = content.ContentID " +
    "WHERE content.ContentID = ? "
)

# 新增：获取带章节信息的高亮内容
getHighlightsWithChapterQuery = (
    "SELECT Bookmark.Text, Bookmark.ContentID, Bookmark.ChapterProgress, " +
    "Bookmark.StartContainerPath, Bookmark.EndContainerPath, " +
    "content.ChapterIDBookmarked, content.CurrentChapterEstimate, content.CurrentChapterProgress " +
    "FROM Bookmark " +
    "INNER JOIN content ON Bookmark.VolumeID = content.ContentID " +
    "WHERE Bookmark.VolumeID = ? " +
    "ORDER BY Bookmark.ChapterProgress"
)


class Book:
    def __init__(self, id, title, subtitle, author, date_last_read, time_spent_reading, description, publisher, percent_read, last_time_finished_reading, isbn):
        self.id = id
        self.title = title
        self.subtitle = subtitle
        self.author = author
        self.date_last_read = date_last_read
        self.time_spent_reading = time_spent_reading
        self.description = description
        self.publisher = publisher
        self.percent_read = percent_read
        self.last_time_finished_reading = last_time_finished_reading
        self.isbn = isbn

    def get_id(self):
        return self.id

    def get_title(self):
        return self.title

    def get_subtitle(self):
        return self.subtitle

    def get_author(self):
        return self.author

    def get_date_last_read(self):
        return self.date_last_read

    def get_time_spent_reading(self):
        return self.time_spent_reading

    def get_description(self):
        return self.description

    def get_publisher(self):
        return self.publisher

    def get_percent_read(self):
        return self.percent_read

    def get_last_time_finished_reading(self):
        return self.last_time_finished_reading

    def get_isbn(self):
        return self.isbn



def getBookInfoFromDB():
    try:
        bookList = []
        db = get_db_connection()
        cursor = db.execute(getBookListQuery)
        
        for row in cursor.fetchall():
            # 解包查詢結果中的所有欄位
            id, title, subtitle, author, date_last_read, time_spent_reading, description, publisher, percent_read, last_time_finished_reading, isbn = row
            
            # 創建 Book 物件，傳入所有所需參數
            book = Book(
                id=id,
                title=title,
                subtitle=subtitle,
                author=author,
                date_last_read=date_last_read,
                time_spent_reading=time_spent_reading,
                description=description,
                publisher=publisher,
                percent_read=percent_read,
                last_time_finished_reading=last_time_finished_reading,
                isbn=isbn
            )
            
            # 將 Book 物件加入列表
            bookList.append(book)
    
    except Exception as e:
        print(f"Error getBookInfoFromDB: {e}")
    finally:
        db.close()
    
    return bookList


def getHLFromDB(content_id) :
    highlights_list = []
    db = get_db_connection()
    try:
        cursor = db.execute(getHighlightsQuery, (content_id,))
        for row in cursor.fetchall():
            # print(row[0])
            highlights_list.append(row[0])
        # print(len(highlights_list))
        # print("============================================")
        return highlights_list
    finally:
        db.close()

# 新增：获取带章节信息的高亮内容
def getHLWithChapterFromDB(content_id):
    highlights_with_chapter = []
    db = get_db_connection()
    try:
        cursor = db.execute(getHighlightsWithChapterQuery, (content_id,))
        for row in cursor.fetchall():
            text, bookmark_content_id, chapter_progress, start_container_path, end_container_path, chapter_id_bookmarked, current_chapter_estimate, current_chapter_progress = row
            
            # 優先級順序：1. 從文本內容提取真正章節標題 2. ContentID解析 3. StartContainerPath解析 4. ChapterIDBookmarked解析
        
            # 首先嘗試從文本內容提取真正的章節標題
            real_chapter_title = extract_real_chapter_title(text, bookmark_content_id)
            
            if real_chapter_title:
                chapter_name = real_chapter_title
            else:
                # 如果無法從文本提取，使用原有的方法
                chapter_name = extract_chapter_name(bookmark_content_id)
                
                # 如果從ContentID無法獲取，嘗試從StartContainerPath獲取
                if chapter_name == "未知章节" and start_container_path:
                    container_chapter_name = extract_chapter_name_from_container_path(start_container_path)
                    if container_chapter_name:
                        chapter_name = container_chapter_name
                
                # 如果還是無法獲取，嘗試從content表的ChapterIDBookmarked獲取（但這個字段可能不準確）
                if chapter_name == "未知章节" and chapter_id_bookmarked:
                    content_chapter_name = extract_chapter_name(chapter_id_bookmarked)
                    if content_chapter_name != "未知章节":
                        # 檢查是否為有效的章節名稱（不是通用的章節ID）
                        if not content_chapter_name.startswith('OEBPS/Text/'):
                            chapter_name = content_chapter_name
            
            highlight_info = {
                'text': text,
                'chapter_name': chapter_name,
                'chapter_progress': chapter_progress,
                'content_id': bookmark_content_id,
                'start_container_path': start_container_path,
                'end_container_path': end_container_path,
                'chapter_id_bookmarked': chapter_id_bookmarked,
                'current_chapter_estimate': current_chapter_estimate,
                'current_chapter_progress': current_chapter_progress
            }
            highlights_with_chapter.append(highlight_info)
        
        return highlights_with_chapter
    finally:
        db.close()

def extract_chapter_name(content_id):
    """从ContentID中提取章节名称，支持多种格式"""
    try:
        # 方法1：从ContentID中提取（主要方法）
        if '!OEBPS!Text/' in content_id:
            chapter_part = content_id.split('!OEBPS!Text/')[1]
            # 移除.xhtml扩展名
            chapter_name = chapter_part.replace('.xhtml', '')
            
            # 處理不同的章節命名格式
            # 如果是Section格式，嘗試提取更友好的名稱
            if chapter_name.startswith('Section'):
                # 提取數字部分
                import re
                match = re.search(r'Section(\d+)', chapter_name)
                if match:
                    section_num = int(match.group(1))
                    # 轉換為更友好的章節名稱
                    if section_num <= 10:
                        return f"第{section_num}章"
                    else:
                        return f"章節{section_num}"
                else:
                    return chapter_name
            else:
                # 處理其他格式（如Prologue、01、02等）
                return chapter_name
        
        # 方法2：从item!xhtml格式提取
        elif '!item!xhtml/' in content_id:
            chapter_part = content_id.split('!item!xhtml/')[1]
            chapter_name = chapter_part.replace('.xhtml', '')
            return chapter_name
        
        # 方法3：直接处理文件名格式
        elif '.xhtml' in content_id:
            # 提取最后一个斜杠后的文件名
            parts = content_id.split('/')
            if len(parts) > 1:
                filename = parts[-1]
                chapter_name = filename.replace('.xhtml', '')
                return chapter_name
        
        return "未知章节"
    except Exception as e:
        print(f"提取章节名称时出错: {e}")
        return "未知章节"

def extract_real_chapter_title(text, content_id):
    """从文本内容中提取真正的章节标题"""
    try:
        if not text or len(text.strip()) > 200:
            return None
        
        text_clean = text.strip()
        
        # 檢查是否像章節標題
        is_chapter_title = False
        
        # 模式1：包含"："的短文本
        if '：' in text_clean and len(text_clean) < 50:
            is_chapter_title = True
        
        # 模式2：數字開頭
        elif re.match(r'^\d+\.', text_clean):
            is_chapter_title = True
        
        # 模式3：中文數字開頭
        elif re.match(r'^[一二三四五六七八九十]+\.', text_clean):
            is_chapter_title = True
        
        # 模式4：包含"第X章"
        elif re.search(r'第[一二三四五六七八九十\d]+章', text_clean):
            is_chapter_title = True
        
        # 模式5：包含"Chapter"
        elif re.search(r'Chapter\s*\d+', text_clean, re.IGNORECASE):
            is_chapter_title = True
        
        # 模式6：特定關鍵詞
        elif any(keyword in text_clean for keyword in ['序', '前言', '導讀', '引言', '結語', '後記']):
            is_chapter_title = True
        
        # 模式7：短文本且包含特定結構
        elif len(text_clean) < 30 and ('：' in text_clean or ':' in text_clean):
            is_chapter_title = True
        
        if is_chapter_title:
            return text_clean
        
        return None
    except Exception as e:
        print(f"提取章节标题时出错: {e}")
        return None

def extract_chapter_name_from_container_path(container_path):
    """从StartContainerPath中提取章节名称"""
    try:
        if 'OEBPS/Text/' in container_path:
            # 格式：OEBPS/Text/chapter_name.xhtml#kobo.X.X
            text_part = container_path.split('OEBPS/Text/')[1]
            if '.xhtml' in text_part:
                chapter_name = text_part.split('.xhtml')[0]
                return chapter_name
        return None
    except:
        return None

def get_chapter_name_from_content_table(book_id):
    """从content表中获取章节信息"""
    try:
        query = """
        SELECT DISTINCT ChapterIDBookmarked, CurrentChapterEstimate, CurrentChapterProgress
        FROM content 
        WHERE ContentID = ? AND ChapterIDBookmarked IS NOT NULL
        """
        cursor = db.execute(query, (book_id,))
        result = cursor.fetchone()
        if result:
            chapter_id, estimate, progress = result
            # 从ChapterIDBookmarked中提取章节名称
            if 'OEBPS/Text/' in chapter_id:
                chapter_part = chapter_id.split('OEBPS/Text/')[1]
                if '.xhtml' in chapter_part:
                    chapter_name = chapter_part.split('.xhtml')[0]
                    return chapter_name
        return None
    except Exception as e:
        print(f"从content表获取章节信息时出错: {e}")
        return None
    