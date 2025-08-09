from abc import ABC, abstractmethod
from typing import Optional, Dict, Any


class BaseLLM(ABC):
    """Abstract base class for LLM integrations"""
    
    def __init__(self, model_name: str, **kwargs):
        self.model_name = model_name
        self.config = kwargs
    
    @abstractmethod
    def generate_summary(self, text: str, max_length: int = 100) -> str:
        """Generate a summary of the given text"""
        pass
    
    @abstractmethod
    def extract_themes(self, highlights: list[str]) -> list[str]:
        """Extract main themes from a list of highlights"""
        pass
    
    @abstractmethod
    def improve_chapter_title(self, original_title: str, context: str) -> str:
        """Improve chapter title based on context"""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if the LLM service is available"""
        pass
    
    def process_highlights(self, highlights: list[Dict[str, Any]]) -> Dict[str, Any]:
        """Process highlights and extract insights"""
        if not self.is_available():
            return {"error": "LLM service not available"}
        
        texts = [h.get('text', '') for h in highlights if h.get('text')]
        
        if not texts:
            return {"themes": [], "summary": ""}
        
        combined_text = " ".join(texts)
        
        return {
            "themes": self.extract_themes(texts),
            "summary": self.generate_summary(combined_text),
            "highlight_count": len(texts)
        }