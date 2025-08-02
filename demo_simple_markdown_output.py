#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
演示簡潔的markdown語法輸出格式
"""

import DBReader
import os

def demo_simple_markdown_output():
    """演示簡潔的markdown語法輸出格式"""
    
    # 檢查數據庫文件是否存在
    if not os.path.exists('KoboReader.sqlite'):
        print("❌ 錯誤：找不到 KoboReader.sqlite 文件")
        print("請確保 KoboReader.sqlite 文件在當前目錄中")
        return
    
    print("📚 演示簡潔的markdown語法輸出格式")
    print("=" * 50)
    
    try:
        # 獲取書籍列表
        books = DBReader.getBookInfoFromDB()
        
        if not books:
            print("❌ 沒有找到任何書籍")
            return
        
        print(f"✅ 找到 {len(books)} 本書籍")
        print()
        
        # 選擇第一本書進行演示
        book = books[0]
        print(f"📖 演示書籍：{book.get_title()}")
        print(f"👤 作者：{book.get_author()}")
        print()
        
        # 獲取該書籍的帶章節信息的高亮內容
        highlights_with_chapter = DBReader.getHLWithChapterFromDB(book.get_id())
        
        if not highlights_with_chapter:
            print("❌ 沒有找到任何高亮內容")
            return
        
        print(f"✅ 成功獲取 {len(highlights_with_chapter)} 條高亮內容")
        print()
        
        # 按章節分組
        chapter_groups = {}
        for highlight_info in highlights_with_chapter:
            chapter_name = highlight_info['chapter_name']
            if chapter_name not in chapter_groups:
                chapter_groups[chapter_name] = []
            chapter_groups[chapter_name].append(highlight_info)
        
        # 按章節進度排序
        sorted_chapters = sorted(chapter_groups.items(), key=lambda x: 
            max([h['chapter_progress'] for h in x[1]]) if x[1] else 0)
        
        print("📖 簡潔的markdown語法輸出格式：")
        print()
        
        # 輸出簡潔的markdown格式
        for chapter_name, highlights in sorted_chapters:
            # 輸出章節標題（單層級標題，不顯示進度）
            print(f"# 📖 {chapter_name}")
            print()
            
            # 輸出該章節的所有高亮內容（列表格式）
            for highlight_info in highlights:
                text = highlight_info['text']
                if text is not None:
                    print(f"* {text}")
                    print()
            
            # 添加分隔符
            print("---")
            print()
        
        print("✅ 演示完成！")
        print()
        print("📝 格式說明：")
        print("- 章節標題使用單層級標題 (#)")
        print("- 畫線內容使用列表格式 (*)")
        print("- 按閱讀進度排序章節")
        print("- 簡潔的視覺層次")
        
    except Exception as e:
        print(f"❌ 錯誤：{e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    demo_simple_markdown_output() 