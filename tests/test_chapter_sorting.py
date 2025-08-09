#!/usr/bin/env python3
"""
測試章節排序功能的腳本
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import DBReader

def test_chapter_sorting():
    """測試章節排序功能"""
    print("=== 測試章節排序功能 ===\n")
    
    # 獲取書籍列表
    bookList = DBReader.getBookInfoFromDB()
    
    if not bookList:
        print("沒有找到任何書籍資料")
        return
    
    print(f"找到 {len(bookList)} 本書籍")
    
    # 選擇第一本書進行測試
    test_book = bookList[0]
    print(f"\n測試書籍: {test_book.get_title()}")
    print(f"作者: {test_book.get_author()}")
    print(f"書籍ID: {test_book.get_id()}")
    
    # 獲取原始高亮資料
    highlights_with_chapter = DBReader.getHLWithChapterFromDB(test_book.get_id())
    
    if not highlights_with_chapter:
        print("這本書沒有高亮資料")
        return
    
    print(f"\n原始高亮數量: {len(highlights_with_chapter)}")
    
    # 顯示前幾個原始高亮的章節信息
    print("\n=== 原始高亮章節資訊（前10個）===")
    for i, highlight in enumerate(highlights_with_chapter[:10]):
        chapter_name = highlight.get('chapter_name', 'N/A')
        chapter_progress = highlight.get('chapter_progress', 0)
        content_id = highlight.get('content_id', 'N/A')
        text_preview = highlight.get('text', '')[:50] + "..." if highlight.get('text') else ""
        
        print(f"{i+1:2d}. 章節: {chapter_name[:30]:30} | "
              f"進度: {chapter_progress:.3f} | "
              f"內容: {text_preview}")
    
    # 使用智能排序
    print(f"\n{'='*60}")
    print("開始智能排序...")
    print(f"{'='*60}")
    
    sorted_highlights = DBReader.smart_sort_highlights_by_chapter(highlights_with_chapter)
    
    print(f"\n排序後高亮數量: {len(sorted_highlights)}")
    
    # 顯示排序後的章節順序
    print("\n=== 排序後章節分佈 ===")
    current_chapter = ""
    chapter_count = 0
    
    for i, highlight in enumerate(sorted_highlights):
        chapter_name = highlight.get('chapter_name', 'N/A')
        chapter_progress = highlight.get('chapter_progress', 0)
        
        if chapter_name != current_chapter:
            if current_chapter:
                print()  # 章節間空行
            current_chapter = chapter_name
            chapter_count += 1
            print(f"第 {chapter_count} 章: {chapter_name}")
            print(f"  進度範圍: {chapter_progress:.3f} - ", end="")
            
            # 找到這個章節的最大進度
            max_progress = chapter_progress
            for j in range(i+1, len(sorted_highlights)):
                if sorted_highlights[j].get('chapter_name') == chapter_name:
                    max_progress = max(max_progress, sorted_highlights[j].get('chapter_progress', 0))
                else:
                    break
            print(f"{max_progress:.3f}")
    
    # 驗證排序是否正確
    print(f"\n{'='*60}")
    print("驗證排序結果...")
    print(f"{'='*60}")
    
    # 檢查章節是否按平均進度遞增
    chapter_avg_progress = {}
    chapter_groups = {}
    
    for highlight in sorted_highlights:
        chapter_name = highlight.get('chapter_name', 'N/A')
        chapter_progress = highlight.get('chapter_progress', 0)
        
        if chapter_name not in chapter_groups:
            chapter_groups[chapter_name] = []
        chapter_groups[chapter_name].append(chapter_progress)
    
    # 計算每個章節的平均進度
    for chapter, progresses in chapter_groups.items():
        valid_progresses = [p for p in progresses if p > 0]
        if valid_progresses:
            chapter_avg_progress[chapter] = sum(valid_progresses) / len(valid_progresses)
        else:
            chapter_avg_progress[chapter] = 0
    
    # 檢查章節順序是否遞增
    previous_avg = -1
    is_sorted_correctly = True
    current_chapter = ""
    
    print("章節平均進度檢查:")
    for highlight in sorted_highlights:
        chapter_name = highlight.get('chapter_name', 'N/A')
        if chapter_name != current_chapter:
            current_chapter = chapter_name
            avg_progress = chapter_avg_progress.get(chapter_name, 0)
            
            print(f"  {chapter_name[:40]:40} 平均進度: {avg_progress:.3f}")
            
            if avg_progress > 0 and avg_progress < previous_avg:
                print(f"    ⚠️  警告：進度倒退！前一章節: {previous_avg:.3f}")
                is_sorted_correctly = False
            
            if avg_progress > 0:
                previous_avg = avg_progress
    
    if is_sorted_correctly:
        print("\n✅ 排序驗證通過：章節按畫線位置正確排序")
    else:
        print("\n❌ 排序驗證失敗：章節順序可能不正確")

if __name__ == "__main__":
    test_chapter_sorting()