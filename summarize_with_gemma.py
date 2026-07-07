import logging
import os
from logging.handlers import RotatingFileHandler

import requests

from legacy import DBReader


# 设置日志配置
def setup_logger():
    logger = logging.getLogger('kobo_highlights_summary')
    logger.setLevel(logging.DEBUG)
    
    # 创建日志目录
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # 设置日志文件
    log_file = os.path.join(log_dir, 'kobo_highlights_summary.log')
    file_handler = RotatingFileHandler(log_file, maxBytes=1024*1024, backupCount=5, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    
    # 设置控制台输出
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    
    # 设置日志格式
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)
    
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

# 初始化日志记录器
logger = setup_logger()

class GemmaSummarizer:
    """使用 Gemma 模型进行文本总结"""
    
    def __init__(self):
        self.model_name = os.getenv('OLLAMA_MODEL', 'gemma4:e4b')
        self.api_url = os.getenv('OLLAMA_API_URL', 'http://localhost:11434/api/generate')
        
    def summarize(self, text: str) -> str:
        """
        使用 Gemma 模型总结文本
        
        Args:
            text (str): 要总结的文本
            
        Returns:
            str: 总结后的文本
        """
        try:
            prompt = f"""請將以下書籍的畫線內容整理成16個重點段落。每個段落的格式要求如下：

1. 首先用【】標註一個簡短的子標題，描述該段的核心概念
2. 然後在50個字以內補充說明這個概念的細節
3. 確保每個段落都清晰、簡潔，並保持原文的核心思想
4. 請使用繁體中文撰寫，並符合台灣的用語習慣

例如：
【核心概念】這裡是50個字以內的詳細說明，解釋這個概念的具體內容和重要性。

原文內容：
{text}

請按照上述格式輸出16個重點段落，每個段落都應該包含一個主要觀點或見解。確保每個段落的說明部分不超過50個字，並使用繁體中文撰寫。"""

            # 调用本地 API
            response = requests.post(
                self.api_url,
                json={
                    "model": self.model_name,
                    "prompt": prompt,
                    "stream": False
                }
            )
            
            if response.status_code == 200:
                result = response.json()
                return result["response"]
            else:
                logger.error(f"Gemma API 错误: {response.status_code} - {response.text}")
                return None
            
        except Exception as e:
            logger.error(f"Gemma 处理错误: {str(e)}")
            return None

def get_all_highlights():
    """获取所有书籍的高亮记录"""
    try:
        book_list = DBReader.getBookInfoFromDB()
        all_highlights = {}
        
        for book in book_list:
            highlights = DBReader.getHLFromDB(book.get_id())
            if highlights:
                all_highlights[book.get_title()] = {
                    'author': book.get_author(),
                    'highlights': highlights
                }
        
        return all_highlights
    except Exception as e:
        logger.error(f"Error getting highlights: {str(e)}")
        return {}

def save_summary_to_file(book_title: str, summary: str):
    """将总结保存到文件"""
    try:
        output_dir = 'summaries'
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
        filename = os.path.join(output_dir, f"{book_title.replace(':', '_')}_summary.txt")
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"书名：{book_title}\n\n")
            f.write(summary)
        logger.info(f"Summary saved to {filename}")
    except Exception as e:
        logger.error(f"Error saving summary: {str(e)}")

def main():
    logger.info("Starting highlights summary process")
    
    # 初始化 Gemma 总结器
    summarizer = GemmaSummarizer()
    
    # 获取所有高亮记录
    all_highlights = get_all_highlights()
    logger.info(f"Found highlights for {len(all_highlights)} books")
    
    # 处理每本书的高亮
    for book_title, book_data in all_highlights.items():
        try:
            logger.info(f"Processing book: {book_title}")
            
            # 准备高亮文本
            highlights_text = "\n".join(h for h in book_data['highlights'] if h and h.strip())
            
            # 使用 Gemma 总结
            summary = summarizer.summarize(highlights_text)
            
            if summary:
                # 保存总结到文件
                save_summary_to_file(book_title, summary)
                logger.info(f"Successfully summarized {book_title}")
            else:
                logger.error(f"Failed to summarize {book_title}")
                
        except Exception as e:
            logger.error(f"Error processing book {book_title}: {str(e)}")
    
    logger.info("Summary process completed")

if __name__ == "__main__":
    main() 