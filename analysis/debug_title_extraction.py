#!/usr/bin/env python3
"""
調試章節標題提取問題
"""
import DBReader
import re

def test_specific_texts():
    """測試特定的文本是否能被提取"""
    test_cases = [
        "「非受迫性失誤」（unforced error）的發生不是因為另一個選手產生失誤，而是選手自己判斷錯誤或產生失誤所造成。",
        "「反向思考」（inverse thinking）的概念可以幫你在面對挑戰時做出好決策。",
        "「從第一原理開始論證」（arguing from first principles）。這是錯誤少一點的實際起點",
        "「心智模式」（mental models），一旦熟悉它們之後，就可以很快地運用它們創造一個情境的心智圖像。",
        "「推力」（nudging）...",
        "「過早最佳化」（premature optimization），指你太快（過早）調整或完成程式碼",
        "「臨界質量」（critical mass）概念，臨界質量指的是，核材料的質量需要創造出一個臨界狀態",
    ]
    
    print("=== 測試特定文本的標題提取 ===\n")
    
    for i, text in enumerate(test_cases, 1):
        print(f"測試 {i}: {text[:60]}...")
        result = DBReader.extract_real_chapter_title(text, "")
        status = "✓" if result else "✗"
        print(f"  {status} 提取結果: {result if result else '無'}")
        
        # 手動測試正則表達式
        print(f"  調試正則表達式:")
        
        # 測試模式12
        pattern12 = r'^「.+?」\s*[（(].+?[）)]'
        match12 = re.search(pattern12, text.strip())
        print(f"    模式12匹配: {match12.group(0) if match12 else '無'}")
        
        # 測試模式11
        pattern11 = r'^「.+」'
        match11 = re.match(pattern11, text.strip())
        print(f"    模式11匹配: {match11.group(0) if match11 else '無'}")
        
        print()

def analyze_pattern_issues():
    """分析模式匹配的問題"""
    print("=== 分析正則表達式模式 ===\n")
    
    # 測試文本
    text = "「非受迫性失誤」（unforced error）的發生不是因為另一個選手產生失誤"
    
    print(f"測試文本: {text}")
    print(f"文本長度: {len(text)}")
    
    # 測試各種模式
    patterns = [
        (r'^「.+?」\s*[（(].+?[）)]', "帶英文翻譯的概念"),
        (r'^「.+」', "引號內的概念"),
        (r'^[「"](.{2,20})[」"]', "短引號概念"),
    ]
    
    for pattern, description in patterns:
        match = re.search(pattern, text)
        if match:
            print(f"  ✓ {description}: {match.group(0)}")
            if len(match.groups()) > 0:
                print(f"    群組1: {match.group(1)}")
        else:
            print(f"  ✗ {description}: 無匹配")
    
    print()
    
    # 手動提取引號+括號內容
    manual_pattern = r'^(「[^」]+」\s*[（(][^）)]+[）)])'
    manual_match = re.match(manual_pattern, text)
    if manual_match:
        print(f"  手動模式: {manual_match.group(1)}")
        print(f"  長度: {len(manual_match.group(1))}")

if __name__ == "__main__":
    test_specific_texts()
    analyze_pattern_issues()