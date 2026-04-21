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
    """从文本内容中提取真正的章节标题，增強驗證邏輯和真實標題識別"""
    try:
        if not text or len(text.strip()) > 150:  # 稍微放寬長度限制，真實標題可能較長
            return None
        
        text_clean = text.strip()
        
        # 基本長度檢查
        if len(text_clean) > 150:
            return None
        
        # 檢查標點符號密度 - 但對冒號更寬容
        punctuation_ratio = sum(1 for c in text_clean if c in '。！？；，、') / len(text_clean) if text_clean else 0
        if punctuation_ratio > 0.4:  # 提高容忍度
            return None
            
        # 檢查是否像章節標題
        is_chapter_title = False
        has_chapter_keywords = False
        confidence_score = 0
        
        # 模式1：包含"："或"："的文本（高置信度）
        if '：' in text_clean or ':' in text_clean:
            is_chapter_title = True
            confidence_score += 3
            
            # 特別檢查是否為國家/地區相關標題（從分析中發現的模式）
            if any(keyword in text_clean for keyword in ['美國', '中國', '日本', '台灣', '韓國', '強項', '優勢', '特色']):
                confidence_score += 2
                has_chapter_keywords = True
        
        # 模式2：數字開頭
        elif re.match(r'^\d+\.', text_clean):
            is_chapter_title = True
            confidence_score += 2
        
        # 模式3：中文數字開頭
        elif re.match(r'^[一二三四五六七八九十]+\.', text_clean):
            is_chapter_title = True
            confidence_score += 2
        
        # 模式4：包含"第X章"
        elif re.search(r'第[一二三四五六七八九十\d]+章', text_clean):
            is_chapter_title = True
            has_chapter_keywords = True
            confidence_score += 4
        
        # 模式5：包含"Chapter"
        elif re.search(r'Chapter\s*\d+', text_clean, re.IGNORECASE):
            is_chapter_title = True
            has_chapter_keywords = True
            confidence_score += 4
        
        # 模式6：特定關鍵詞
        elif any(keyword in text_clean for keyword in ['序', '前言', '導讀', '引言', '結語', '後記', '附錄', '目錄']):
            is_chapter_title = True
            has_chapter_keywords = True
            confidence_score += 3
            
        # 模式7：入口X格式（從主控力書籍發現）
        elif re.search(r'入口\s*[０-９\d]+\s*[：:]', text_clean):
            is_chapter_title = True
            has_chapter_keywords = True
            confidence_score += 4
            
        # 模式8：對抗/防護等動作類標題
        elif re.search(r'^[對抗|防護|掌握|學會|了解|認識|建立].+[：:]', text_clean):
            is_chapter_title = True
            confidence_score += 2
            
        # 模式9：短文本且結構化
        elif len(text_clean) < 40 and ('：' in text_clean or ':' in text_clean):
            is_chapter_title = True
            confidence_score += 1
            
        # 模式10：純粹的動名詞短語（可能是章節名）
        elif (len(text_clean) < 30 and 
              not text_clean.endswith(('。', '！', '？', '.', '，', '；')) and
              len([c for c in text_clean if c.isalnum()]) / len(text_clean) > 0.7):
            is_chapter_title = True
            confidence_score += 1
            
        # 模式11：概念定義型標題（新增）
        elif re.match(r'^「.+」', text_clean):
            # 引號內的概念，如「反向思考」、「心智模式」
            if len(text_clean) < 60:
                is_chapter_title = True
                confidence_score += 3
                has_chapter_keywords = True
                
        # 模式12：帶英文翻譯的概念（新增）
        elif re.search(r'^「.+?」\s*[（(].+?[）)]', text_clean):
            # 如「反向思考」（inverse thinking）
            # 提取引號和括號部分作為標題
            match = re.match(r'^(「.+?」\s*[（(].+?[）)])', text_clean)
            if match and len(match.group(1)) < 80:
                extracted_title = match.group(1)
                is_chapter_title = True
                confidence_score += 5
                has_chapter_keywords = True
                # 直接返回提取的部分而不是整個文本
                if confidence_score >= 2:
                    return extracted_title
                
        # 模式13：學術/專業概念（新增）
        elif re.search(r'^[「"](.{2,20})[」"]', text_clean):
            # 引號內的短概念
            if len(text_clean) < 50:
                is_chapter_title = True
                confidence_score += 2
                has_chapter_keywords = True
            
        # 額外驗證：如果文本較長但置信度不高，可能不是標題
        if is_chapter_title and len(text_clean) > 80 and confidence_score < 3:
            return None
            
        # 檢查是否是完整句子（但允許部分例外）
        if (is_chapter_title and 
            text_clean.endswith(('。', '！', '？')) and 
            len(text_clean) > 50 and
            confidence_score < 3):
            return None
        
        # 需要足夠的置信度
        if is_chapter_title and confidence_score >= 2:
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

