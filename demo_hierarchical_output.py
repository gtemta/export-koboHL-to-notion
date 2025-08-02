#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import DBReader

def demo_hierarchical_output():
    """演示階層式章節排列輸出格式"""
    print("=== 階層式章節排列輸出格式演示 ===\n")
    
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
    
    # 按章节进度排序（階層式排列）
    sorted_chapters = sorted(chapter_groups.items(), key=lambda x: 
        max([h['chapter_progress'] for h in x[1]]) if x[1] else 0)
    
    # 模拟Notion输出格式
    print("# Highlights\n")
    
    for chapter_name, highlights in sorted_chapters:
        # 计算该章节的平均进度
        avg_progress = sum([h['chapter_progress'] for h in highlights]) / len(highlights) if highlights else 0
        
        # 章节标题（按进度階層式排列）
        print(f"## 📖 {chapter_name} (進度: {avg_progress:.1%})")
        
        # 该章节的高亮内容（單純的文本區塊）
        for highlight_info in highlights:
            text = highlight_info['text']
            
            if text:
                print(f"{text}")
        
        # 章节分隔符
        print("\n---\n")
    
    print("\n=== 階層式排列統計 ===")
    print(f"总章节数: {len(chapter_groups)}")
    print(f"总高亮数: {len(highlights_with_chapter)}")
    
    # 显示按进度排序的章节
    print("\n按進度排序的章節:")
    for i, (chapter_name, highlights) in enumerate(sorted_chapters, 1):
        avg_progress = sum([h['chapter_progress'] for h in highlights]) / len(highlights) if highlights else 0
        print(f"  {i}. 📖 {chapter_name}: {len(highlights)} 个高亮 (平均進度: {avg_progress:.1%})")

def show_progress_hierarchy():
    """显示进度階層分布"""
    print("\n=== 進度階層分布 ===")
    
    books = DBReader.getBookInfoFromDB()
    if not books:
        return
    
    book = books[0]
    highlights_with_chapter = DBReader.getHLWithChapterFromDB(book.get_id())
    
    # 按章节分组
    chapter_groups = {}
    for highlight_info in highlights_with_chapter:
        chapter_name = highlight_info['chapter_name']
        if chapter_name not in chapter_groups:
            chapter_groups[chapter_name] = []
        chapter_groups[chapter_name].append(highlight_info)
    
    # 按进度排序
    sorted_chapters = sorted(chapter_groups.items(), key=lambda x: 
        max([h['chapter_progress'] for h in x[1]]) if x[1] else 0)
    
    print("章節進度階層:")
    for i, (chapter_name, highlights) in enumerate(sorted_chapters, 1):
        max_progress = max([h['chapter_progress'] for h in highlights]) if highlights else 0
        avg_progress = sum([h['chapter_progress'] for h in highlights]) / len(highlights) if highlights else 0
        print(f"  {i}. {chapter_name}")
        print(f"     最高進度: {max_progress:.1%}")
        print(f"     平均進度: {avg_progress:.1%}")
        print(f"     高亮數量: {len(highlights)}")
        print()

def compare_output_formats():
    """比較不同輸出格式"""
    print("\n=== 輸出格式比較 ===")
    
    books = DBReader.getBookInfoFromDB()
    if not books:
        return
    
    book = books[0]
    highlights_with_chapter = DBReader.getHLWithChapterFromDB(book.get_id())
    
    # 按章节分组
    chapter_groups = {}
    for highlight_info in highlights_with_chapter:
        chapter_name = highlight_info['chapter_name']
        if chapter_name not in chapter_groups:
            chapter_groups[chapter_name] = []
        chapter_groups[chapter_name].append(highlight_info)
    
    # 原始格式（按章节名排序）
    print("原始格式（按章節名排序）:")
    for chapter_name, highlights in sorted(chapter_groups.items()):
        print(f"  📖 {chapter_name}")
    
    print("\n階層式格式（按進度排序）:")
    sorted_chapters = sorted(chapter_groups.items(), key=lambda x: 
        max([h['chapter_progress'] for h in x[1]]) if x[1] else 0)
    for chapter_name, highlights in sorted_chapters:
        avg_progress = sum([h['chapter_progress'] for h in highlights]) / len(highlights) if highlights else 0
        print(f"  📖 {chapter_name} (進度: {avg_progress:.1%})")

if __name__ == "__main__":
    demo_hierarchical_output()
    show_progress_hierarchy()
    compare_output_formats() 