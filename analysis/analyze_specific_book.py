#!/usr/bin/env python3
"""
分析特定書籍的章節標題提取問題
"""
import DBReader

def analyze_specific_book(book_title_keyword):
    """分析特定書籍的章節標題提取問題"""
    print(f"=== 分析包含 '{book_title_keyword}' 的書籍 ===\n")
    
    # 獲取所有書籍
    bookList = DBReader.getBookInfoFromDB()
    
    target_book = None
    for book in bookList:
        if book_title_keyword in book.get_title():
            target_book = book
            break
    
    if not target_book:
        print(f"沒有找到包含 '{book_title_keyword}' 的書籍")
        return
    
    print(f"找到目標書籍: {target_book.get_title()}")
    print(f"作者: {target_book.get_author()}")
    print(f"書籍ID: {target_book.get_id()}")
    
    # 獲取高亮資料
    highlights_with_chapter = DBReader.getHLWithChapterFromDB(target_book.get_id())
    
    if not highlights_with_chapter:
        print("這本書沒有高亮資料")
        return
    
    print(f"\n總高亮數量: {len(highlights_with_chapter)}")
    
    # 分析每個高亮的章節標題提取結果
    print("\n=== 詳細分析每個高亮的章節標題提取 ===")
    
    real_titles_found = 0
    potential_titles = []
    
    for i, highlight in enumerate(highlights_with_chapter):
        text = highlight.get('text', '')
        content_id = highlight.get('content_id', '')
        chapter_progress = highlight.get('chapter_progress', 0)
        
        # 嘗試提取真實標題
        real_title = DBReader.extract_real_chapter_title(text, content_id)
        
        print(f"\n高亮 {i+1:2d}: 進度 {chapter_progress:.3f}")
        if text:
            print(f"  原文: {text[:80]}...")
        else:
            print(f"  原文: [空白內容]")
        print(f"  提取結果: {real_title if real_title else '無'}")
        
        if real_title:
            real_titles_found += 1
            potential_titles.append((chapter_progress, real_title))
        
        # 手動檢查是否可能是標題
        if not real_title and text:
            # 檢查是否有其他可能的標題模式
            is_potential = check_potential_title_patterns(text)
            if is_potential:
                print(f"  ⚠️ 可能的標題模式: {is_potential}")
    
    print(f"\n=== 分析總結 ===")
    print(f"找到的真實標題數量: {real_titles_found}")
    print(f"真實標題比例: {real_titles_found/len(highlights_with_chapter)*100:.1f}%")
    
    if potential_titles:
        print(f"\n發現的真實標題:")
        for progress, title in potential_titles:
            print(f"  進度 {progress:.3f}: {title}")
    
    # 運行智能排序來看結果
    print(f"\n{'='*60}")
    print("運行智能章節排序...")
    print(f"{'='*60}")
    
    try:
        sorted_highlights = DBReader.smart_sort_highlights_by_chapter(highlights_with_chapter)
        print(f"排序完成，總共 {len(sorted_highlights)} 個高亮")
    except Exception as e:
        print(f"排序時出錯: {e}")

def check_potential_title_patterns(text):
    """檢查文本是否包含可能的標題模式"""
    if not text or len(text) > 200:
        return None
    
    import re
    
    potential_patterns = []
    
    # 檢查各種可能的標題模式
    patterns_to_check = [
        # 英文標題模式
        (r'^[A-Z][a-z\s]+[A-Z][a-z\s]*$', "英文標題格式"),
        
        # 數字編號
        (r'^\d+[\.、]\s*\w+', "數字編號開頭"),
        
        # 括號內容
        (r'^\(.+\)', "括號標題"),
        
        # 問句形式
        (r'.+[？?]$', "問句標題"),
        
        # 短文本且無句號
        (r'^[^。！？\n]{5,40}$', "短文本無句號"),
        
        # 包含特定動詞
        (r'^(如何|怎樣|什麼|為什麼|學會|掌握|理解)', "動詞開頭"),
        
        # 思維相關關鍵詞
        (r'.*(思維|思考|方法|策略|技巧|能力).*', "思維相關詞彙"),
    ]
    
    for pattern, description in patterns_to_check:
        if re.search(pattern, text.strip()):
            potential_patterns.append(description)
    
    return ", ".join(potential_patterns) if potential_patterns else None

def analyze_chapter_title_extraction_rules():
    """分析當前的章節標題提取規則"""
    print(f"\n{'='*60}")
    print("分析當前章節標題提取規則...")
    print(f"{'='*60}")
    
    # 模擬測試各種標題格式
    test_titles = [
        "思維模式1：系統思考",
        "第一章：邏輯思維的力量", 
        "如何培養批判性思維？",
        "系統思考 vs 線性思考",
        "什麼是超級思維",
        "Chapter 1: Critical Thinking",
        "1. 基礎思維訓練",
        "（一）認知偏誤的影響",
        "思維的盲點與突破",
        "培養多元思維能力",
        "這是一個很長的句子，包含了很多內容，但可能不是章節標題。",
        "AI 可以取代重複性事務，也展現出強大的推理能力，但無法協調、決策、管理。"
    ]
    
    print("測試各種標題格式的提取結果:")
    for test_title in test_titles:
        result = DBReader.extract_real_chapter_title(test_title, "")
        status = "✓" if result else "✗"
        print(f"  {status} {test_title}")
        if result and result != test_title:
            print(f"    -> 提取結果: {result}")

if __name__ == "__main__":
    analyze_specific_book("超級思維")
    analyze_chapter_title_extraction_rules()