def extract_chapter_order_info(content_id):
    """從ContentID中提取章節順序信息"""
    try:
        # 提取各種章節編號格式
        patterns = [
            # Section格式: Section0001, Section0012 等
            (r'Section(\d+)', lambda m: int(m.group(1))),
            
            # 數字格式: 01.xhtml, 12.xhtml 等  
            (r'/(\d+)\.xhtml', lambda m: int(m.group(1))),
            
            # Chapter格式: chapter01, chapter12 等
            (r'chapter(\d+)', lambda m: int(m.group(1)), re.IGNORECASE),
            
            # Part格式: part1, part2 等
            (r'part(\d+)', lambda m: int(m.group(1)), re.IGNORECASE),
            
            # 中文格式: 第1章, 第12章 等 (如果出現在路徑中)
            (r'第(\d+)章', lambda m: int(m.group(1))),
        ]
        
        for pattern, extractor, *flags in patterns:
            flag = flags[0] if flags else 0
            match = re.search(pattern, content_id, flag)
            if match:
                order_num = extractor(match)
                identifier = match.group(0)
                return order_num, identifier
        
        # 如果沒有找到數字，嘗試其他識別符
        special_orders = {
            'prologue': 0,      # 序言
            'preface': 1,       # 前言  
            'introduction': 2,  # 引言
            'epilogue': 9999,   # 尾聲
            'appendix': 10000,  # 附錄
            'bibliography': 10001,  # 參考文獻
        }
        
        content_lower = content_id.lower()
        for keyword, order in special_orders.items():
            if keyword in content_lower:
                return order, keyword
                
        # 默認使用一個很大的數字，讓未識別的章節排在後面
        return 99999, "unknown"
        
    except Exception as e:
        print(f"提取章節順序信息時出錯: {e}")
        return 99999, "error"

