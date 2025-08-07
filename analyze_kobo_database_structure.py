#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深入分析Kobo數據庫結構，尋找章節名稱信息
參考 kobo-up 項目的實現方式
"""

import sqlite3
import os

def analyze_kobo_database_structure():
    """深入分析Kobo數據庫結構"""
    
    if not os.path.exists('KoboReader.sqlite'):
        print("❌ 錯誤：找不到 KoboReader.sqlite 文件")
        return
    
    db = sqlite3.connect("KoboReader.sqlite")
    
    print("🔍 深入分析Kobo數據庫結構")
    print("=" * 50)
    
    try:
        # 獲取所有表名
        cursor = db.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print("📊 數據庫中的表：")
        for table in tables:
            print(f"  - {table[0]}")
        print()
        
        # 分析content表的結構
        print("📋 content表結構：")
        cursor = db.execute("PRAGMA table_info(content);")
        columns = cursor.fetchall()
        for col in columns:
            print(f"  - {col[1]} ({col[2]})")
        print()
        
        # 分析Bookmark表的結構
        print("📋 Bookmark表結構：")
        cursor = db.execute("PRAGMA table_info(Bookmark);")
        columns = cursor.fetchall()
        for col in columns:
            print(f"  - {col[1]} ({col[2]})")
        print()
        
        # 檢查是否有其他相關表
        print("🔍 檢查其他相關表：")
        for table in tables:
            table_name = table[0]
            if 'chapter' in table_name.lower() or 'section' in table_name.lower():
                print(f"  📖 發現相關表：{table_name}")
                cursor = db.execute(f"PRAGMA table_info({table_name});")
                columns = cursor.fetchall()
                for col in columns:
                    print(f"    - {col[1]} ({col[2]})")
                print()
        
        # 分析第一本書的詳細信息
        print("📖 分析第一本書的詳細信息：")
        cursor = db.execute("""
            SELECT DISTINCT content.ContentId, content.Title, content.Attribution
            FROM Bookmark 
            INNER JOIN content ON Bookmark.VolumeID = content.ContentID 
            LIMIT 1
        """)
        
        book_info = cursor.fetchone()
        if book_info:
            book_id, book_title, author = book_info
            print(f"  書籍：{book_title}")
            print(f"  作者：{author}")
            print(f"  ID：{book_id}")
            print()
            
            # 檢查content表中的所有字段
            cursor = db.execute("""
                SELECT * FROM content WHERE ContentID = ?
            """, (book_id,))
            
            content_row = cursor.fetchone()
            if content_row:
                print("  📋 content表完整記錄：")
                cursor = db.execute("PRAGMA table_info(content);")
                columns = cursor.fetchall()
                column_names = [col[1] for col in columns]
                
                for i, value in enumerate(content_row):
                    if value is not None and str(value).strip():
                        print(f"    {column_names[i]}: {value}")
                print()
            
            # 檢查是否有章節相關的字段
            print("  🔍 檢查章節相關字段：")
            chapter_related_fields = []
            for col in columns:
                col_name = col[1].lower()
                if any(keyword in col_name for keyword in ['chapter', 'section', 'title', 'name']):
                    chapter_related_fields.append(col[1])
            
            if chapter_related_fields:
                print(f"    發現章節相關字段：{', '.join(chapter_related_fields)}")
                
                # 查詢這些字段的值
                for field in chapter_related_fields:
                    cursor = db.execute(f"""
                        SELECT DISTINCT {field} FROM content 
                        WHERE ContentID = ? AND {field} IS NOT NULL
                    """, (book_id,))
                    values = cursor.fetchall()
                    if values:
                        print(f"    {field}: {[v[0] for v in values]}")
            else:
                print("    未發現明顯的章節相關字段")
            print()
            
            # 檢查Bookmark表中的章節信息
            print("  📋 Bookmark表章節信息：")
            cursor = db.execute("""
                SELECT DISTINCT Bookmark.ContentID, Bookmark.StartContainerPath, Bookmark.EndContainerPath,
                       content.ChapterIDBookmarked
                FROM Bookmark 
                INNER JOIN content ON Bookmark.VolumeID = content.ContentID 
                WHERE Bookmark.VolumeID = ?
                LIMIT 5
            """, (book_id,))
            
            bookmark_rows = cursor.fetchall()
            for i, row in enumerate(bookmark_rows):
                content_id, start_path, end_path, chapter_id = row
                print(f"    記錄 {i+1}:")
                print(f"      ContentID: {content_id}")
                print(f"      StartContainerPath: {start_path}")
                print(f"      EndContainerPath: {end_path}")
                print(f"      ChapterIDBookmarked: {chapter_id}")
                print()
        
    except Exception as e:
        print(f"❌ 錯誤：{e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    analyze_kobo_database_structure() 