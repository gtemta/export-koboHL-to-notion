#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import DBReader
import sqlite3

def analyze_chapter_extraction():
    """分析章節名稱提取的準確性"""
    print("=== 章節名稱提取分析 ===\n")
    
    # 獲取書籍列表
    books = DBReader.getBookInfoFromDB()
    if not books:
        print("沒有找到書籍")
        return
    
    # 選擇第一本書進行分析
    book = books[0]
    print(f"📚 分析書籍: {book.get_title()}")
    print(f"👤 作者: {book.get_author()}")
    print(f"📖 ISBN: {book.get_isbn()}")
    print("=" * 50)
    
    # 獲取帶章節信息的高亮內容
    highlights_with_chapter = DBReader.getHLWithChapterFromDB(book.get_id())
    
    # 分析每個高亮的章節信息
    print("章節信息詳細分析:")
    print("-" * 80)
    
    for i, highlight_info in enumerate(highlights_with_chapter[:10]):  # 只分析前10個
        text = highlight_info['text'][:50] + "..." if len(highlight_info['text']) > 50 else highlight_info['text']
        content_id = highlight_info.get('content_id', '')
        start_container_path = highlight_info.get('start_container_path', '')
        chapter_id_bookmarked = highlight_info.get('chapter_id_bookmarked', '')
        chapter_name = highlight_info['chapter_name']
        progress = highlight_info['chapter_progress']
        
        print(f"\n{i+1}. 高亮內容: {text}")
        print(f"   最終章節名稱: {chapter_name}")
        print(f"   章節進度: {progress:.1%}")
        print(f"   ContentID: {content_id}")
        print(f"   StartContainerPath: {start_container_path}")
        print(f"   ChapterIDBookmarked: {chapter_id_bookmarked}")
        
        # 分析提取方法
        if '!OEBPS!Text/' in content_id:
            method = "ContentID (OEBPS)"
        elif '!item!xhtml/' in content_id:
            method = "ContentID (item)"
        elif 'OEBPS/Text/' in start_container_path:
            method = "StartContainerPath"
        elif chapter_id_bookmarked and not chapter_id_bookmarked.startswith('OEBPS/Text/'):
            method = "ChapterIDBookmarked"
        else:
            method = "未知"
        
        print(f"   提取方法: {method}")
    
    print("\n" + "="*50)
    
    # 統計分析
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
        elif chapter_id_bookmarked and not chapter_id_bookmarked.startswith('OEBPS/Text/'):
            method = "ChapterIDBookmarked"
        else:
            method = "未知"
        
        if method not in extraction_methods:
            extraction_methods[method] = 0
        extraction_methods[method] += 1
    
    print("統計結果:")
    print(f"總高亮數: {len(highlights_with_chapter)}")
    print(f"唯一章節數: {len(chapter_name_stats)}")
    
    print("\n章節名稱分布:")
    for chapter_name, count in sorted(chapter_name_stats.items()):
        print(f"  📖 {chapter_name}: {count} 個高亮")
    
    print("\n提取方法分布:")
    for method, count in extraction_methods.items():
        print(f"  {method}: {count} 個")

def test_different_extraction_methods():
    """測試不同的提取方法"""
    print("\n=== 不同提取方法測試 ===")
    
    # 測試數據
    test_cases = [
        {
            'content_id': '8b28b082-a6cd-4d1c-9a5f-7e97f35699e3!OEBPS!Text/Section0007.xhtml',
            'start_container_path': 'span#kobo.19.1',
            'chapter_id_bookmarked': 'OEBPS/Text/Section0039.xhtml#kobo.16.1'
        },
        {
            'content_id': '9a724406-16c0-44e1-a2c6-bd2e75578aee!item!xhtml/p-001.xhtml',
            'start_container_path': 'span#kobo.1.1',
            'chapter_id_bookmarked': 'OEBPS/Text/Section0039.xhtml#kobo.16.1'
        },
        {
            'content_id': 'unknown_format.xhtml',
            'start_container_path': 'OEBPS/Text/Section0002.xhtml#kobo.1.1',
            'chapter_id_bookmarked': 'OEBPS/Text/Section0039.xhtml#kobo.16.1'
        }
    ]
    
    for i, case in enumerate(test_cases, 1):
        print(f"\n測試案例 {i}:")
        print(f"  ContentID: {case['content_id']}")
        print(f"  StartContainerPath: {case['start_container_path']}")
        print(f"  ChapterIDBookmarked: {case['chapter_id_bookmarked']}")
        
        # 測試不同的提取方法
        chapter_name1 = DBReader.extract_chapter_name(case['content_id'])
        chapter_name2 = DBReader.extract_chapter_name_from_container_path(case['start_container_path'])
        chapter_name3 = DBReader.extract_chapter_name(case['chapter_id_bookmarked'])
        
        print(f"  方法1 (ContentID): {chapter_name1}")
        print(f"  方法2 (StartContainerPath): {chapter_name2}")
        print(f"  方法3 (ChapterIDBookmarked): {chapter_name3}")
        
        # 確定最終使用的章節名稱
        final_chapter_name = chapter_name1
        if final_chapter_name == "未知章节" and chapter_name2:
            final_chapter_name = chapter_name2
        if final_chapter_name == "未知章节" and chapter_name3 != "未知章节" and not chapter_name3.startswith('OEBPS/Text/'):
            final_chapter_name = chapter_name3
        
        print(f"  最終章節名稱: {final_chapter_name}")

if __name__ == "__main__":
    analyze_chapter_extraction()
    test_different_extraction_methods() 