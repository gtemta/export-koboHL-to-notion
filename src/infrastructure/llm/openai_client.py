import openai
from typing import Optional, Dict, Any, List
from .base_llm import BaseLLM
import logging
import os

logger = logging.getLogger(__name__)


class OpenAIClient(BaseLLM):
    """OpenAI API client implementation (can work with local OpenAI-compatible APIs)"""
    
    def __init__(self, model_name: str = "gpt-3.5-turbo", api_key: str = None, base_url: str = None, **kwargs):
        super().__init__(model_name, **kwargs)
        
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        
        # Initialize client with custom base URL if provided (for local APIs)
        if self.base_url:
            self.client = openai.OpenAI(api_key=self.api_key, base_url=self.base_url)
        else:
            self.client = openai.OpenAI(api_key=self.api_key)
    
    def _make_request(self, messages: List[Dict[str, str]], max_tokens: int = 150) -> Optional[str]:
        """Make a request to OpenAI API"""
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.7
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            logger.error(f"OpenAI API request failed: {e}")
            return None
    
    def is_available(self) -> bool:
        """Check if OpenAI API is available"""
        if not self.api_key:
            return False
        
        try:
            # Try a simple request to test availability
            messages = [{"role": "user", "content": "Hello"}]
            response = self._make_request(messages, max_tokens=5)
            return response is not None
        except Exception:
            return False
    
    def generate_summary(self, text: str, max_length: int = 100) -> str:
        """Generate a summary of the given text"""
        if not text.strip():
            return ""
        
        messages = [
            {"role": "system", "content": f"You are a helpful assistant that creates concise summaries in approximately {max_length} words."},
            {"role": "user", "content": f"Please summarize the following text concisely:\n\n{text}"}
        ]
        
        result = self._make_request(messages, max_tokens=max_length + 50)
        return result if result else "Summary generation failed"
    
    def extract_themes(self, highlights: List[str]) -> List[str]:
        """Extract main themes from a list of highlights"""
        if not highlights:
            return []
        
        combined_text = "\n".join(highlights)
        messages = [
            {"role": "system", "content": "You are an expert at identifying key themes and concepts in text. Extract 3-5 main themes as single words or short phrases."},
            {"role": "user", "content": f"Extract the main themes from these book highlights. Return only the themes, one per line:\n\n{combined_text}"}
        ]
        
        result = self._make_request(messages, max_tokens=100)
        if result:
            themes = [theme.strip() for theme in result.split('\n') if theme.strip()]
            return themes[:5]  # Limit to 5 themes
        return []
    
    def improve_chapter_title(self, original_title: str, context: str) -> str:
        """Improve chapter title based on context"""
        if not original_title or not context:
            return original_title
        
        messages = [
            {"role": "system", "content": "You are an expert at creating clear, engaging chapter titles. Improve the given title based on the context provided."},
            {"role": "user", "content": f"Original title: {original_title}\nContext: {context}\n\nProvide an improved, clear chapter title (keep it under 60 characters):"}
        ]
        
        result = self._make_request(messages, max_tokens=50)
        if result and len(result) <= 60:
            return result
        return original_title
    
    def analyze_book_sentiment(self, highlights: List[str]) -> Dict[str, Any]:
        """Analyze the overall sentiment and tone of book highlights"""
        if not highlights:
            return {"sentiment": "neutral", "confidence": 0}
        
        combined_text = "\n".join(highlights[:10])  # Limit for analysis
        messages = [
            {"role": "system", "content": "You are a sentiment analysis expert. Analyze the overall sentiment and tone."},
            {"role": "user", "content": f"Analyze the sentiment of these book highlights. Respond with only: positive/negative/neutral and a confidence score 0-1:\n\n{combined_text}"}
        ]
        
        result = self._make_request(messages, max_tokens=20)
        if result:
            parts = result.lower().split()
            sentiment = "neutral"
            confidence = 0.5
            
            for part in parts:
                if part in ["positive", "negative", "neutral"]:
                    sentiment = part
                try:
                    if "." in part:
                        confidence = float(part)
                        break
                except ValueError:
                    continue
            
            return {"sentiment": sentiment, "confidence": confidence}
        
        return {"sentiment": "neutral", "confidence": 0}