def create_progress_based_chapters_with_real_titles(highlights_with_chapter, num_chapters=None):
    """基於畫線進度分佈自動建立章節區間，並嘗試使用真實章節標題"""
    if not highlights_with_chapter:
        return []
    
    # 提取所有有效的進度值並排序
    all_progresses = []
    real_chapter_titles = {}  # 存儲發現的真實章節標題
    
    for highlight_info in highlights_with_chapter:
        progress = highlight_info.get('chapter_progress', 0)
        if progress is not None and progress > 0:
            all_progresses.append((progress, highlight_info))
            
            # 檢查是否包含真實章節標題
            text = highlight_info.get('text', '')
            real_title = extract_real_chapter_title(text, highlight_info.get('content_id', ''))
            if real_title:
                real_chapter_titles[progress] = real_title
    
    # 按進度排序
    all_progresses.sort(key=lambda x: x[0])
    
    print(f"總共 {len(all_progresses)} 個有效畫線，進度範圍：{all_progresses[0][0]:.3f} - {all_progresses[-1][0]:.3f}")
    print(f"發現 {len(real_chapter_titles)} 個可能的真實章節標題")
    
    # 如果沒有指定章節數，使用自適應方法
    if num_chapters is None:
        # 基於畫線密度和真實標題數量決定章節數
        estimated_chapters = min(20, max(3, len(all_progresses) // 2))
        # 如果有真實標題，考慮使用接近的章節數
        if real_chapter_titles:
            title_based_estimate = min(15, max(len(real_chapter_titles), len(real_chapter_titles) * 2))
            estimated_chapters = min(estimated_chapters, title_based_estimate)
        num_chapters = estimated_chapters
    
    print(f"自動劃分為 {num_chapters} 個章節")
    
    # 計算章節分界點
    total_highlights = len(all_progresses)
    highlights_per_chapter = total_highlights / num_chapters
    
    chapter_highlights = []
    current_chapter = []
    
    for i, (progress, highlight_info) in enumerate(all_progresses):
        current_chapter.append(highlight_info)
        
        # 檢查是否應該結束當前章節
        should_end_chapter = False
        
        if len(chapter_highlights) < num_chapters - 1:  # 不是最後一章
            expected_end = (len(chapter_highlights) + 1) * highlights_per_chapter
            
            # 如果達到預期大小，或下一個畫線進度跨度較大，則結束章節
            if i + 1 >= expected_end:
                if i + 1 < total_highlights:
                    next_progress = all_progresses[i + 1][0]
                    progress_gap = next_progress - progress
                    # 如果進度跨度大於0.05（5%）或發現真實標題分界，則認為是章節分界
                    if (progress_gap > 0.05 or 
                        len(current_chapter) >= highlights_per_chapter * 1.5 or
                        next_progress in real_chapter_titles):
                        should_end_chapter = True
                else:
                    should_end_chapter = True
        
        if should_end_chapter or i == total_highlights - 1:  # 最後一個畫線
            if current_chapter:
                chapter_highlights.append(current_chapter)
                current_chapter = []
    
    # 為每個章節分配名稱和編號，優先使用真實標題
    reorganized_highlights = []
    
    print("=== 基於進度分佈和真實標題的章節劃分結果 ===")
    
    for i, chapter_highlights_list in enumerate(chapter_highlights):
        chapter_num = i + 1
        
        # 計算章節統計信息
        progresses = [h.get('chapter_progress', 0) for h in chapter_highlights_list]
        valid_progresses = [p for p in progresses if p > 0]
        
        if valid_progresses:
            min_progress = min(valid_progresses)
            max_progress = max(valid_progresses)
            avg_progress = sum(valid_progresses) / len(valid_progresses)
        else:
            min_progress = max_progress = avg_progress = 0
        
        # 尋找這個章節範圍內的真實標題
        chapter_title = None
        best_title_score = 0
        
        for progress in valid_progresses:
            if progress in real_chapter_titles:
                title = real_chapter_titles[progress]
                # 計算標題的置信度分數
                score = calculate_title_confidence(title)
                if score > best_title_score:
                    best_title_score = score
                    chapter_title = title
        
        # 如果沒有找到真實標題，使用默認名稱
        if not chapter_title:
            chapter_title = f"第{chapter_num}章"
        else:
            # 限制標題長度，避免過長
            if len(chapter_title) > 60:
                chapter_title = chapter_title[:57] + "..."
        
        print(f"第{chapter_num:2d}章: 進度範圍 {min_progress:.3f}-{max_progress:.3f}, "
              f"平均 {avg_progress:.3f}, {len(chapter_highlights_list)} 個高亮")
        print(f"         標題: {chapter_title}")
        
        # 更新章節信息
        for highlight_info in chapter_highlights_list:
            highlight_info['chapter_name'] = chapter_title
            highlight_info['chapter_number'] = chapter_num
            highlight_info['chapter_min_progress'] = min_progress
            highlight_info['chapter_max_progress'] = max_progress
            highlight_info['chapter_avg_progress'] = avg_progress
            highlight_info['has_real_title'] = chapter_title != f"第{chapter_num}章"
        
        reorganized_highlights.extend(chapter_highlights_list)
    
    return reorganized_highlights

def calculate_title_confidence(title):
    """計算章節標題的置信度分數"""
    if not title:
        return 0
    
    score = 0
    
    # 長度合理
    if 5 <= len(title) <= 50:
        score += 2
    elif 3 <= len(title) <= 80:
        score += 1
    
    # 包含冒號
    if '：' in title or ':' in title:
        score += 3
    
    # 包含章節關鍵詞
    chapter_keywords = ['第', '章', 'Chapter', '序', '前言', '引言', '結語', '入口', '步驟']
    if any(kw in title for kw in chapter_keywords):
        score += 2
    
    # 包含動作詞
    action_keywords = ['對抗', '掌握', '學會', '了解', '認識', '建立', '防護']
    if any(kw in title for kw in action_keywords):
        score += 1
    
    # 不是完整句子
    if not title.endswith(('。', '！', '？')):
        score += 1
    
    return score

def smart_sort_highlights_by_chapter(highlights_with_chapter):
    """智能排序高亮內容：基於畫線進度重新劃分章節，並使用真實章節標題"""
    if not highlights_with_chapter:
        return []
    
    print(f"開始基於進度的智能章節重組（含真實標題提取），原始高亮數：{len(highlights_with_chapter)}")
    
    # 第一步：基於進度分佈重新劃分章節，並提取真實標題
    reorganized_highlights = create_progress_based_chapters_with_real_titles(highlights_with_chapter)
    
    # 第二步：按章節編號和進度排序
    sorted_highlights = sorted(reorganized_highlights, key=lambda x: (
        x.get('chapter_number', 999),     # 主要排序：章節編號
        x.get('chapter_progress', 0),     # 次要排序：章節內進度
    ))
    
    print(f"\n=== 重組後的章節順序驗證（含真實標題）===")
    current_chapter = 0
    chapter_count = 0
    real_title_count = 0
    
    for highlight in sorted_highlights:
        chapter_num = highlight.get('chapter_number', 0)
        if chapter_num != current_chapter:
            current_chapter = chapter_num
            chapter_count += 1
            chapter_name = highlight.get('chapter_name', f'第{chapter_num}章')
            min_prog = highlight.get('chapter_min_progress', 0)
            max_prog = highlight.get('chapter_max_progress', 0)
            has_real_title = highlight.get('has_real_title', False)
            
            status = "📖" if has_real_title else "📄"
            print(f"  {status} {chapter_name}: {min_prog:.3f} - {max_prog:.3f}")
            
            if has_real_title:
                real_title_count += 1
    
    print(f"✅ 重組完成：{chapter_count} 個章節，{len(sorted_highlights)} 個高亮")
    print(f"📖 真實標題：{real_title_count} 個，📄 默認標題：{chapter_count - real_title_count} 個")
    
    return sorted_highlights
    