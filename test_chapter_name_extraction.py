#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import DBReader
import sqlite3

def test_chapter_name_extraction():
    """測試章節名稱提取功能"""
    print("=== 章節名稱提取功能測試 ===\n")
    
    # 測試不同的ContentID格式
    test_content_ids = [
        "8b28b082-a6cd-4d1c-9a5f-7e97f35699e3!OEBPS!Text/Section0007.xhtml",
        "8b28b082-a6cd-4d1c-9a5f-7e97f35699e3!OEBPS!Text/1-2.xhtml",
        "8b28b082-a6cd-4d1c-9a5f-7e97f35699e3!OEBPS!Text/5-21.xhtml",
        "9a724406-16c0-44e1-a2c6-bd2e75578aee!item!xhtml/p-001.xhtml",
        "9a724406-16c0-44e1-a2c6-bd2e75578aee!item!xhtml/p-cover.xhtml",
        "unknown_format.xhtml"
    ]
    
    print("ContentID格式測試:")
    for content_id in test_content_ids:
        chapter_name = DBReader.extract_chapter_name(content_id)
        print(f"  {content_id} → {chapter_name}")
    
    print("\n" + "="*50 + "\n")
    
    # 測試StartContainerPath格式
    test_container_paths = [
        "OEBPS/Text/Section0002.xhtml#kobo.1.1",
        "OEBPS/Text/chapter50.xhtml#kobo.1.1",
        "OEBPS/Text/Section0014.xhtml#kobo.55.1",
        "unknown_format"
    ]
    
    print("StartContainerPath格式測試:")
    for container_path in test_container_paths:
        chapter_name = DBReader.extract_chapter_name_from_container_path(container_path)
        print(f"  {container_path} → {chapter_name}")
    
    print("\n" + "="*50 + "\n")

def test_real_data_extraction():
    """測試真實數據的章節名稱提取"""
    print("=== 真實數據章節名稱提取測試 ===\n")
    
    # 獲取書籍列表
    books = DBReader.getBookInfoFromDB()
    if not books:
        print("沒有找到書籍")
        return
    
    # 選擇第一本書進行測試
    book = books[0]
    print(f"📚 測試書籍: {book.get_title()}")
    print(f"👤 作者: {book.get_author()}")
    print(f"📖 ISBN: {book.get_isbn()}")
    print("=" * 50)
    
    # 獲取帶章節信息的高亮內容
    highlights_with_chapter = DBReader.getHLWithChapterFromDB(book.get_id())
    
    # 統計章節名稱提取結果
    chapter_name_stats = {}
    extraction_methods = {}
    
    for highlight_info in highlights_with_chapter:
        chapter_name = highlight_info['chapter_name']
        content_id = highlight_info.get('content_id', '')
        start_container_path = highlight_info.get('start_container_path', '')
        chapter_id_bookmarked = highlight_info.get('chapter_id_bookmarked', '')
        
        # 統計章節名稱
        if chapter_name not in chapter_name_stats:
            chapter_name_stats[chapter_name] = 0
        chapter_name_stats[chapter_name] += 1
        
        # 分析提取方法
        if '!OEBPS!Text/' in content_id:
            method = "ContentID (OEBPS)"
        elif '!item!xhtml/' in content_id:
            method = "ContentID (item)"
        elif 'OEBPS/Text/' in start_container_path:
            method = "StartContainerPath"
        elif chapter_id_bookmarked:
            method = "ChapterIDBookmarked"
        else:
            method = "未知"
        
        if method not in extraction_methods:
            extraction_methods[method] = 0
        extraction_methods[method] += 1
    
    print("章節名稱統計:")
    for chapter_name, count in sorted(chapter_name_stats.items()):
        print(f"  📖 {chapter_name}: {count} 個高亮")
    
    print("\n提取方法統計:")
    for method, count in extraction_methods.items():
        print(f"  {method}: {count} 個")
    
    print(f"\n總計: {len(highlights_with_chapter)} 個高亮")
    print(f"唯一章節數: {len(chapter_name_stats)}")

def test_database_queries():
    """測試數據庫查詢"""
    print("\n=== 數據庫查詢測試 ===")
    
    db = sqlite3.connect("KoboReader.sqlite")
    
    # 測試改進的查詢
    query = """
    SELECT Bookmark.Text, Bookmark.ContentID, Bookmark.ChapterProgress, 
           Bookmark.StartContainerPath, Bookmark.EndContainerPath,
           content.ChapterIDBookmarked, content.CurrentChapterEstimate, content.CurrentChapterProgress
    FROM Bookmark 
    INNER JOIN content ON Bookmark.VolumeID = content.ContentID 
    WHERE content.ContentID = ? 
    ORDER BY Bookmark.ChapterProgress
    LIMIT 5
    """
    
    # 獲取第一本書的ID
    books = DBReader.getBookInfoFromDB()
    if books:
        book_id = books[0].get_id()
        print(f"測試書籍ID: {book_id}")
        
        cursor = db.execute(query, (book_id,))
        results = cursor.fetchall()
        
        print(f"查詢結果:")
        for i, row in enumerate(results):
            text, content_id, progress, start_path, end_path, chapter_id, estimate, chapter_progress = row
            print(f"  {i+1}. ContentID: {content_id}")
            print(f"     章節進度: {progress:.1%}")
            print(f"     開始路徑: {start_path}")
            print(f"     章節ID: {chapter_id}")
            print(f"     內容: {text[:50]}...")
            print()

if __name__ == "__main__":
    test_chapter_name_extraction()
    test_real_data_extraction()
    test_database_queries() 