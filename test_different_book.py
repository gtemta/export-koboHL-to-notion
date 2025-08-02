#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
測試不同書籍的章節提取
"""

import DBReader
import os

def test_different_book():
    """測試不同書籍的章節提取"""
    
    if not os.path.exists('KoboReader.sqlite'):
        print("❌ 錯誤：找不到 KoboReader.sqlite 文件")
        return
    
    print("📚 測試不同書籍的章節提取")
    print("=" * 50)
    
    try:
        # 獲取書籍列表
        books = DBReader.getBookInfoFromDB()
        
        if not books:
            print("❌ 沒有找到任何書籍")
            return
        
        print(f"✅ 找到 {len(books)} 本書籍")
        print()
        
        # 測試前兩本書
        for i, book in enumerate(books[:2]):
            print(f"📖 測試書籍 {i+1}：{book.get_title()}")
            print(f"👤 作者：{book.get_author()}")
            print()
            
            # 獲取該書籍的帶章節信息的高亮內容
            highlights_with_chapter = DBReader.getHLWithChapterFromDB(book.get_id())
            
            if not highlights_with_chapter:
                print("❌ 沒有找到任何高亮內容")
                print()
                continue
            
            print(f"✅ 成功獲取 {len(highlights_with_chapter)} 條高亮內容")
            print()
            
            # 按章節分組
            chapter_groups = {}
            for highlight_info in highlights_with_chapter:
                chapter_name = highlight_info['chapter_name']
                if chapter_name not in chapter_groups:
                    chapter_groups[chapter_name] = []
                chapter_groups[chapter_name].append(highlight_info)
            
            print("📖 章節提取結果：")
            for chapter_name, highlights in sorted(chapter_groups.items()):
                print(f"  📖 {chapter_name}: {len(highlights)} 條高亮")
            
            print()
            print("-" * 50)
            print()
        
    except Exception as e:
        print(f"❌ 錯誤：{e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_different_book() 