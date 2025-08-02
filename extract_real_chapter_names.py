#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
嘗試提取真正的章節名稱
參考 kobo-up 項目的實現方式
"""

import sqlite3
import os
import re

def extract_real_chapter_names():
    """嘗試提取真正的章節名稱"""
    
    if not os.path.exists('KoboReader.sqlite'):
        print("❌ 錯誤：找不到 KoboReader.sqlite 文件")
        return
    
    db = sqlite3.connect("KoboReader.sqlite")
    
    print("🔍 嘗試提取真正的章節名稱")
    print("=" * 50)
    
    try:
        # 獲取第一本書
        cursor = db.execute("""
            SELECT DISTINCT content.ContentId, content.Title
            FROM Bookmark 
            INNER JOIN content ON Bookmark.VolumeID = content.ContentID 
            LIMIT 1
        """)
        
        book_info = cursor.fetchone()
        if not book_info:
            print("❌ 沒有找到任何書籍")
            return
        
        book_id, book_title = book_info
        print(f"📖 分析書籍：{book_title}")
        print(f"🆔 書籍ID：{book_id}")
        print()
        
        # 獲取該書籍的所有高亮記錄
        cursor = db.execute("""
            SELECT Bookmark.Text, Bookmark.ContentID, Bookmark.ChapterProgress, 
                   Bookmark.StartContainerPath, Bookmark.EndContainerPath,
                   content.ChapterIDBookmarked, content.CurrentChapterEstimate, content.CurrentChapterProgress
            FROM Bookmark 
            INNER JOIN content ON Bookmark.VolumeID = content.ContentID 
            WHERE Bookmark.VolumeID = ?
        """, (book_id,))
        
        rows = cursor.fetchall()
        print(f"📝 找到 {len(rows)} 條高亮記錄")
        print()
        
        # 分析每個記錄，嘗試提取真正的章節名稱
        for i, row in enumerate(rows[:10]):  # 只分析前10個
            text, bookmark_content_id, chapter_progress, start_container_path, end_container_path, chapter_id_bookmarked, current_chapter_estimate, current_chapter_progress = row
            
            print(f"--- 記錄 {i+1} ---")
            print(f"文本: {text[:50]}...")
            print(f"ContentID: {bookmark_content_id}")
            print(f"ChapterIDBookmarked: {chapter_id_bookmarked}")
            print()
            
            # 方法1：從ContentID提取章節文件名
            if '!OEBPS!Text/' in bookmark_content_id:
                chapter_file = bookmark_content_id.split('!OEBPS!Text/')[1]
                chapter_name = chapter_file.replace('.xhtml', '')
                print(f"  方法1 (ContentID): {chapter_name}")
            else:
                print(f"  方法1 (ContentID): 不適用")
            
            # 方法2：從ChapterIDBookmarked提取
            if chapter_id_bookmarked and 'OEBPS/Text/' in chapter_id_bookmarked:
                chapter_file = chapter_id_bookmarked.split('OEBPS/Text/')[1]
                if '.xhtml' in chapter_file:
                    chapter_name = chapter_file.split('.xhtml')[0]
                    print(f"  方法2 (ChapterIDBookmarked): {chapter_name}")
                else:
                    print(f"  方法2 (ChapterIDBookmarked): 格式不匹配")
            else:
                print(f"  方法2 (ChapterIDBookmarked): 不適用")
            
            # 方法3：嘗試從StartContainerPath提取
            if start_container_path and 'OEBPS/Text/' in start_container_path:
                text_part = start_container_path.split('OEBPS/Text/')[1]
                if '.xhtml' in text_part:
                    chapter_name = text_part.split('.xhtml')[0]
                    print(f"  方法3 (StartContainerPath): {chapter_name}")
                else:
                    print(f"  方法3 (StartContainerPath): 格式不匹配")
            else:
                print(f"  方法3 (StartContainerPath): 不適用")
            
            # 方法4：嘗試從文本內容推斷章節名稱
            # 檢查文本是否包含章節標題的線索
            text_lines = text.split('\n')
            chapter_title_candidates = []
            for line in text_lines:
                line = line.strip()
                # 檢查是否像章節標題（短行，包含數字或特定關鍵詞）
                if len(line) < 100 and (re.search(r'第[一二三四五六七八九十\d]+章', line) or 
                                       re.search(r'Chapter\s*\d+', line, re.IGNORECASE) or
                                       re.search(r'^\d+\.', line) or
                                       re.search(r'^[一二三四五六七八九十\d]+\.', line)):
                    chapter_title_candidates.append(line)
            
            if chapter_title_candidates:
                print(f"  方法4 (文本推斷): {chapter_title_candidates}")
            else:
                print(f"  方法4 (文本推斷): 未找到章節標題線索")
            
            print()
        
        # 分析所有不同的章節文件
        print("📊 所有章節文件分析：")
        cursor = db.execute("""
            SELECT DISTINCT Bookmark.ContentID
            FROM Bookmark 
            WHERE Bookmark.VolumeID = ?
        """, (book_id,))
        
        content_ids = cursor.fetchall()
        chapter_files = set()
        for content_id in content_ids:
            if '!OEBPS!Text/' in content_id[0]:
                chapter_file = content_id[0].split('!OEBPS!Text/')[1]
                chapter_name = chapter_file.replace('.xhtml', '')
                chapter_files.add(chapter_name)
        
        print("發現的章節文件：")
        for chapter in sorted(chapter_files):
            print(f"  - {chapter}")
        
        print()
        
        # 嘗試從文本內容中提取章節標題
        print("🔍 嘗試從文本內容提取章節標題：")
        cursor = db.execute("""
            SELECT Bookmark.Text
            FROM Bookmark 
            WHERE Bookmark.VolumeID = ? AND LENGTH(Bookmark.Text) < 200
        """, (book_id,))
        
        short_texts = cursor.fetchall()
        potential_titles = []
        for text_row in short_texts:
            text = text_row[0]
            if text and len(text.strip()) < 100:
                # 檢查是否像章節標題
                if (re.search(r'第[一二三四五六七八九十\d]+章', text) or 
                    re.search(r'Chapter\s*\d+', text, re.IGNORECASE) or
                    re.search(r'^\d+\.', text) or
                    re.search(r'^[一二三四五六七八九十\d]+\.', text) or
                    '序' in text or '前言' in text or '導讀' in text):
                    potential_titles.append(text.strip())
        
        if potential_titles:
            print("發現的潛在章節標題：")
            for title in potential_titles[:10]:  # 只顯示前10個
                print(f"  - {title}")
        else:
            print("未發現明顯的章節標題")
        
        print()
        
    except Exception as e:
        print(f"❌ 錯誤：{e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    extract_real_chapter_names() 