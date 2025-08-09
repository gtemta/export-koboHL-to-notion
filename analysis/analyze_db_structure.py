#!/usr/bin/env python3
"""
分析KoboReader.sqlite數據庫結構
"""
import sqlite3
import DBReader

def analyze_db_structure():
    """分析數據庫結構"""
    print("=== 分析 KoboReader.sqlite 數據庫結構 ===\n")
    
    db = DBReader.get_db_connection()
    cursor = db.cursor()
    
    try:
        # 1. 查看所有表格
        print("=== 數據庫中的所有表格 ===")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        
        for table in tables:
            print(f"- {table[0]}")
        print()
        
        # 2. 分析主要表格結構
        important_tables = ['content', 'Bookmark', 'Shelf', 'Event']
        
        for table_name in important_tables:
            if any(table_name.lower() in t[0].lower() for t in tables):
                print(f"=== {table_name} 表格結構 ===")
                cursor.execute(f"PRAGMA table_info({table_name});")
                columns = cursor.fetchall()
                
                for col in columns:
                    col_id, name, data_type, not_null, default, pk = col
                    print(f"  {name:25} {data_type:15} {'NOT NULL' if not_null else '':8} {'PK' if pk else '':3}")
                print()
        
        # 3. 分析content表的樣本數據
        print("=== content 表格樣本數據 ===")
        cursor.execute("""
            SELECT ContentID, Title, Attribution, ChapterIDBookmarked, 
                   CurrentChapterEstimate, CurrentChapterProgress, ___PercentRead
            FROM content 
            WHERE ContentID LIKE '%AI世界的底層邏輯%'
            LIMIT 5;
        """)
        
        content_samples = cursor.fetchall()
        if content_samples:
            print("ContentID | Title | Author | ChapterID | ChapterEst | ChapterProg | PercentRead")
            print("-" * 100)
            for row in content_samples:
                print(f"{str(row[0])[:20]:20} | {str(row[1])[:15]:15} | {str(row[2])[:10]:10} | {str(row[3])[:15]:15} | {str(row[4]):10} | {str(row[5]):11} | {str(row[6]):11}")
        print()
        
        # 4. 分析Bookmark表的樣本數據
        print("=== Bookmark 表格樣本數據 ===")
        cursor.execute("""
            SELECT VolumeID, ContentID, ChapterProgress, StartContainerPath, 
                   EndContainerPath, Text
            FROM Bookmark 
            WHERE VolumeID LIKE '%AI世界的底層邏輯%'
            ORDER BY ChapterProgress
            LIMIT 10;
        """)
        
        bookmark_samples = cursor.fetchall()
        if bookmark_samples:
            print("VolumeID (部分) | ContentID (部分) | ChapterProgress | Container Path | Text (前30字)")
            print("-" * 120)
            for row in bookmark_samples:
                volume_id = str(row[0])[-20:] if row[0] else "N/A"
                content_id = str(row[1])[-30:] if row[1] else "N/A" 
                progress = f"{row[2]:.3f}" if row[2] else "N/A"
                path = str(row[3])[-30:] if row[3] else "N/A"
                text = str(row[5])[:30] + "..." if row[5] and len(str(row[5])) > 30 else str(row[5])
                print(f"{volume_id:20} | {content_id:30} | {progress:15} | {path:30} | {text}")
        print()
        
        # 5. 查找是否有章節相關的表格
        print("=== 查找章節相關表格 ===")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%chapter%' OR name LIKE '%Chapter%' OR name LIKE '%section%' OR name LIKE '%Section%');")
        chapter_tables = cursor.fetchall()
        
        if chapter_tables:
            for table in chapter_tables:
                print(f"發現章節相關表格: {table[0]}")
                cursor.execute(f"PRAGMA table_info({table[0]});")
                columns = cursor.fetchall()
                for col in columns:
                    print(f"  - {col[1]} ({col[2]})")
        else:
            print("沒有發現專門的章節表格")
        print()
        
        # 6. 分析content表中所有ContentID的模式
        print("=== 分析 ContentID 模式 ===")
        cursor.execute("""
            SELECT DISTINCT ContentID
            FROM content 
            WHERE ContentID LIKE '%AI世界的底層邏輯%'
            ORDER BY ContentID;
        """)
        
        content_ids = cursor.fetchall()
        if content_ids:
            print("發現的 ContentID 模式:")
            for cid in content_ids[:10]:  # 顯示前10個
                print(f"  {cid[0]}")
        print()
        
    finally:
        db.close()

def analyze_chapter_progress_relationship():
    """深入分析章節與進度的關係"""
    print("=== 分析章節與進度關係 ===\n")
    
    # 獲取第一本書的數據進行詳細分析
    bookList = DBReader.getBookInfoFromDB()
    if not bookList:
        print("沒有找到書籍數據")
        return
        
    test_book = bookList[0]
    print(f"分析書籍: {test_book.get_title()}")
    
    db = DBReader.get_db_connection()
    cursor = db.cursor()
    
    try:
        # 獲取這本書的所有高亮，並分析進度分佈
        cursor.execute("""
            SELECT Bookmark.ContentID, Bookmark.ChapterProgress, 
                   Bookmark.StartContainerPath, Bookmark.EndContainerPath,
                   Bookmark.Text
            FROM Bookmark 
            WHERE Bookmark.VolumeID = ?
            ORDER BY Bookmark.ChapterProgress;
        """, (test_book.get_id(),))
        
        all_highlights = cursor.fetchall()
        
        print(f"總高亮數: {len(all_highlights)}")
        print()
        
        # 分析進度區間與ContentID的關係
        print("=== 進度區間與ContentID分析 ===")
        progress_ranges = {}
        
        for highlight in all_highlights:
            content_id, progress, start_path, end_path, text = highlight
            
            # 提取章節名稱
            chapter_name = DBReader.extract_chapter_name(content_id) if content_id else "未知"
            
            if chapter_name not in progress_ranges:
                progress_ranges[chapter_name] = []
            progress_ranges[chapter_name].append(progress)
        
        # 計算每個章節的進度範圍
        print("章節名稱                          | 進度範圍              | 高亮數 | 平均進度")
        print("-" * 80)
        
        for chapter, progresses in progress_ranges.items():
            valid_progresses = [p for p in progresses if p is not None and p > 0]
            if valid_progresses:
                min_prog = min(valid_progresses)
                max_prog = max(valid_progresses)
                avg_prog = sum(valid_progresses) / len(valid_progresses)
                print(f"{chapter[:30]:30} | {min_prog:.3f} - {max_prog:.3f} | {len(progresses):6d} | {avg_prog:.3f}")
        
    finally:
        db.close()

if __name__ == "__main__":
    analyze_db_structure()
    print("\n" + "="*60 + "\n")
    analyze_chapter_progress_relationship()