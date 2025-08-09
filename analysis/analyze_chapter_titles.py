#!/usr/bin/env python3
"""
深入分析 KoboReader.sqlite 中的章節標題信息
"""
import sqlite3
import DBReader
import re

def analyze_chapter_title_sources():
    """分析所有可能的章節標題來源"""
    print("=== 深入分析章節標題信息來源 ===\n")
    
    db = DBReader.get_db_connection()
    cursor = db.cursor()
    
    try:
        # 1. 檢查content表中所有可能包含章節信息的欄位
        print("=== 檢查 content 表的章節相關欄位 ===")
        cursor.execute("""
            SELECT ContentID, Title, ChapterIDBookmarked, 
                   CurrentChapterEstimate, CurrentChapterProgress,
                   BookTitle, Attribution
            FROM content 
            WHERE ContentID LIKE '%AI世界的底層邏輯%'
            LIMIT 10;
        """)
        
        content_results = cursor.fetchall()
        if content_results:
            for row in content_results:
                content_id, title, chapter_id, estimate, progress, book_title, author = row
                print(f"ContentID: {str(content_id)[-40:]}")
                print(f"Title: {title}")
                print(f"ChapterIDBookmarked: {chapter_id}")
                print(f"CurrentChapterEstimate: {estimate}")
                print(f"CurrentChapterProgress: {progress}")
                print(f"BookTitle: {book_title}")
                print("-" * 60)
        
        # 2. 分析Bookmark表中的路徑信息
        print("\n=== 分析 Bookmark 表的路徑信息 ===")
        cursor.execute("""
            SELECT DISTINCT StartContainerPath, EndContainerPath, ContentID
            FROM Bookmark 
            WHERE VolumeID LIKE '%AI世界的底層邏輯%'
            ORDER BY StartContainerPath
            LIMIT 20;
        """)
        
        bookmark_paths = cursor.fetchall()
        if bookmark_paths:
            print("StartContainerPath 樣本：")
            for start_path, end_path, content_id in bookmark_paths:
                print(f"Start: {start_path}")
                print(f"End: {end_path}")
                print(f"ContentID: {str(content_id)[-40:]}")
                print("-" * 40)
        
        # 3. 檢查是否有專門的章節或目錄表
        print("\n=== 查找可能的章節/目錄相關表格 ===")
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND (
                name LIKE '%chapter%' OR 
                name LIKE '%Chapter%' OR 
                name LIKE '%toc%' OR 
                name LIKE '%TOC%' OR
                name LIKE '%content%' OR
                name LIKE '%navigation%' OR
                name LIKE '%Nav%'
            );
        """)
        
        chapter_tables = cursor.fetchall()
        if chapter_tables:
            print("找到可能相關的表格:")
            for table in chapter_tables:
                table_name = table[0]
                print(f"\n--- {table_name} 表格結構 ---")
                cursor.execute(f"PRAGMA table_info({table_name});")
                columns = cursor.fetchall()
                for col in columns:
                    print(f"  {col[1]} ({col[2]})")
                
                # 查看樣本數據
                try:
                    cursor.execute(f"SELECT * FROM {table_name} LIMIT 5;")
                    samples = cursor.fetchall()
                    if samples:
                        print("  樣本數據:")
                        for sample in samples[:3]:
                            print(f"    {sample}")
                except:
                    print("  (無法讀取樣本數據)")
        else:
            print("沒有找到明顯的章節相關表格")
        
        # 4. 分析ContentID模式，看能否推斷章節結構
        print("\n=== 分析 ContentID 模式 ===")
        cursor.execute("""
            SELECT DISTINCT ContentID
            FROM content
            WHERE ContentID LIKE '%AI世界的底層邏輯%'
            ORDER BY ContentID;
        """)
        
        content_ids = cursor.fetchall()
        if content_ids:
            print("所有相關的 ContentID:")
            for cid in content_ids:
                print(f"  {cid[0]}")
                
                # 嘗試解析結構
                content_id = cid[0]
                if 'OEBPS' in content_id:
                    parts = content_id.split('!')
                    if len(parts) > 2:
                        print(f"    -> 結構: {' -> '.join(parts[-3:])}")
        
        # 5. 檢查是否有存儲HTML內容的表格
        print("\n=== 查找可能存儲HTML內容的表格 ===")
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND (
                name LIKE '%html%' OR 
                name LIKE '%text%' OR 
                name LIKE '%body%' OR
                name LIKE '%page%'
            );
        """)
        
        html_tables = cursor.fetchall()
        if html_tables:
            for table in html_tables:
                table_name = table[0]
                print(f"\n--- {table_name} 表格 ---")
                cursor.execute(f"PRAGMA table_info({table_name});")
                columns = cursor.fetchall()
                for col in columns:
                    print(f"  {col[1]} ({col[2]})")
        
    finally:
        db.close()

