#!/usr/bin/env python3
"""
嘗試從EPUB內容中提取真實章節標題
"""
import sqlite3
import DBReader
import re
from html.parser import HTMLParser
import xml.etree.ElementTree as ET

class ChapterTitleExtractor(HTMLParser):
    """HTML解析器，專門用於提取章節標題"""
    
    def __init__(self):
        super().__init__()
        self.current_tag = None
        self.title_candidates = []
        self.in_heading = False
        self.heading_level = 0
        
    def handle_starttag(self, tag, attrs):
        self.current_tag = tag.lower()
        
        # 檢查標題標籤
        if tag.lower() in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            self.in_heading = True
            self.heading_level = int(tag[1])
            
        # 檢查有class="chapter"或類似的div
        if tag.lower() == 'div':
            for attr_name, attr_value in attrs:
                if attr_name.lower() == 'class' and 'chapter' in attr_value.lower():
                    self.in_heading = True
    
    def handle_endtag(self, tag):
        if tag.lower() in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            self.in_heading = False
            self.heading_level = 0
        if tag.lower() == 'div':
            self.in_heading = False
        self.current_tag = None
    
    def handle_data(self, data):
        if self.in_heading and data.strip():
            clean_data = data.strip()
            if len(clean_data) > 1 and len(clean_data) < 200:
                self.title_candidates.append({
                    'text': clean_data,
                    'tag': self.current_tag,
                    'level': self.heading_level
                })

def analyze_formatted_pages():
    """分析FormattedPage內容尋找章節標題"""
    print("=== 分析FormattedPage內容 ===\n")
    
    db = DBReader.get_db_connection()
    cursor = db.cursor()
    
    try:
        # 檢查shortcover_page表的內容
        cursor.execute("""
            SELECT sp.shortcoverId, sp.PageNumber, sp.FormattedPage,
                   c.Title, c.Attribution
            FROM shortcover_page sp
            JOIN content c ON sp.shortcoverId LIKE '%' || c.ContentID || '%'
            WHERE sp.FormattedPage IS NOT NULL
            AND LENGTH(sp.FormattedPage) > 0
            ORDER BY c.Title, sp.shortcoverId, sp.PageNumber
            LIMIT 20;
        """)
        
        results = cursor.fetchall()
        
        if results:
            print(f"找到 {len(results)} 個FormattedPage記錄")
            
            current_book = ""
            for short_id, page_num, formatted_page, title, author in results:
                book_identifier = f"{title} - {author}" if title and author else short_id
                
                if book_identifier != current_book:
                    print(f"\n{'='*60}")
                    print(f"書籍: {book_identifier}")
                    print(f"{'='*60}")
                    current_book = book_identifier
                
                print(f"\nPage {page_num} (ID: {short_id[-20:]})")
                
                if formatted_page:
                    # 嘗試解析HTML內容
                    chapter_titles = extract_titles_from_html(formatted_page)
                    
                    if chapter_titles:
                        print("  找到可能的章節標題:")
                        for title_info in chapter_titles:
                            print(f"    [{title_info['tag'] or 'text'}] {title_info['text']}")
                    else:
                        # 如果HTML解析失敗，顯示文本預覽
                        text_preview = clean_html_simple(formatted_page)[:200]
                        print(f"  內容預覽: {text_preview}...")
                        
                        # 用正則表達式搜尋可能的標題
                        title_patterns = find_title_patterns(text_preview)
                        if title_patterns:
                            print("  正則表達式找到的標題:")
                            for pattern in title_patterns:
                                print(f"    {pattern}")
        else:
            print("沒有找到FormattedPage內容")
            
    except Exception as e:
        print(f"分析FormattedPage時出錯: {e}")
    finally:
        db.close()

def extract_titles_from_html(html_content):
    """從HTML內容中提取標題"""
    try:
        extractor = ChapterTitleExtractor()
        extractor.feed(html_content)
        
        # 過濾和排序結果
        valid_titles = []
        for candidate in extractor.title_candidates:
            text = candidate['text']
            
            # 過濾條件
            if (len(text) > 3 and len(text) < 150 and
                not text.isdigit() and
                not text.lower().startswith('http') and
                '>' not in text and '<' not in text):
                
                valid_titles.append(candidate)
        
        return valid_titles[:5]  # 返回前5個候選標題
        
    except Exception as e:
        print(f"HTML解析錯誤: {e}")
        return []

