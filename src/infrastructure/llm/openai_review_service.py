import os
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from .enhanced_gemma_service import BookSummary, BookSummaryPoint

logger = logging.getLogger(__name__)

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.warning("OpenAI package not available. Install with: pip install openai")


@dataclass
class ReviewResult:
    """審核結果"""
    success: bool
    reviewed_summary: Optional[BookSummary]
    improvements_made: List[str]
    review_score: float  # 0.0 - 1.0
    error_message: Optional[str] = None


class OpenAIReviewService:
    """OpenAI 審核服務"""
    
    def __init__(self):
        self.api_key = os.getenv('OPENAI_API_KEY')
        self.model_name = os.getenv('OPENAI_MODEL', 'gpt-4')
        self.client = None
        
        if OPENAI_AVAILABLE and self.api_key:
            self.client = OpenAI(api_key=self.api_key)
        
        # 審核配置
        self.temperature = 0.2  # 較低溫度確保一致性
        self.max_tokens = 1500
        self.target_points = int(os.getenv('SUMMARY_POINTS', '16'))
        self.max_chars_per_point = 50
    
    def review_and_improve_summary(self, original_highlights: List[str], 
                                  gemma_summary: BookSummary) -> ReviewResult:
        """
        審核並改進 Gemma 生成的總結
        
        Args:
            original_highlights: 原始劃線內容
            gemma_summary: Gemma 生成的總結
            
        Returns:
            ReviewResult: 審核結果
        """
        if not self.is_available():
            return ReviewResult(
                success=False,
                reviewed_summary=None,
                improvements_made=[],
                review_score=0.0,
                error_message="OpenAI 服務不可用"
            )
        
        if not gemma_summary.generation_success:
            return ReviewResult(
                success=False,
                reviewed_summary=None,
                improvements_made=[],
                review_score=0.0,
                error_message="原始總結生成失敗，無法進行審核"
            )
        
        logger.info(f"開始審核書籍總結: {gemma_summary.book_title}")
        
        try:
            # 生成審核提示詞
            review_prompt = self._create_review_prompt(
                original_highlights, gemma_summary
            )
            
            # 呼叫 OpenAI API
            reviewed_content = self._call_openai_api(review_prompt)
            
            if not reviewed_content:
                return ReviewResult(
                    success=False,
                    reviewed_summary=None,
                    improvements_made=[],
                    review_score=0.0,
                    error_message="OpenAI 未能生成有效回應"
                )
            
            # 解析審核結果
            reviewed_summary, improvements = self._parse_review_result(
                reviewed_content, gemma_summary
            )
            
            # 計算改進評分
            review_score = self._calculate_review_score(
                gemma_summary, reviewed_summary
            )
            
            return ReviewResult(
                success=True,
                reviewed_summary=reviewed_summary,
                improvements_made=improvements,
                review_score=review_score
            )
            
        except Exception as e:
            logger.error(f"審核過程發生錯誤: {e}", exc_info=True)
            return ReviewResult(
                success=False,
                reviewed_summary=None,
                improvements_made=[],
                review_score=0.0,
                error_message=f"審核過程發生錯誤: {str(e)}"
            )
    
    def _create_review_prompt(self, original_highlights: List[str], 
                            gemma_summary: BookSummary) -> str:
        """創建審核提示詞"""
        
        # 限制原始劃線內容長度
        highlights_text = "\n".join(original_highlights[:20])  # 取前20條作為參考
        if len(highlights_text) > 3000:
            highlights_text = highlights_text[:3000] + "\n...(內容已截斷)"
        
        # 格式化 Gemma 總結
        gemma_points = []
        for i, point in enumerate(gemma_summary.summary_points, 1):
            gemma_points.append(f"{i}. 【{point.title}】{point.description}")
        
        gemma_text = "\n".join(gemma_points)
        
        return f"""你是一位專業的內容審核專家，請對以下 AI 生成的書籍重點總結進行審核和改進。

**審核任務：**
1. **準確性檢查**：重點是否準確反映原書內容
2. **精簡優化**：確保每個重點簡潔有力，避免冗餘
3. **邏輯重組**：調整重點順序，建立清晰的邏輯結構
4. **完整性評估**：確保涵蓋重要概念，補充遺漏要點
5. **可讀性提升**：改善用詞和表達方式

**書籍資訊：**
- 書名：{gemma_summary.book_title}
- 作者：{gemma_summary.book_author}
- 劃線數量：{gemma_summary.highlight_count} 條

**格式要求：**
- 必須保持 {self.target_points} 個重點
- 使用【標題】格式（標題10字內）
- 每個重點說明不超過 {self.max_chars_per_point} 字
- 使用繁體中文，符合台灣用語習慣

**原始劃線內容（參考用）：**
{highlights_text}

**待審核的 AI 生成總結：**
{gemma_text}

**請提供審核後的改進版本，嚴格按照以下格式輸出：**

=== 改進後總結 ===
1. 【改進標題1】改進後的說明內容...
2. 【改進標題2】改進後的說明內容...
...
{self.target_points}. 【改進標題{self.target_points}】改進後的說明內容...

=== 改進說明 ===
- 改進項目1：具體說明...
- 改進項目2：具體說明...
（請列出主要的改進項目）"""
    
    def _call_openai_api(self, prompt: str) -> Optional[str]:
        """呼叫 OpenAI API"""
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "你是一位專業的內容審核和編輯專家，擅長改善和優化文本內容。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            
            content = response.choices[0].message.content.strip()
            
            if content:
                logger.info(f"OpenAI 審核完成，回應長度: {len(content)} 字符")
                return content
            else:
                logger.error("OpenAI 回應為空")
                return None
                
        except Exception as e:
            logger.error(f"OpenAI API 呼叫失敗: {e}")
            return None
    
    def _parse_review_result(self, reviewed_content: str, 
                           original_summary: BookSummary) -> Tuple[BookSummary, List[str]]:
        """解析審核結果"""
        
        # 分割內容
        parts = reviewed_content.split("=== 改進說明 ===")
        summary_part = parts[0].replace("=== 改進後總結 ===", "").strip()
        improvements_part = parts[1].strip() if len(parts) > 1 else ""
        
        # 解析改進項目
        improvements = []
        if improvements_part:
            for line in improvements_part.split('\n'):
                line = line.strip()
                if line.startswith('- ') or line.startswith('•'):
                    improvements.append(line[2:].strip())
        
        # 解析總結重點 (重用 Gemma 的解析邏輯)
        import re
        pattern = r'(?:\d+\.\s*)?【([^】]+)】([^【]*?)(?=\d+\.\s*【|$)'
        matches = re.findall(pattern, summary_part, re.DOTALL)
        
        reviewed_points = []
        for title, description in matches:
            title = title.strip()
            description = description.strip()
            
            # 移除可能的編號和多餘空白
            description = re.sub(r'^\d+\.\s*', '', description)
            description = re.sub(r'\s+', ' ', description)
            
            point = BookSummaryPoint(
                title=title,
                description=description,
                char_count=len(description),
                is_valid=len(title) <= 10 and len(description) <= self.max_chars_per_point * 1.2
            )
            reviewed_points.append(point)
        
        # 如果解析失敗，返回原始總結
        if len(reviewed_points) != self.target_points:
            logger.warning(f"審核結果解析異常，期望 {self.target_points} 個重點，實際解析到 {len(reviewed_points)} 個")
            return original_summary, improvements
        
        # 創建審核後的總結
        reviewed_summary = BookSummary(
            book_title=original_summary.book_title,
            book_author=original_summary.book_author,
            highlight_count=original_summary.highlight_count,
            summary_points=reviewed_points,
            generation_success=True
        )
        
        logger.info(f"成功解析審核結果: {len(reviewed_points)} 個重點，{len(improvements)} 個改進項目")
        
        return reviewed_summary, improvements
    
    def _calculate_review_score(self, original: BookSummary, 
                              reviewed: BookSummary) -> float:
        """計算審核改進評分"""
        if not reviewed.generation_success:
            return 0.0
        
        score = 0.0
        max_score = 1.0
        
        # 基礎分數（成功審核）
        score += 0.3
        
        # 格式改進分數
        original_valid = sum(1 for p in original.summary_points if p.is_valid)
        reviewed_valid = sum(1 for p in reviewed.summary_points if p.is_valid)
        
        if reviewed_valid > original_valid:
            score += 0.2
        elif reviewed_valid == len(reviewed.summary_points):
            score += 0.1
        
        # 內容長度優化分數
        original_avg_length = sum(p.char_count for p in original.summary_points) / len(original.summary_points)
        reviewed_avg_length = sum(p.char_count for p in reviewed.summary_points) / len(reviewed.summary_points)
        
        # 理想長度是30-45字
        original_length_score = 1.0 - abs(original_avg_length - 37.5) / 37.5
        reviewed_length_score = 1.0 - abs(reviewed_avg_length - 37.5) / 37.5
        
        if reviewed_length_score > original_length_score:
            score += 0.3
        
        # 標題多樣性分數
        original_titles = [p.title for p in original.summary_points]
        reviewed_titles = [p.title for p in reviewed.summary_points]
        
        original_unique_ratio = len(set(original_titles)) / len(original_titles)
        reviewed_unique_ratio = len(set(reviewed_titles)) / len(reviewed_titles)
        
        if reviewed_unique_ratio > original_unique_ratio:
            score += 0.2
        
        return min(score, max_score)
    
    def format_review_result(self, result: ReviewResult) -> str:
        """格式化審核結果"""
        if not result.success:
            return f"❌ 審核失敗\n錯誤訊息：{result.error_message}"
        
        output = []
        output.append("🔍 OpenAI 審核結果")
        output.append("=" * 40)
        output.append(f"📊 審核評分：{result.review_score:.2f}/1.00")
        output.append(f"✨ 改進項目數：{len(result.improvements_made)}")
        output.append("")
        
        if result.improvements_made:
            output.append("🔧 主要改進項目：")
            for i, improvement in enumerate(result.improvements_made, 1):
                output.append(f"  {i}. {improvement}")
            output.append("")
        
        # 顯示改進後的總結
        if result.reviewed_summary:
            output.append("📝 審核後總結：")
            output.append("-" * 30)
            for i, point in enumerate(result.reviewed_summary.summary_points, 1):
                output.append(f"{i:2d}. 【{point.title}】{point.description}")
            output.append("")
        
        return "\n".join(output)
    
    def is_available(self) -> bool:
        """檢查 OpenAI 服務是否可用"""
        if not OPENAI_AVAILABLE:
            return False
        
        if not self.api_key or not self.client:
            return False
        
        try:
            # 簡單的連接測試
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": "測試"}],
                max_tokens=1
            )
            return bool(response.choices)
        except Exception as e:
            logger.debug(f"OpenAI 服務可用性檢查失敗: {e}")
            return False