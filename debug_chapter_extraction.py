#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
調試章節提取問題
"""

import sqlite3
import os

def debug_chapter_extraction():
    """調試章節提取問題"""
    
    if not os.path.exists('KoboReader.sqlite'):
        print("❌ 錯誤：找不到 KoboReader.sqlite 文件")
        return
    
    db = sqlite3.connect("KoboReader.sqlite")
    
    print("🔍 調試章節提取問題")
    print("=" * 50)
    
    try:
        # 獲取第一本書的ID
        cursor = db.execute("""
            SELECT DISTINCT content.ContentId, content.Title
            FROM Bookmark 
            INNER JOIN content ON Bookmark.VolumeID = content.ContentID 
            WHERE content.Title LIKE '%AI世界的底層邏輯與生存法則%'
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
        
        # 分析每個記錄的章節提取
        for i, row in enumerate(rows[:5]):  # 只分析前5個
            text, bookmark_content_id, chapter_progress, start_container_path, end_container_path, chapter_id_bookmarked, current_chapter_estimate, current_chapter_progress = row
            
            print(f"--- 記錄 {i+1} ---")
            print(f"文本: {text[:50]}...")
            print(f"Bookmark.ContentID: {bookmark_content_id}")
            print(f"Bookmark.StartContainerPath: {start_container_path}")
            print(f"content.ChapterIDBookmarked: {chapter_id_bookmarked}")
            print()
            
            # 測試不同的提取方法
            print("🔍 章節提取測試：")
            
            # 方法1：從ContentID提取
            if '!OEBPS!Text/' in bookmark_content_id:
                chapter_part = bookmark_content_id.split('!OEBPS!Text/')[1]
                chapter_name = chapter_part.replace('.xhtml', '')
                print(f"  方法1 (ContentID): {chapter_name}")
            else:
                print(f"  方法1 (ContentID): 不適用")
            
            # 方法2：從StartContainerPath提取
            if start_container_path and 'OEBPS/Text/' in start_container_path:
                text_part = start_container_path.split('OEBPS/Text/')[1]
                if '.xhtml' in text_part:
                    chapter_name = text_part.split('.xhtml')[0]
                    print(f"  方法2 (StartContainerPath): {chapter_name}")
                else:
                    print(f"  方法2 (StartContainerPath): 格式不匹配")
            else:
                print(f"  方法2 (StartContainerPath): 不適用")
            
            # 方法3：從ChapterIDBookmarked提取
            if chapter_id_bookmarked and 'OEBPS/Text/' in chapter_id_bookmarked:
                chapter_part = chapter_id_bookmarked.split('OEBPS/Text/')[1]
                if '.xhtml' in chapter_part:
                    chapter_name = chapter_part.split('.xhtml')[0]
                    print(f"  方法3 (ChapterIDBookmarked): {chapter_name}")
                else:
                    print(f"  方法3 (ChapterIDBookmarked): 格式不匹配")
            else:
                print(f"  方法3 (ChapterIDBookmarked): 不適用")
            
            print()
        
        # 分析所有ContentID的格式
        print("📊 ContentID格式分析：")
        cursor = db.execute("""
            SELECT DISTINCT Bookmark.ContentID
            FROM Bookmark 
            WHERE Bookmark.VolumeID = ?
        """, (book_id,))
        
        content_ids = cursor.fetchall()
        for content_id in content_ids:
            print(f"  {content_id[0]}")
            
            # 測試提取
            if '!OEBPS!Text/' in content_id[0]:
                chapter_part = content_id[0].split('!OEBPS!Text/')[1]
                chapter_name = chapter_part.replace('.xhtml', '')
                print(f"    -> 提取結果: {chapter_name}")
            else:
                print(f"    -> 無法提取")
        
        print()
        
    except Exception as e:
        print(f"❌ 錯誤：{e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    debug_chapter_extraction() 