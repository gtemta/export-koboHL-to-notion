#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import DBReader

def demo_chapter_output():
    """演示章节输出格式"""
    print("=== 章节输出格式演示 ===\n")
    
    # 获取书籍列表
    books = DBReader.getBookInfoFromDB()
    if not books:
        print("没有找到书籍")
        return
    
    # 选择第一本书进行演示
    book = books[0]
    print(f"📚 书籍: {book.get_title()}")
    print(f"👤 作者: {book.get_author()}")
    print(f"📖 ISBN: {book.get_isbn()}")
    print("=" * 50)
    
    # 获取带章节信息的高亮内容
    highlights_with_chapter = DBReader.getHLWithChapterFromDB(book.get_id())
    
    # 按章节分组
    chapter_groups = {}
    for highlight_info in highlights_with_chapter:
        chapter_name = highlight_info['chapter_name']
        if chapter_name not in chapter_groups:
            chapter_groups[chapter_name] = []
        chapter_groups[chapter_name].append(highlight_info)
    
    # 模拟Notion输出格式
    print("# Highlights\n")
    
    for chapter_name, highlights in sorted(chapter_groups.items()):
        # 章节标题
        print(f"## 📖 {chapter_name}")
        
        # 该章节的高亮内容
        for highlight_info in highlights:
            text = highlight_info['text']
            progress = highlight_info['chapter_progress']
            
            if text:
                progress_text = f" (進度: {progress:.1%})" if progress else ""
                print(f"{text}{progress_text}")
        
        # 章节分隔符
        print("\n---\n")
    
    print("\n=== 统计信息 ===")
    print(f"总章节数: {len(chapter_groups)}")
    print(f"总高亮数: {len(highlights_with_chapter)}")
    
    # 显示每个章节的高亮数量
    print("\n各章节高亮数量:")
    for chapter_name, highlights in sorted(chapter_groups.items()):
        print(f"  📖 {chapter_name}: {len(highlights)} 个高亮")

def show_chapter_progress_distribution():
    """显示章节进度分布"""
    print("\n=== 章节进度分布 ===")
    
    books = DBReader.getBookInfoFromDB()
    if not books:
        return
    
    book = books[0]
    highlights_with_chapter = DBReader.getHLWithChapterFromDB(book.get_id())
    
    # 按进度范围分组
    progress_ranges = {
        "0-20%": 0,
        "20-40%": 0,
        "40-60%": 0,
        "60-80%": 0,
        "80-100%": 0
    }
    
    for highlight_info in highlights_with_chapter:
        progress = highlight_info['chapter_progress']
        if progress <= 0.2:
            progress_ranges["0-20%"] += 1
        elif progress <= 0.4:
            progress_ranges["20-40%"] += 1
        elif progress <= 0.6:
            progress_ranges["40-60%"] += 1
        elif progress <= 0.8:
            progress_ranges["60-80%"] += 1
        else:
            progress_ranges["80-100%"] += 1
    
    print("进度分布:")
    for range_name, count in progress_ranges.items():
        if count > 0:
            print(f"  {range_name}: {count} 个高亮")

if __name__ == "__main__":
    demo_chapter_output()
    show_chapter_progress_distribution() 