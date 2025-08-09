import os
import requests
import json
import logging
import re
from typing import Dict, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class BookSummaryPoint:
    """書籍重點摘要單元"""
    title: str          # 【】內的標題
    description: str    # 詳細說明
    char_count: int     # 字數統計
    is_valid: bool      # 格式是否有效


@dataclass
class BookSummary:
    """書籍總結"""
    book_title: str
    book_author: str
    highlight_count: int
    summary_points: List[BookSummaryPoint]
    generation_success: bool
    error_message: Optional[str] = None


class EnhancedGemmaService:
    """增強的 Gemma 總結服務"""
    
    def __init__(self):
        self.api_url = os.getenv('GEMMA_API_URL', 'http://localhost:11434/api/generate')
        self.model_name = os.getenv('GEMMA_MODEL', 'gemma:7b')
        self.target_points = int(os.getenv('SUMMARY_POINTS', '16'))
        self.max_chars_per_point = 50
        self.title_max_chars = 10
        
        # API 配置
        self.timeout = 180  # 3分鐘超時
        self.temperature = 0.3
        self.max_tokens = 2048
    
    def generate_book_summary(self, book_title: str, book_author: str, 
                            highlights: List[str]) -> BookSummary:
        """
        為書籍生成16個重點總結
        
        Args:
            book_title: 書籍標題
            book_author: 書籍作者
            highlights: 劃線內容列表
            
        Returns:
            BookSummary: 總結結果
        """
        if not highlights:
            return BookSummary(
                book_title=book_title,
                book_author=book_author,
                highlight_count=0,
                summary_points=[],
                generation_success=False,
                error_message="無劃線內容可供總結"
            )
        
        logger.info(f"開始生成書籍總結: {book_title} (作者: {book_author})")
        logger.info(f"劃線數量: {len(highlights)} 條")
        
        try:
            # 預處理劃線內容
            processed_highlights = self._preprocess_highlights(highlights)
            
            # 生成總結
            summary_text = self._generate_summary_with_gemma(
                book_title, book_author, processed_highlights
            )
            
            if not summary_text:
                return BookSummary(
                    book_title=book_title,
                    book_author=book_author,
                    highlight_count=len(highlights),
                    summary_points=[],
                    generation_success=False,
                    error_message="Gemma 模型未能生成有效回應"
                )
            
            # 解析總結結果
            summary_points = self._parse_summary_points(summary_text)
            
            # 驗證總結品質
            is_valid, validation_message = self._validate_summary_quality(summary_points)
            
            return BookSummary(
                book_title=book_title,
                book_author=book_author,
                highlight_count=len(highlights),
                summary_points=summary_points,
                generation_success=is_valid,
                error_message=validation_message if not is_valid else None
            )
            
        except Exception as e:
            logger.error(f"生成書籍總結時發生錯誤: {e}", exc_info=True)
            return BookSummary(
                book_title=book_title,
                book_author=book_author,
                highlight_count=len(highlights),
                summary_points=[],
                generation_success=False,
                error_message=f"處理過程發生錯誤: {str(e)}"
            )
    
    def _preprocess_highlights(self, highlights: List[str]) -> str:
        """預處理劃線內容"""
        # 去除過短的劃線（少於10字）
        filtered_highlights = [h.strip() for h in highlights if len(h.strip()) >= 10]
        
        # 去重複
        unique_highlights = []
        seen = set()
        for highlight in filtered_highlights:
            if highlight not in seen:
                unique_highlights.append(highlight)
                seen.add(highlight)
        
        logger.info(f"劃線預處理: {len(highlights)} → {len(unique_highlights)} 條")
        
        # 組合成文本，限制總長度避免 token 超限
        combined_text = "\n".join(unique_highlights)
        
        # 如果文本過長，截取前80%
        max_chars = 8000  # 約2000 tokens
        if len(combined_text) > max_chars:
            combined_text = combined_text[:max_chars] + "\n...(內容已截斷)"
            logger.info(f"劃線內容因長度限制已截斷至 {max_chars} 字符")
        
        return combined_text
    
    def _generate_summary_with_gemma(self, book_title: str, book_author: str, 
                                   highlights_text: str) -> Optional[str]:
        """使用 Gemma 模型生成總結"""
        
        prompt = self._create_summary_prompt(book_title, book_author, highlights_text)
        
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
                "num_ctx": 4096,
                "stop": ["```", "---", "=="]
            }
        }
        
        try:
            logger.info(f"向 Gemma API 發送請求: {self.api_url}")
            response = requests.post(
                self.api_url,
                json=payload,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                summary_text = result.get("response", "").strip()
                
                if summary_text:
                    logger.info(f"Gemma 生成總結成功，長度: {len(summary_text)} 字符")
                    return summary_text
                else:
                    logger.error("Gemma 回應為空")
                    return None
            else:
                logger.error(f"Gemma API 錯誤: {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.Timeout:
            logger.error("Gemma API 請求超時")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Gemma API 請求失敗: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"無法解析 Gemma 回應: {e}")
            return None
    
    def _create_summary_prompt(self, book_title: str, book_author: str, 
                             highlights_text: str) -> str:
        """創建總結提示詞"""
        
        return f"""請將以下書籍的劃線內容整理成 {self.target_points} 個重點段落。

**書籍資訊：**
- 書名：{book_title}
- 作者：{book_author}

**格式要求：**
1. 每個重點必須使用【標題】格式，標題不超過 {self.title_max_chars} 個字
2. 標題後接詳細說明，說明部分不超過 {self.max_chars_per_point} 個字
3. 確保每個重點都是從原文提煉的精華觀念
4. 保持原文的核心思想和邏輯結構
5. 使用繁體中文，符合台灣用語習慣
6. 總共必須有 {self.target_points} 個重點，不多不少

**範例格式：**
【時間管理】有效的時間規劃需要明確目標設定，透過優先順序排列和專注力集中，能夠大幅提升工作效率和生活品質。

【心理韌性】面對挫折時保持積極態度是成功的關鍵，透過正念練習和自我對話調整，可以建立更強的抗壓能力。

**原文劃線內容：**
{highlights_text}

**請嚴格按照上述格式輸出 {self.target_points} 個重點段落：**"""
    
    def _parse_summary_points(self, summary_text: str) -> List[BookSummaryPoint]:
        """解析總結重點"""
        points = []
        
        # 使用正則表達式匹配【標題】格式
        pattern = r'【([^】]+)】([^【]*?)(?=【|$)'
        matches = re.findall(pattern, summary_text, re.DOTALL)
        
        for i, (title, description) in enumerate(matches):
            title = title.strip()
            description = description.strip()
            
            # 移除可能的編號
            description = re.sub(r'^\d+\.\s*', '', description)
            
            # 計算字數
            char_count = len(description)
            
            # 檢查格式有效性
            is_valid = (
                len(title) <= self.title_max_chars and
                len(title) >= 2 and
                char_count <= self.max_chars_per_point * 1.2 and  # 允許20%彈性
                char_count >= 10
            )
            
            point = BookSummaryPoint(
                title=title,
                description=description,
                char_count=char_count,
                is_valid=is_valid
            )
            
            points.append(point)
            
            logger.debug(f"解析重點 {i+1}: 標題='{title}' 字數={char_count} 有效={is_valid}")
        
        logger.info(f"成功解析 {len(points)} 個重點段落")
        return points
    
    def _validate_summary_quality(self, points: List[BookSummaryPoint]) -> tuple[bool, Optional[str]]:
        """驗證總結品質"""
        if not points:
            return False, "未能解析到任何重點段落"
        
        # 檢查數量
        if len(points) != self.target_points:
            return False, f"重點數量不正確：期望 {self.target_points} 個，實際 {len(points)} 個"
        
        # 檢查格式有效性
        invalid_points = [p for p in points if not p.is_valid]
        if invalid_points:
            return False, f"有 {len(invalid_points)} 個重點格式不符合要求"
        
        # 檢查標題重複
        titles = [p.title for p in points]
        if len(set(titles)) != len(titles):
            return False, "發現重複的重點標題"
        
        # 檢查內容重複（簡單檢查）
        descriptions = [p.description for p in points]
        unique_descriptions = set(descriptions)
        if len(unique_descriptions) < len(descriptions) * 0.8:  # 允許20%重複率
            return False, "重點內容重複率過高"
        
        return True, None
    
    def format_summary_for_output(self, summary: BookSummary) -> str:
        """格式化總結輸出"""
        if not summary.generation_success:
            return f"❌ 書籍總結生成失敗\n錯誤訊息：{summary.error_message}"
        
        output = []
        output.append(f"📚 書名：{summary.book_title}")
        output.append(f"👤 作者：{summary.book_author}")
        output.append(f"📝 劃線數量：{summary.highlight_count} 條")
        output.append(f"📋 重點數量：{len(summary.summary_points)} 個")
        output.append("")
        output.append("=" * 50)
        output.append("📖 重點總結")
        output.append("=" * 50)
        output.append("")
        
        for i, point in enumerate(summary.summary_points, 1):
            output.append(f"{i:2d}. 【{point.title}】{point.description}")
            output.append("")
        
        return "\n".join(output)
    
    def is_available(self) -> bool:
        """檢查 Gemma 服務是否可用"""
        try:
            test_payload = {
                "model": self.model_name,
                "prompt": "測試",
                "stream": False,
                "options": {"num_predict": 1}
            }
            
            response = requests.post(
                self.api_url,
                json=test_payload,
                timeout=10
            )
            
            return response.status_code == 200
            
        except Exception as e:
            logger.debug(f"Gemma 服務可用性檢查失敗: {e}")
            return False