#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import DBReader
import sqlite3

def test_chapter_extraction():
    """测试章节提取功能"""
    print("=== 测试章节提取功能 ===")
    
    # 获取书籍列表
    books = DBReader.getBookInfoFromDB()
    print(f"找到 {len(books)} 本书")
    
    if len(books) > 0:
        # 测试第一本书
        book = books[0]
        print(f"\n测试书籍: {book.get_title()}")
        print(f"书籍ID: {book.get_id()}")
        
        # 获取带章节信息的高亮内容
        highlights_with_chapter = DBReader.getHLWithChapterFromDB(book.get_id())
        print(f"找到 {len(highlights_with_chapter)} 个带章节信息的高亮")
        
        # 按章节分组显示
        chapter_groups = {}
        for highlight_info in highlights_with_chapter:
            chapter_name = highlight_info['chapter_name']
            if chapter_name not in chapter_groups:
                chapter_groups[chapter_name] = []
            chapter_groups[chapter_name].append(highlight_info)
        
        print(f"\n章节分组结果:")
        for chapter_name, highlights in sorted(chapter_groups.items()):
            print(f"\n📖 {chapter_name} ({len(highlights)} 个高亮)")
            for i, highlight_info in enumerate(highlights[:3]):  # 只显示前3个
                text = highlight_info['text'][:50] + "..." if len(highlight_info['text']) > 50 else highlight_info['text']
                progress = highlight_info['chapter_progress']
                print(f"  {i+1}. {text} (進度: {progress:.1%})")
            if len(highlights) > 3:
                print(f"  ... 还有 {len(highlights) - 3} 个高亮")

def test_database_queries():
    """测试数据库查询"""
    print("\n=== 测试数据库查询 ===")
    
    db = sqlite3.connect("KoboReader.sqlite")
    
    # 测试查询带章节信息的高亮
    query = """
    SELECT Bookmark.Text, Bookmark.ContentID, Bookmark.ChapterProgress
    FROM Bookmark 
    INNER JOIN content ON Bookmark.VolumeID = content.ContentID 
    WHERE content.ContentID = ? 
    ORDER BY Bookmark.ChapterProgress
    LIMIT 5
    """
    
    # 获取第一本书的ID
    books = DBReader.getBookInfoFromDB()
    if books:
        book_id = books[0].get_id()
        print(f"测试书籍ID: {book_id}")
        
        cursor = db.execute(query, (book_id,))
        results = cursor.fetchall()
        
        print(f"查询结果:")
        for i, row in enumerate(results):
            text, content_id, progress = row
            chapter_name = DBReader.extract_chapter_name(content_id)
            print(f"  {i+1}. 章节: {chapter_name}, 进度: {progress:.1%}")
            print(f"     内容: {text[:50]}...")
            print()

if __name__ == "__main__":
    test_chapter_extraction()
    test_database_queries() 