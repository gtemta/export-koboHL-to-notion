#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析數據庫中的章節數據結構
"""

import sqlite3
import os

def analyze_chapter_data():
    """分析數據庫中的章節數據結構"""
    
    if not os.path.exists('KoboReader.sqlite'):
        print("❌ 錯誤：找不到 KoboReader.sqlite 文件")
        return
    
    db = sqlite3.connect("KoboReader.sqlite")
    
    print("📊 分析數據庫中的章節數據結構")
    print("=" * 50)
    
    try:
        # 獲取第一本書的ID
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
        
        # 分析Bookmark表中的章節相關字段
        cursor = db.execute("""
            SELECT Bookmark.Text, Bookmark.ContentID, Bookmark.ChapterProgress, 
                   Bookmark.StartContainerPath, Bookmark.EndContainerPath,
                   content.ChapterIDBookmarked, content.CurrentChapterEstimate, content.CurrentChapterProgress
            FROM Bookmark 
            INNER JOIN content ON Bookmark.VolumeID = content.ContentID 
            WHERE Bookmark.VolumeID = ? 
            LIMIT 10
        """, (book_id,))
        
        rows = cursor.fetchall()
        print(f"📝 找到 {len(rows)} 條高亮記錄")
        print()
        
        for i, row in enumerate(rows, 1):
            text, bookmark_content_id, chapter_progress, start_container_path, end_container_path, chapter_id_bookmarked, current_chapter_estimate, current_chapter_progress = row
            
            print(f"--- 記錄 {i} ---")
            print(f"文本: {text[:50]}...")
            print(f"Bookmark.ContentID: {bookmark_content_id}")
            print(f"Bookmark.ChapterProgress: {chapter_progress}")
            print(f"Bookmark.StartContainerPath: {start_container_path}")
            print(f"Bookmark.EndContainerPath: {end_container_path}")
            print(f"content.ChapterIDBookmarked: {chapter_id_bookmarked}")
            print(f"content.CurrentChapterEstimate: {current_chapter_estimate}")
            print(f"content.CurrentChapterProgress: {current_chapter_progress}")
            print()
        
        # 分析所有可能的章節名稱格式
        print("🔍 分析章節名稱格式：")
        print()
        
        # 分析ContentID格式
        cursor = db.execute("""
            SELECT DISTINCT Bookmark.ContentID
            FROM Bookmark 
            WHERE Bookmark.VolumeID = ?
        """, (book_id,))
        
        content_ids = cursor.fetchall()
        print(f"ContentID 格式範例：")
        for content_id in content_ids[:5]:
            print(f"  {content_id[0]}")
        print()
        
        # 分析StartContainerPath格式
        cursor = db.execute("""
            SELECT DISTINCT Bookmark.StartContainerPath
            FROM Bookmark 
            WHERE Bookmark.VolumeID = ? AND Bookmark.StartContainerPath IS NOT NULL
        """, (book_id,))
        
        container_paths = cursor.fetchall()
        print(f"StartContainerPath 格式範例：")
        for path in container_paths[:5]:
            print(f"  {path[0]}")
        print()
        
        # 分析ChapterIDBookmarked格式
        cursor = db.execute("""
            SELECT DISTINCT content.ChapterIDBookmarked
            FROM content 
            WHERE content.ContentID = ? AND content.ChapterIDBookmarked IS NOT NULL
        """, (book_id,))
        
        chapter_ids = cursor.fetchall()
        print(f"ChapterIDBookmarked 格式範例：")
        for chapter_id in chapter_ids[:5]:
            print(f"  {chapter_id[0]}")
        print()
        
    except Exception as e:
        print(f"❌ 錯誤：{e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    analyze_chapter_data() 