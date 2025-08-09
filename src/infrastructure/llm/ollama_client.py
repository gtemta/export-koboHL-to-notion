import requests
import json
from typing import Optional, Dict, Any, List
from .base_llm import BaseLLM
import logging

logger = logging.getLogger(__name__)


class OllamaClient(BaseLLM):
    """Ollama local LLM client implementation"""
    
    def __init__(self, model_name: str = "llama3.2", host: str = "http://localhost:11434", **kwargs):
        super().__init__(model_name, **kwargs)
        self.host = host.rstrip('/')
        self.api_url = f"{self.host}/api"
        self.timeout = kwargs.get('timeout', 30)
    
    def _make_request(self, prompt: str, system_prompt: str = None) -> Optional[str]:
        """Make a request to Ollama API"""
        try:
            payload = {
                "model": self.model_name,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "num_ctx": 4096
                }
            }
            
            if system_prompt:
                payload["system"] = system_prompt
            
            response = requests.post(
                f"{self.api_url}/generate",
                json=payload,
                timeout=self.timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                return result.get('response', '').strip()
            else:
                logger.error(f"Ollama API error: {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Request to Ollama failed: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Ollama response: {e}")
            return None
    
    def is_available(self) -> bool:
        """Check if Ollama service is running and model is available"""
        try:
            # Check if service is running
            response = requests.get(f"{self.api_url}/tags", timeout=5)
            if response.status_code != 200:
                return False
            
            # Check if our model is available
            models = response.json().get('models', [])
            available_models = [model.get('name', '') for model in models]
            
            return any(self.model_name in model for model in available_models)
            
        except requests.exceptions.RequestException:
            return False
    
    def generate_summary(self, text: str, max_length: int = 100) -> str:
        """Generate a summary of the given text"""
        if not text.strip():
            return ""
        
        system_prompt = f"You are a helpful assistant that creates concise summaries. Generate a summary in approximately {max_length} words."
        prompt = f"Please summarize the following text concisely:\n\n{text}"
        
        result = self._make_request(prompt, system_prompt)
        return result if result else "Summary generation failed"
    
    def extract_themes(self, highlights: List[str]) -> List[str]:
        """Extract main themes from a list of highlights"""
        if not highlights:
            return []
        
        combined_text = "\n".join(highlights)
        system_prompt = "You are an expert at identifying key themes and concepts in text. Extract 3-5 main themes as single words or short phrases."
        prompt = f"Extract the main themes from these book highlights. Return only the themes, one per line:\n\n{combined_text}"
        
        result = self._make_request(prompt, system_prompt)
        if result:
            themes = [theme.strip() for theme in result.split('\n') if theme.strip()]
            return themes[:5]  # Limit to 5 themes
        return []
    
    def improve_chapter_title(self, original_title: str, context: str) -> str:
        """Improve chapter title based on context"""
        if not original_title or not context:
            return original_title
        
        system_prompt = "You are an expert at creating clear, engaging chapter titles. Improve the given title based on the context provided."
        prompt = f"Original title: {original_title}\nContext: {context}\n\nProvide an improved, clear chapter title (keep it under 60 characters):"
        
        result = self._make_request(prompt, system_prompt)
        if result and len(result) <= 60:
            return result
        return original_title
    
    def analyze_book_sentiment(self, highlights: List[str]) -> Dict[str, Any]:
        """Analyze the overall sentiment and tone of book highlights"""
        if not highlights:
            return {"sentiment": "neutral", "confidence": 0}
        
        combined_text = "\n".join(highlights[:10])  # Limit for analysis
        system_prompt = "You are a sentiment analysis expert. Analyze the overall sentiment and tone."
        prompt = f"Analyze the sentiment of these book highlights. Respond with only: positive/negative/neutral and a confidence score 0-1:\n\n{combined_text}"
        
        result = self._make_request(prompt, system_prompt)
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