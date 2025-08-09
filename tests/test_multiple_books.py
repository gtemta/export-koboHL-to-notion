#!/usr/bin/env python3
"""
測試多本書籍的章節劃分效果
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import DBReader

def test_multiple_books():
    """測試多本書籍的章節劃分"""
    print("=== 測試多本書籍的章節劃分效果 ===\n")
    
    # 獲取所有書籍
    bookList = DBReader.getBookInfoFromDB()
    
    if not bookList:
        print("沒有找到任何書籍資料")
        return
    
    print(f"總共找到 {len(bookList)} 本書籍")
    
    # 測試前5本書
    test_books = bookList[:5]
    
    for i, book in enumerate(test_books, 1):
        print(f"\n{'='*60}")
        print(f"測試書籍 {i}/{len(test_books)}: {book.get_title()}")
        print(f"作者: {book.get_author()}")
        print(f"{'='*60}")
        
        # 獲取高亮資料
        highlights_with_chapter = DBReader.getHLWithChapterFromDB(book.get_id())
        
        if not highlights_with_chapter:
            print("❌ 這本書沒有高亮資料，跳過")
            continue
        
        print(f"原始高亮數量: {len(highlights_with_chapter)}")
        
        # 顯示原始章節分佈（基於ContentID）
        original_chapters = {}
        for highlight in highlights_with_chapter:
            chapter_name = highlight.get('chapter_name', 'N/A')
            if chapter_name not in original_chapters:
                original_chapters[chapter_name] = []
            original_chapters[chapter_name].append(highlight.get('chapter_progress', 0))
        
        print(f"\n原始章節數（基於ContentID）: {len(original_chapters)}")
        
        # 使用新的智能排序
        try:
            sorted_highlights = DBReader.smart_sort_highlights_by_chapter(highlights_with_chapter)
            
            # 統計新的章節分佈
            new_chapters = {}
            for highlight in sorted_highlights:
                chapter_name = highlight.get('chapter_name', 'N/A')
                if chapter_name not in new_chapters:
                    new_chapters[chapter_name] = 0
                new_chapters[chapter_name] += 1
            
            print(f"✅ 重組後章節數: {len(new_chapters)}")
            
            # 驗證章節順序
            is_sorted = True
            prev_avg = -1
            
            for chapter_name in new_chapters.keys():
                # 找到這個章節的高亮
                chapter_highlights = [h for h in sorted_highlights if h.get('chapter_name') == chapter_name]
                if chapter_highlights:
                    avg_progress = chapter_highlights[0].get('chapter_avg_progress', 0)
                    if avg_progress > 0 and avg_progress < prev_avg:
                        is_sorted = False
                        break
                    if avg_progress > 0:
                        prev_avg = avg_progress
            
            if is_sorted:
                print("✅ 章節排序驗證通過")
            else:
                print("❌ 章節排序驗證失敗")
                
        except Exception as e:
            print(f"❌ 處理出錯: {str(e)}")
    
    print(f"\n{'='*60}")
    print("多本書籍測試完成")

if __name__ == "__main__":
    test_multiple_books()