def clean_html_simple(html_content):
    """簡單的HTML清理"""
    # 移除HTML標籤
    clean = re.sub(r'<[^>]+>', '', html_content)
    # 清理多餘空白
    clean = re.sub(r'\s+', ' ', clean)
    return clean.strip()

def find_title_patterns(text):
    """使用正則表達式尋找可能的標題模式"""
    patterns = []
    
    # 模式1: 第X章 xxx
    matches = re.findall(r'第\s*[零一二三四五六七八九十\d]+\s*章\s*[^\n\r]{1,50}', text)
    patterns.extend(matches)
    
    # 模式2: Chapter X: xxx
    matches = re.findall(r'Chapter\s+\d+\s*[:\-]\s*[^\n\r]{1,50}', text, re.IGNORECASE)
    patterns.extend(matches)
    
    # 模式3: 獨立的短行（可能是標題）
    lines = text.split('\n')
    for line in lines:
        line = line.strip()
        if (5 < len(line) < 80 and 
            not line.endswith('.') and 
            not line.endswith('。') and
            not line.startswith('http') and
            ':' in line or '：' in line):
            patterns.append(line)
    
    return patterns[:3]  # 返回前3個模式

def analyze_bookmark_text_for_titles():
    """分析Bookmark表中的Text欄位，尋找可能的章節標題"""
    print("\n" + "="*60)
    print("=== 從Bookmark文本中尋找章節標題 ===\n")
    
    db = DBReader.get_db_connection()
    cursor = db.cursor()
    
    try:
        # 獲取可能的章節標題（短文本，包含特定關鍵詞）
        cursor.execute("""
            SELECT DISTINCT b.Text, b.ContentID, c.Title
            FROM Bookmark b
            JOIN content c ON b.VolumeID = c.ContentID
            WHERE b.Text IS NOT NULL
            AND LENGTH(b.Text) BETWEEN 5 AND 100
            AND (b.Text LIKE '%第%章%' 
                 OR b.Text LIKE '%Chapter%'
                 OR b.Text LIKE '%：%'
                 OR b.Text LIKE '%序%'
                 OR b.Text LIKE '%前言%'
                 OR b.Text LIKE '%引言%'
                 OR b.Text LIKE '%結語%')
            ORDER BY c.Title, LENGTH(b.Text)
            LIMIT 30;
        """)
        
        results = cursor.fetchall()
        
        if results:
            print(f"從Bookmark中找到 {len(results)} 個可能的章節標題:")
            
            current_book = ""
            for text, content_id, book_title in results:
                
                if book_title != current_book:
                    print(f"\n--- {book_title} ---")
                    current_book = book_title
                
                # 評估是否真的像章節標題
                is_likely_title = evaluate_title_likelihood(text)
                status = "✓" if is_likely_title else "?"
                
                print(f"  {status} {text}")
                if content_id:
                    chapter_hint = DBReader.extract_chapter_name(content_id)
                    if chapter_hint != "未知章节":
                        print(f"    (來自: {chapter_hint})")
        else:
            print("沒有在Bookmark中找到可能的章節標題")
            
    except Exception as e:
        print(f"分析Bookmark文本時出錯: {e}")
    finally:
        db.close()

def evaluate_title_likelihood(text):
    """評估文本是否像章節標題"""
    if not text:
        return False
    
    # 正面指標
    positive_indicators = 0
    
    # 包含章節關鍵詞
    chapter_keywords = ['第', '章', 'Chapter', '序', '前言', '引言', '結語', '附錄']
    for keyword in chapter_keywords:
        if keyword in text:
            positive_indicators += 2
            break
    
    # 包含冒號
    if '：' in text or ':' in text:
        positive_indicators += 1
    
    # 長度適中
    if 10 <= len(text) <= 50:
        positive_indicators += 1
    
    # 負面指標
    negative_indicators = 0
    
    # 包含完整句子結尾
    if text.endswith('。') or text.endswith('.'):
        negative_indicators += 1
    
    # 包含過多標點
    punctuation_count = sum(1 for c in text if c in '。！？；，、')
    if punctuation_count > 3:
        negative_indicators += 1
    
    # 太長
    if len(text) > 80:
        negative_indicators += 1
    
    return positive_indicators >= 2 and negative_indicators <= 1

if __name__ == "__main__":
    analyze_formatted_pages()
    analyze_bookmark_text_for_titles()