#!/usr/bin/env python3
"""
增強的書籍總結工具
支援 Gemma 本地模型總結 + OpenAI 審核
依據環境變數自動選擇服務模式，完全可選的 LLM 功能
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from typing import Dict, List
import DBReader

# 添加 src 路徑以便導入
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

from infrastructure.llm.llm_environment_checker import LLMEnvironmentChecker, ServiceMode
from infrastructure.llm.book_summary_service_factory import BookSummaryServiceFactory


def setup_logger():
    """設置日誌配置"""
    logger = logging.getLogger('enhanced_book_summary')
    logger.setLevel(logging.INFO)
    
    # 避免重複添加 handler
    if logger.handlers:
        return logger
    
    # 創建日誌目錄
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # 文件日誌
    log_file = os.path.join(log_dir, 'enhanced_book_summary.log')
    file_handler = RotatingFileHandler(
        log_file, maxBytes=2*1024*1024, backupCount=3, encoding='utf-8'
    )
    file_handler.setLevel(logging.DEBUG)
    
    # 控制台日誌
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # 日誌格式
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger


def get_all_books_highlights() -> Dict[str, Dict]:
    """獲取所有書籍的劃線記錄"""
    try:
        book_list = DBReader.getBookInfoFromDB()
        books_data = {}
        
        for book in book_list:
            highlights = DBReader.getHLFromDB(book.get_id())
            if highlights:  # 只處理有劃線的書籍
                books_data[book.get_id()] = {
                    'title': book.get_title(),
                    'author': book.get_author(),
                    'highlights': highlights,
                    'book_obj': book
                }
        
        return books_data
    except Exception as e:
        logger.error(f"獲取書籍資料時發生錯誤: {e}")
        return {}


def save_summary_to_file(book_title: str, processing_result, output_dir: str = 'summaries'):
    """將總結保存到文件"""
    try:
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        
        # 清理文件名
        safe_title = "".join(c for c in book_title if c.isalnum() or c in (' ', '-', '_')).strip()
        safe_title = safe_title.replace(' ', '_')[:50]  # 限制長度
        
        filename = os.path.join(output_dir, f"{safe_title}_enhanced_summary.txt")
        
        with open(filename, 'w', encoding='utf-8') as f:
            # 寫入處理結果
            formatted_result = summary_factory.format_processing_result(processing_result)
            f.write(formatted_result)
        
        logger.info(f"總結已保存至: {filename}")
        return filename
        
    except Exception as e:
        logger.error(f"保存總結文件時發生錯誤: {e}")
        return None


def display_service_status():
    """顯示服務狀態"""
    env_checker = LLMEnvironmentChecker()
    env_checker.display_status_report()


def process_all_books():
    """處理所有書籍的總結"""
    logger.info("開始處理所有書籍的增強總結")
    
    # 獲取所有書籍資料
    books_data = get_all_books_highlights()
    
    if not books_data:
        logger.warning("未找到任何有劃線的書籍")
        return
    
    logger.info(f"找到 {len(books_data)} 本有劃線的書籍")
    
    # 統計結果
    success_count = 0
    failed_count = 0
    skipped_count = 0
    
    # 處理每本書
    for book_id, book_data in books_data.items():
        book_title = book_data['title']
        book_author = book_data['author']
        highlights = book_data['highlights']
        
        try:
            logger.info(f"\n{'='*60}")
            logger.info(f"處理書籍: {book_title}")
            logger.info(f"作者: {book_author}")
            logger.info(f"劃線數量: {len(highlights)} 條")
            logger.info(f"{'='*60}")
            
            # 使用服務工廠處理總結
            processing_result = summary_factory.process_book_summary(
                book_title, book_author, highlights
            )
            
            if processing_result.service_mode_used == ServiceMode.DISABLED:
                logger.info("LLM 服務未啟用，跳過此書籍")
                skipped_count += 1
                continue
            
            # 保存結果
            if processing_result.success:
                saved_file = save_summary_to_file(book_title, processing_result)
                if saved_file:
                    success_count += 1
                    logger.info(f"✅ {book_title} 處理成功")
                else:
                    failed_count += 1
                    logger.error(f"❌ {book_title} 保存失敗")
            else:
                failed_count += 1
                logger.error(f"❌ {book_title} 處理失敗: {processing_result.error_message}")
            
            # 顯示處理結果摘要
            print(f"\n{summary_factory.format_processing_result(processing_result)}\n")
            
        except Exception as e:
            failed_count += 1
            logger.error(f"處理書籍 {book_title} 時發生錯誤: {e}", exc_info=True)
    
    # 顯示最終統計
    logger.info(f"\n{'='*60}")
    logger.info("處理完成統計")
    logger.info(f"{'='*60}")
    logger.info(f"✅ 成功: {success_count} 本")
    logger.info(f"❌ 失敗: {failed_count} 本") 
    logger.info(f"⏭️  跳過: {skipped_count} 本")
    logger.info(f"📚 總計: {len(books_data)} 本")
    
    if success_count > 0:
        logger.info(f"\n📁 總結文件已保存在 'summaries' 資料夾中")


def interactive_mode():
    """互動模式"""
    while True:
        print("\n" + "="*50)
        print("📚 增強書籍總結工具")
        print("="*50)
        print("1. 檢查 LLM 服務狀態")
        print("2. 處理所有書籍總結")
        print("3. 處理指定書籍總結")
        print("4. 顯示環境設定指引")
        print("0. 退出")
        print("="*50)
        
        choice = input("請選擇操作 (0-4): ").strip()
        
        if choice == "0":
            print("👋 感謝使用，再見！")
            break
        elif choice == "1":
            display_service_status()
        elif choice == "2":
            process_all_books()
        elif choice == "3":
            process_single_book_interactive()
        elif choice == "4":
            display_setup_guide()
        else:
            print("❌ 無效選項，請重新選擇")


def process_single_book_interactive():
    """互動式處理單本書籍"""
    books_data = get_all_books_highlights()
    
    if not books_data:
        print("❌ 未找到任何有劃線的書籍")
        return
    
    print(f"\n找到 {len(books_data)} 本有劃線的書籍:")
    book_list = list(books_data.items())
    
    for i, (book_id, book_data) in enumerate(book_list, 1):
        print(f"{i:2d}. {book_data['title']} - {book_data['author']} ({len(book_data['highlights'])} 劃線)")
    
    try:
        choice = int(input(f"\n請選擇書籍 (1-{len(book_list)}): ")) - 1
        
        if 0 <= choice < len(book_list):
            book_id, book_data = book_list[choice]
            
            print(f"\n處理書籍: {book_data['title']}")
            
            processing_result = summary_factory.process_book_summary(
                book_data['title'], book_data['author'], book_data['highlights']
            )
            
            if processing_result.success:
                saved_file = save_summary_to_file(book_data['title'], processing_result)
                if saved_file:
                    print(f"✅ 總結已保存至: {saved_file}")
            
            print(f"\n{summary_factory.format_processing_result(processing_result)}")
            
        else:
            print("❌ 無效選項")
            
    except ValueError:
        print("❌ 請輸入有效數字")
    except Exception as e:
        print(f"❌ 處理過程發生錯誤: {e}")


def display_setup_guide():
    """顯示設定指引"""
    print("\n" + "="*60)
    print("🔧 LLM 服務環境設定指引")
    print("="*60)
    
    print("\n📋 支援的 LLM 服務:")
    print("• Gemma (本地模型，推薦)")
    print("• OpenAI (雲端 API)")
    print("• 雙模型協作 (Gemma + OpenAI，效果最佳)")
    
    print("\n🐳 Gemma 本地模型設定:")
    print("1. 安裝 Ollama: https://ollama.ai")
    print("2. 下載模型: ollama pull gemma:7b")
    print("3. 啟動服務: ollama serve")
    print("4. 設定環境變數:")
    print("   export GEMMA_API_URL=http://localhost:11434/api/generate")
    print("   export GEMMA_MODEL=gemma:7b")
    
    print("\n🌐 OpenAI API 設定:")
    print("1. 獲取 API Key: https://platform.openai.com/api-keys")
    print("2. 設定環境變數:")
    print("   export OPENAI_API_KEY=your_api_key")
    print("   export OPENAI_MODEL=gpt-4")
    
    print("\n⚙️ 其他設定 (可選):")
    print("   export SUMMARY_POINTS=16  # 總結重點數量")
    
    print("\n🚀 使用方式:")
    print("• 未設定環境變數: 跳過 LLM 功能，正常同步")
    print("• 僅設定 Gemma: 使用 Gemma 生成 16 重點總結")
    print("• 僅設定 OpenAI: 使用 OpenAI 生成總結")
    print("• 同時設定兩者: Gemma 初稿 + OpenAI 審核 (推薦)")
    
    print(f"\n{'='*60}")


def main():
    """主程式"""
    global logger, summary_factory
    
    # 初始化日誌
    logger = setup_logger()
    
    # 初始化服務工廠
    summary_factory = BookSummaryServiceFactory()
    
    logger.info("啟動增強書籍總結工具")
    
    # 檢查是否有命令列參數
    if len(sys.argv) > 1:
        if sys.argv[1] == "--status":
            display_service_status()
            return
        elif sys.argv[1] == "--process-all":
            process_all_books()
            return
        elif sys.argv[1] == "--setup-guide":
            display_setup_guide()
            return
        elif sys.argv[1] == "--help":
            print("用法:")
            print("  python enhanced_summarize_with_review.py                # 互動模式")
            print("  python enhanced_summarize_with_review.py --status       # 檢查服務狀態")
            print("  python enhanced_summarize_with_review.py --process-all  # 處理所有書籍")
            print("  python enhanced_summarize_with_review.py --setup-guide  # 顯示設定指引")
            return
    
    # 顯示歡迎訊息和狀態
    print("🚀 增強書籍總結工具啟動")
    print("支援 Gemma 本地模型 + OpenAI 審核")
    print("完全可選的 LLM 功能，依據環境變數自動調整\n")
    
    # 快速狀態檢查
    status = summary_factory.get_service_status()
    service_mode = status['service_mode']
    
    if service_mode == ServiceMode.DISABLED:
        print("⚠️  目前 LLM 服務未啟用")
        print("基礎書籍同步功能仍可正常使用")
        print("如需啟用總結功能，請設定相關環境變數")
        print("使用 --setup-guide 查看詳細設定說明\n")
    else:
        mode_desc = {
            ServiceMode.GEMMA_ONLY: "🟡 Gemma 本地模型",
            ServiceMode.OPENAI_ONLY: "🔵 OpenAI API",
            ServiceMode.FULL_SERVICE: "🟢 雙模型協作 (Gemma + OpenAI)"
        }
        print(f"✅ LLM 服務已啟用: {mode_desc.get(service_mode, '未知模式')}\n")
    
    # 進入互動模式
    try:
        interactive_mode()
    except KeyboardInterrupt:
        print("\n👋 程式已中斷，再見！")
    except Exception as e:
        logger.error(f"程式執行過程發生錯誤: {e}", exc_info=True)


if __name__ == "__main__":
    main()