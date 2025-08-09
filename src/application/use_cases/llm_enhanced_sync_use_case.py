from typing import Optional, Dict, Any, List
import logging
from ...infrastructure.llm.llm_factory import LLMFactory
from ...infrastructure.llm.base_llm import BaseLLM
import DBReader

logger = logging.getLogger(__name__)


class LLMEnhancedSyncUseCase:
    """Use case for LLM-enhanced book synchronization"""
    
    def __init__(self, llm_config: Optional[Dict[str, Any]] = None):
        """
        Initialize with LLM configuration
        
        Args:
            llm_config: Configuration dict with keys like 'type', 'model_name', etc.
        """
        self.llm_config = llm_config or {}
        self.llm_client = None
        self._initialize_llm()
    
    def _initialize_llm(self) -> None:
        """Initialize LLM client based on configuration"""
        llm_type = self.llm_config.get('type', 'auto')
        
        if llm_type == 'auto':
            self.llm_client = LLMFactory.get_best_available_llm(**self.llm_config)
        else:
            self.llm_client = LLMFactory.create_llm(llm_type, **self.llm_config)
        
        if self.llm_client:
            logger.info(f"LLM initialized: {self.llm_client.model_name}")
        else:
            logger.warning("No LLM client available - falling back to basic functionality")
    
    def enhance_book_highlights(self, book_id: str) -> Dict[str, Any]:
        """
        Enhance book highlights with LLM-generated insights
        
        Args:
            book_id: Book identifier
            
        Returns:
            Enhanced book data with LLM insights
        """
        # Get original highlights with chapter info
        highlights_with_chapter = DBReader.getHLWithChapterFromDB(book_id)
        
        if not highlights_with_chapter:
            return {
                "book_id": book_id,
                "highlights": [],
                "llm_insights": None,
                "enhanced_chapters": []
            }
        
        result = {
            "book_id": book_id,
            "highlights": highlights_with_chapter,
            "llm_insights": None,
            "enhanced_chapters": []
        }
        
        # Apply LLM enhancements if available
        if self.llm_client and self.llm_client.is_available():
            try:
                # Generate book-level insights
                result["llm_insights"] = self._generate_book_insights(highlights_with_chapter)
                
                # Enhance chapter titles and add chapter summaries
                result["enhanced_chapters"] = self._enhance_chapters(highlights_with_chapter)
                
                logger.info(f"Successfully enhanced book {book_id} with LLM insights")
                
            except Exception as e:
                logger.error(f"LLM enhancement failed for book {book_id}: {e}")
        
        return result
    
    def _generate_book_insights(self, highlights: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate book-level insights using LLM"""
        if not self.llm_client or not highlights:
            return {}
        
        try:
            insights = self.llm_client.process_highlights(highlights)
            
            # Add sentiment analysis
            texts = [h.get('text', '') for h in highlights if h.get('text')]
            sentiment_data = self.llm_client.analyze_book_sentiment(texts)
            insights.update(sentiment_data)
            
            return insights
            
        except Exception as e:
            logger.error(f"Failed to generate book insights: {e}")
            return {}
    
    def _enhance_chapters(self, highlights: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Enhance chapters with better titles and summaries"""
        if not self.llm_client:
            return []
        
        # Group highlights by chapter
        chapter_groups = {}
        for highlight in highlights:
            chapter_name = highlight.get('chapter_name', '未知章节')
            if chapter_name not in chapter_groups:
                chapter_groups[chapter_name] = []
            chapter_groups[chapter_name].append(highlight)
        
        enhanced_chapters = []
        
        for chapter_name, chapter_highlights in chapter_groups.items():
            try:
                # Get chapter context from highlights
                chapter_texts = [h.get('text', '') for h in chapter_highlights if h.get('text')]
                context = " ".join(chapter_texts[:3])  # Use first 3 highlights as context
                
                # Enhance chapter title if it's generic
                enhanced_title = chapter_name
                if self._is_generic_title(chapter_name) and context:
                    enhanced_title = self.llm_client.improve_chapter_title(chapter_name, context)
                
                # Generate chapter summary
                chapter_summary = ""
                if len(chapter_texts) > 2:  # Only summarize if there are enough highlights
                    chapter_text = " ".join(chapter_texts)
                    chapter_summary = self.llm_client.generate_summary(chapter_text, max_length=50)
                
                enhanced_chapter = {
                    "original_title": chapter_name,
                    "enhanced_title": enhanced_title,
                    "summary": chapter_summary,
                    "highlight_count": len(chapter_highlights),
                    "highlights": chapter_highlights
                }
                
                enhanced_chapters.append(enhanced_chapter)
                
            except Exception as e:
                logger.error(f"Failed to enhance chapter {chapter_name}: {e}")
                # Fall back to original chapter
                enhanced_chapters.append({
                    "original_title": chapter_name,
                    "enhanced_title": chapter_name,
                    "summary": "",
                    "highlight_count": len(chapter_highlights),
                    "highlights": chapter_highlights
                })
        
        return enhanced_chapters
    
    def _is_generic_title(self, title: str) -> bool:
        """Check if a chapter title is generic and could be improved"""
        generic_patterns = [
            "第",  # 第1章, 第2章
            "章节",  # 章节1, 章节2
            "Section",  # Section001
            "Chapter",  # Chapter1
            "未知"  # 未知章节
        ]
        
        return any(pattern in title for pattern in generic_patterns)
    
    def get_llm_status(self) -> Dict[str, Any]:
        """Get status of LLM integration"""
        return {
            "llm_available": self.llm_client is not None,
            "llm_model": self.llm_client.model_name if self.llm_client else None,
            "llm_service_available": self.llm_client.is_available() if self.llm_client else False,
            "available_services": LLMFactory.get_available_llms()
        }