def analyze_epub_structure_from_paths():
    """從路徑信息分析EPUB結構"""
    print("\n" + "="*60)
    print("=== 從路徑分析 EPUB 結構 ===\n")
    
    db = DBReader.get_db_connection()
    cursor = db.cursor()
    
    try:
        # 獲取所有書籍的路徑信息
        cursor.execute("""
            SELECT DISTINCT b.StartContainerPath, b.ContentID, c.Title, c.Attribution
            FROM Bookmark b
            JOIN content c ON b.VolumeID = c.ContentID
            WHERE b.StartContainerPath IS NOT NULL
            ORDER BY c.Title, b.StartContainerPath
            LIMIT 50;
        """)
        
        results = cursor.fetchall()
        
        # 按書籍分組
        books = {}
        for start_path, content_id, title, author in results:
            if title not in books:
                books[title] = []
            books[title].append((start_path, content_id))
        
        for book_title, paths in list(books.items())[:3]:  # 分析前3本書
            print(f"書籍: {book_title[:50]}")
            print("章節路徑分析:")
            
            # 去重並排序
            unique_paths = list(set([path for path, _ in paths]))
            unique_paths.sort()
            
            for path in unique_paths[:10]:  # 顯示前10個路徑
                print(f"  {path}")
                
                # 嘗試解析路徑中的章節信息
                chapter_hints = extract_chapter_info_from_path(path)
                if chapter_hints:
                    print(f"    -> 可能的章節信息: {chapter_hints}")
            
            print("-" * 50)
    
    finally:
        db.close()

def extract_chapter_info_from_path(path):
    """從路徑中提取可能的章節信息"""
    if not path:
        return None
    
    hints = []
    
    # 模式1: 提取文件名
    if '/' in path:
        filename = path.split('/')[-1]
        if '.xhtml' in filename:
            chapter_name = filename.replace('.xhtml', '').replace('.html', '')
            hints.append(f"文件名: {chapter_name}")
    
    # 模式2: 查找數字模式
    number_patterns = [
        r'chapter(\d+)',
        r'Chapter(\d+)',
        r'section(\d+)',
        r'Section(\d+)',
        r'/(\d+)\.',
        r'第(\d+)章',
        r'ch(\d+)',
    ]
    
    for pattern in number_patterns:
        matches = re.findall(pattern, path, re.IGNORECASE)
        if matches:
            hints.append(f"章節編號: {matches[0]}")
    
    # 模式3: 查找特殊章節名稱
    special_names = ['prologue', 'epilogue', 'preface', 'introduction', 'conclusion', 'appendix']
    for name in special_names:
        if name in path.lower():
            hints.append(f"特殊章節: {name}")
    
    return hints if hints else None

def search_for_chapter_titles_in_db():
    """在數據庫中搜尋可能的章節標題"""
    print("\n" + "="*60)
    print("=== 搜尋數據庫中的章節標題 ===\n")
    
    db = DBReader.get_db_connection()
    cursor = db.cursor()
    
    try:
        # 搜尋所有表格中可能包含章節標題的欄位
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        
        for table in tables:
            print(f"分析表格: {table}")
            
            # 獲取表格結構
            cursor.execute(f"PRAGMA table_info({table});")
            columns = cursor.fetchall()
            
            # 查找可能包含文字內容的欄位
            text_columns = []
            for col in columns:
                col_name = col[1]
                col_type = col[2].upper()
                if 'TEXT' in col_type or 'VARCHAR' in col_type:
                    text_columns.append(col_name)
            
            # 在文字欄位中搜尋可能的章節標題
            for col_name in text_columns[:3]:  # 只檢查前3個文字欄位
                try:
                    cursor.execute(f"""
                        SELECT DISTINCT {col_name}
                        FROM {table} 
                        WHERE {col_name} IS NOT NULL 
                        AND LENGTH({col_name}) > 0 
                        AND LENGTH({col_name}) < 200
                        AND ({col_name} LIKE '%章%' 
                             OR {col_name} LIKE '%Chapter%'
                             OR {col_name} LIKE '%第%'
                             OR {col_name} LIKE '%：%')
                        LIMIT 10;
                    """)
                    
                    results = cursor.fetchall()
                    if results:
                        print(f"  在 {col_name} 欄位找到可能的章節標題:")
                        for result in results:
                            title = result[0]
                            if title and len(str(title)) < 100:
                                print(f"    {title}")
                
                except Exception as e:
                    # 跳過有問題的查詢
                    continue
            
            print()
    
    finally:
        db.close()

if __name__ == "__main__":
    analyze_chapter_title_sources()
    analyze_epub_structure_from_paths() 
    search_for_chapter_titles_in_db()