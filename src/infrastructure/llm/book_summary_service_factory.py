import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from .llm_environment_checker import LLMEnvironmentChecker, ServiceMode
from .enhanced_gemma_service import EnhancedGemmaService, BookSummary
from .openai_review_service import OpenAIReviewService, ReviewResult

logger = logging.getLogger(__name__)


@dataclass
class SummaryProcessingResult:
    """總結處理結果"""
    success: bool
    final_summary: Optional[BookSummary]
    service_mode_used: ServiceMode
    gemma_result: Optional[BookSummary] = None
    openai_result: Optional[ReviewResult] = None
    processing_time: Optional[float] = None
    error_message: Optional[str] = None


class BookSummaryServiceFactory:
    """書籍總結服務工廠"""
    
    def __init__(self):
        self.env_checker = LLMEnvironmentChecker()
        self.gemma_service = None
        self.openai_service = None
        self._initialize_services()
    
    def _initialize_services(self):
        """初始化服務"""
        # 檢查環境狀態
        env_status = self.env_checker.check_environment_status()
        
        # 初始化 Gemma 服務
        if env_status['gemma_accessible']:
            try:
                self.gemma_service = EnhancedGemmaService()
                logger.info("Gemma 服務初始化成功")
            except Exception as e:
                logger.error(f"Gemma 服務初始化失敗: {e}")
        
        # 初始化 OpenAI 服務
        if env_status['openai_accessible']:
            try:
                self.openai_service = OpenAIReviewService()
                logger.info("OpenAI 服務初始化成功")
            except Exception as e:
                logger.error(f"OpenAI 服務初始化失敗: {e}")
    
    def process_book_summary(self, book_title: str, book_author: str, 
                           highlights: List[str]) -> SummaryProcessingResult:
        """
        處理書籍總結（根據可用服務自動選擇處理模式）
        
        Args:
            book_title: 書籍標題
            book_author: 書籍作者  
            highlights: 劃線內容列表
            
        Returns:
            SummaryProcessingResult: 處理結果
        """
        import time
        start_time = time.time()
        
        # 獲取服務模式
        service_mode = self.env_checker.get_service_mode()
        
        logger.info(f"開始處理書籍總結: {book_title}")
        logger.info(f"使用服務模式: {service_mode.value}")
        logger.info(f"劃線數量: {len(highlights)}")
        
        try:
            if service_mode == ServiceMode.DISABLED:
                return self._handle_disabled_mode(book_title, book_author, highlights)
            
            elif service_mode == ServiceMode.GEMMA_ONLY:
                return self._handle_gemma_only_mode(book_title, book_author, highlights)
            
            elif service_mode == ServiceMode.OPENAI_ONLY:
                return self._handle_openai_only_mode(book_title, book_author, highlights)
            
            elif service_mode == ServiceMode.FULL_SERVICE:
                return self._handle_full_service_mode(book_title, book_author, highlights)
            
            else:
                return SummaryProcessingResult(
                    success=False,
                    final_summary=None,
                    service_mode_used=service_mode,
                    error_message=f"未知的服務模式: {service_mode}"
                )
                
        except Exception as e:
            logger.error(f"處理書籍總結時發生錯誤: {e}", exc_info=True)
            return SummaryProcessingResult(
                success=False,
                final_summary=None,
                service_mode_used=service_mode,
                processing_time=time.time() - start_time,
                error_message=f"處理過程發生錯誤: {str(e)}"
            )
        
        finally:
            processing_time = time.time() - start_time
            logger.info(f"總結處理完成，耗時: {processing_time:.2f} 秒")
    
    def _handle_disabled_mode(self, book_title: str, book_author: str, 
                            highlights: List[str]) -> SummaryProcessingResult:
        """處理停用模式"""
        logger.info("LLM 服務未啟用，跳過總結生成")
        
        return SummaryProcessingResult(
            success=False,
            final_summary=None,
            service_mode_used=ServiceMode.DISABLED,
            error_message="LLM 服務未配置，請設定相關環境變數以啟用總結功能"
        )
    
    def _handle_gemma_only_mode(self, book_title: str, book_author: str, 
                              highlights: List[str]) -> SummaryProcessingResult:
        """處理僅 Gemma 模式"""
        if not self.gemma_service:
            return SummaryProcessingResult(
                success=False,
                final_summary=None,
                service_mode_used=ServiceMode.GEMMA_ONLY,
                error_message="Gemma 服務未初始化"
            )
        
        logger.info("使用 Gemma 進行總結")
        
        # 生成總結
        gemma_result = self.gemma_service.generate_book_summary(
            book_title, book_author, highlights
        )
        
        return SummaryProcessingResult(
            success=gemma_result.generation_success,
            final_summary=gemma_result,
            service_mode_used=ServiceMode.GEMMA_ONLY,
            gemma_result=gemma_result,
            error_message=gemma_result.error_message if not gemma_result.generation_success else None
        )
    
    def _handle_openai_only_mode(self, book_title: str, book_author: str, 
                                highlights: List[str]) -> SummaryProcessingResult:
        """處理僅 OpenAI 模式"""
        if not self.openai_service:
            return SummaryProcessingResult(
                success=False,
                final_summary=None,
                service_mode_used=ServiceMode.OPENAI_ONLY,
                error_message="OpenAI 服務未初始化"
            )
        
        logger.info("使用 OpenAI 直接進行總結")
        
        # 由於 OpenAI 服務設計為審核器，這裡需要先創建一個基礎總結
        # 或者實現 OpenAI 直接總結功能
        # 這裡簡化為使用 OpenAI 的總結能力
        
        try:
            openai_summary = self._generate_openai_direct_summary(
                book_title, book_author, highlights
            )
            
            return SummaryProcessingResult(
                success=openai_summary.generation_success,
                final_summary=openai_summary,
                service_mode_used=ServiceMode.OPENAI_ONLY,
                error_message=openai_summary.error_message if not openai_summary.generation_success else None
            )
            
        except Exception as e:
            return SummaryProcessingResult(
                success=False,
                final_summary=None,
                service_mode_used=ServiceMode.OPENAI_ONLY,
                error_message=f"OpenAI 直接總結失敗: {str(e)}"
            )
    
    def _handle_full_service_mode(self, book_title: str, book_author: str, 
                                highlights: List[str]) -> SummaryProcessingResult:
        """處理完整服務模式（Gemma + OpenAI）"""
        if not self.gemma_service or not self.openai_service:
            missing_services = []
            if not self.gemma_service:
                missing_services.append("Gemma")
            if not self.openai_service:
                missing_services.append("OpenAI")
            
            return SummaryProcessingResult(
                success=False,
                final_summary=None,
                service_mode_used=ServiceMode.FULL_SERVICE,
                error_message=f"服務未初始化: {', '.join(missing_services)}"
            )
        
        logger.info("使用完整服務: Gemma 總結 + OpenAI 審核")
        
        # 第一階段：Gemma 生成初始總結
        logger.info("第一階段: 使用 Gemma 生成初始總結")
        gemma_result = self.gemma_service.generate_book_summary(
            book_title, book_author, highlights
        )
        
        if not gemma_result.generation_success:
            logger.error("Gemma 總結生成失敗，無法進行後續審核")
            return SummaryProcessingResult(
                success=False,
                final_summary=None,
                service_mode_used=ServiceMode.FULL_SERVICE,
                gemma_result=gemma_result,
                error_message=f"Gemma 階段失敗: {gemma_result.error_message}"
            )
        
        # 第二階段：OpenAI 審核和改進
        logger.info("第二階段: 使用 OpenAI 審核和改進")
        openai_result = self.openai_service.review_and_improve_summary(
            highlights, gemma_result
        )
        
        # 決定最終結果
        if openai_result.success and openai_result.reviewed_summary:
            final_summary = openai_result.reviewed_summary
            success = True
            logger.info(f"雙模型處理成功，審核評分: {openai_result.review_score:.2f}")
        else:
            # OpenAI 審核失敗，使用 Gemma 結果
            final_summary = gemma_result
            success = gemma_result.generation_success
            logger.warning("OpenAI 審核失敗，使用 Gemma 原始結果")
        
        return SummaryProcessingResult(
            success=success,
            final_summary=final_summary,
            service_mode_used=ServiceMode.FULL_SERVICE,
            gemma_result=gemma_result,
            openai_result=openai_result
        )
    
    def _generate_openai_direct_summary(self, book_title: str, book_author: str, 
                                      highlights: List[str]) -> BookSummary:
        """使用 OpenAI 直接生成總結（簡化實現）"""
        # 這是一個簡化的實現，實際上應該創建專門的 OpenAI 總結服務
        # 這裡重用審核服務的 API 調用能力
        
        from .enhanced_gemma_service import BookSummaryPoint
        
        try:
            # 創建直接總結的提示詞
            highlights_text = "\n".join(highlights[:30])  # 限制長度
            if len(highlights_text) > 4000:
                highlights_text = highlights_text[:4000] + "\n...(內容已截斷)"
            
            prompt = f"""請將以下書籍的劃線內容總結成16個重點。

**書籍資訊：**
- 書名：{book_title}
- 作者：{book_author}

**格式要求：**
- 使用【標題】格式，標題不超過10字
- 每個重點說明不超過50字
- 總共16個重點，使用繁體中文

**劃線內容：**
{highlights_text}

**請按以下格式輸出：**
1. 【標題1】說明內容...
2. 【標題2】說明內容...
...
16. 【標題16】說明內容..."""
            
            # 調用 OpenAI API
            response = self.openai_service.client.chat.completions.create(
                model=self.openai_service.model_name,
                messages=[
                    {"role": "system", "content": "你是一位專業的內容總結專家。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=1500
            )
            
            content = response.choices[0].message.content.strip()
            
            # 解析結果（重用 Gemma 的解析邏輯）
            import re
            pattern = r'(?:\d+\.\s*)?【([^】]+)】([^【]*?)(?=\d+\.\s*【|$)'
            matches = re.findall(pattern, content, re.DOTALL)
            
            summary_points = []
            for title, description in matches:
                title = title.strip()
                description = description.strip()
                description = re.sub(r'^\d+\.\s*', '', description)
                
                point = BookSummaryPoint(
                    title=title,
                    description=description,
                    char_count=len(description),
                    is_valid=len(title) <= 10 and len(description) <= 60
                )
                summary_points.append(point)
            
            success = len(summary_points) == 16
            
            return BookSummary(
                book_title=book_title,
                book_author=book_author,
                highlight_count=len(highlights),
                summary_points=summary_points,
                generation_success=success,
                error_message=None if success else f"解析到 {len(summary_points)} 個重點，期望16個"
            )
            
        except Exception as e:
            logger.error(f"OpenAI 直接總結失敗: {e}")
            return BookSummary(
                book_title=book_title,
                book_author=book_author,
                highlight_count=len(highlights),
                summary_points=[],
                generation_success=False,
                error_message=f"OpenAI 直接總結失敗: {str(e)}"
            )
    
    def get_service_status(self) -> Dict:
        """獲取服務狀態"""
        return self.env_checker.check_environment_status()
    
    def is_service_available(self) -> bool:
        """檢查是否有任何 LLM 服務可用"""
        return self.env_checker.get_service_mode() != ServiceMode.DISABLED
    
    def format_processing_result(self, result: SummaryProcessingResult) -> str:
        """格式化處理結果"""
        if not result.success:
            return f"❌ 總結處理失敗\n錯誤訊息：{result.error_message}"
        
        output = []
        output.append("📊 總結處理結果")
        output.append("=" * 50)
        output.append(f"🔧 服務模式：{result.service_mode_used.value}")
        
        if result.processing_time:
            output.append(f"⏱️  處理時間：{result.processing_time:.2f} 秒")
        
        # Gemma 結果
        if result.gemma_result:
            output.append(f"🤖 Gemma 結果：{'✅ 成功' if result.gemma_result.generation_success else '❌ 失敗'}")
        
        # OpenAI 結果  
        if result.openai_result:
            output.append(f"🔍 OpenAI 審核：{'✅ 成功' if result.openai_result.success else '❌ 失敗'}")
            if result.openai_result.success:
                output.append(f"📈 審核評分：{result.openai_result.review_score:.2f}/1.00")
                output.append(f"✨ 改進項目：{len(result.openai_result.improvements_made)} 個")
        
        output.append("")
        
        # 最終總結
        if result.final_summary:
            final_service = EnhancedGemmaService()
            formatted_summary = final_service.format_summary_for_output(result.final_summary)
            output.append(formatted_summary)
        
        return "\n".join(output)