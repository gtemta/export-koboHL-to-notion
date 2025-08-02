#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
尋找真正的章節標題
"""

import sqlite3
import os
import re

def find_chapter_titles():
    """尋找真正的章節標題"""
    
    if not os.path.exists('KoboReader.sqlite'):
        print("❌ 錯誤：找不到 KoboReader.sqlite 文件")
        return
    
    db = sqlite3.connect("KoboReader.sqlite")
    
    print("🔍 尋找真正的章節標題")
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
        
        # 尋找可能的章節標題
        print("🔍 尋找章節標題：")
        cursor = db.execute("""
            SELECT Bookmark.Text, Bookmark.ContentID
            FROM Bookmark 
            WHERE Bookmark.VolumeID = ? AND LENGTH(Bookmark.Text) < 300
        """, (book_id,))
        
        rows = cursor.fetchall()
        chapter_titles = []
        
        for text, content_id in rows:
            if text and len(text.strip()) < 200:
                # 檢查是否像章節標題
                text_clean = text.strip()
                
                # 檢查各種章節標題模式
                is_chapter_title = False
                title_type = ""
                
                # 模式1：包含"："的短文本
                if '：' in text_clean and len(text_clean) < 50:
                    is_chapter_title = True
                    title_type = "冒號模式"
                
                # 模式2：數字開頭
                elif re.match(r'^\d+\.', text_clean):
                    is_chapter_title = True
                    title_type = "數字模式"
                
                # 模式3：中文數字開頭
                elif re.match(r'^[一二三四五六七八九十]+\.', text_clean):
                    is_chapter_title = True
                    title_type = "中文數字模式"
                
                # 模式4：包含"第X章"
                elif re.search(r'第[一二三四五六七八九十\d]+章', text_clean):
                    is_chapter_title = True
                    title_type = "第X章模式"
                
                # 模式5：包含"Chapter"
                elif re.search(r'Chapter\s*\d+', text_clean, re.IGNORECASE):
                    is_chapter_title = True
                    title_type = "Chapter模式"
                
                # 模式6：特定關鍵詞
                elif any(keyword in text_clean for keyword in ['序', '前言', '導讀', '引言', '結語', '後記']):
                    is_chapter_title = True
                    title_type = "關鍵詞模式"
                
                # 模式7：短文本且包含特定結構
                elif len(text_clean) < 30 and ('：' in text_clean or ':' in text_clean):
                    is_chapter_title = True
                    title_type = "短文本冒號模式"
                
                if is_chapter_title:
                    # 提取章節文件名
                    if '!OEBPS!Text/' in content_id:
                        chapter_file = content_id.split('!OEBPS!Text/')[1]
                        chapter_name = chapter_file.replace('.xhtml', '')
                    else:
                        chapter_name = "未知"
                    
                    chapter_titles.append({
                        'title': text_clean,
                        'chapter_file': chapter_name,
                        'type': title_type
                    })
        
        # 顯示找到的章節標題
        if chapter_titles:
            print(f"✅ 找到 {len(chapter_titles)} 個可能的章節標題：")
            print()
            
            # 按章節文件分組
            chapter_groups = {}
            for item in chapter_titles:
                chapter_file = item['chapter_file']
                if chapter_file not in chapter_groups:
                    chapter_groups[chapter_file] = []
                chapter_groups[chapter_file].append(item)
            
            for chapter_file in sorted(chapter_groups.keys()):
                print(f"📖 章節文件：{chapter_file}")
                for item in chapter_groups[chapter_file]:
                    print(f"  - {item['title']} ({item['type']})")
                print()
        else:
            print("❌ 未找到明顯的章節標題")
        
        # 檢查是否有其他可能的章節標題模式
        print("🔍 檢查其他可能的章節標題模式：")
        cursor = db.execute("""
            SELECT Bookmark.Text, Bookmark.ContentID
            FROM Bookmark 
            WHERE Bookmark.VolumeID = ? AND LENGTH(Bookmark.Text) < 100
        """, (book_id,))
        
        short_texts = cursor.fetchall()
        other_candidates = []
        
        for text, content_id in short_texts:
            if text and len(text.strip()) < 80:
                text_clean = text.strip()
                # 檢查是否包含常見的章節標題結構
                if (':' in text_clean or '：' in text_clean) and len(text_clean) < 60:
                    other_candidates.append(text_clean)
        
        if other_candidates:
            print("其他可能的章節標題候選：")
            for candidate in other_candidates[:10]:  # 只顯示前10個
                print(f"  - {candidate}")
        else:
            print("未發現其他候選")
        
        print()
        
    except Exception as e:
        print(f"❌ 錯誤：{e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    find_chapter_titles() 