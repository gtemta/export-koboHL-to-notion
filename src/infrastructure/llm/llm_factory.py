from typing import Optional, Dict, Any
from .base_llm import BaseLLM
from .ollama_client import OllamaClient
from .openai_client import OpenAIClient
import logging
import os

logger = logging.getLogger(__name__)


class LLMFactory:
    """Factory class for creating LLM instances"""
    
    @staticmethod
    def create_llm(llm_type: str, **kwargs) -> Optional[BaseLLM]:
        """
        Create an LLM instance based on type
        
        Args:
            llm_type: Type of LLM ('ollama', 'openai', 'openai-local')
            **kwargs: Additional configuration parameters
            
        Returns:
            BaseLLM instance or None if creation fails
        """
        try:
            if llm_type.lower() == 'ollama':
                return LLMFactory._create_ollama(**kwargs)
            elif llm_type.lower() == 'openai':
                return LLMFactory._create_openai(**kwargs)
            elif llm_type.lower() == 'openai-local':
                return LLMFactory._create_openai_local(**kwargs)
            else:
                logger.error(f"Unknown LLM type: {llm_type}")
                return None
                
        except Exception as e:
            logger.error(f"Failed to create LLM of type {llm_type}: {e}")
            return None
    
    @staticmethod
    def _create_ollama(**kwargs) -> OllamaClient:
        """Create Ollama client"""
        model_name = kwargs.get('model_name', 'llama3.2')
        host = kwargs.get('host', 'http://localhost:11434')
        return OllamaClient(model_name=model_name, host=host, **kwargs)
    
    @staticmethod
    def _create_openai(**kwargs) -> OpenAIClient:
        """Create OpenAI client"""
        model_name = kwargs.get('model_name', 'gpt-3.5-turbo')
        api_key = kwargs.get('api_key') or os.getenv("OPENAI_API_KEY")
        return OpenAIClient(model_name=model_name, api_key=api_key, **kwargs)
    
    @staticmethod
    def _create_openai_local(**kwargs) -> OpenAIClient:
        """Create OpenAI-compatible local client (e.g., text-generation-webui)"""
        model_name = kwargs.get('model_name', 'local-model')
        api_key = kwargs.get('api_key', 'dummy-key')  # Some local APIs need a dummy key
        base_url = kwargs.get('base_url', 'http://localhost:5000/v1')
        return OpenAIClient(model_name=model_name, api_key=api_key, base_url=base_url, **kwargs)
    
    @staticmethod
    def get_available_llms() -> Dict[str, bool]:
        """Check which LLM services are available"""
        availability = {}
        
        # Check Ollama
        try:
            ollama_client = LLMFactory.create_llm('ollama')
            availability['ollama'] = ollama_client.is_available() if ollama_client else False
        except Exception:
            availability['ollama'] = False
        
        # Check OpenAI
        try:
            openai_client = LLMFactory.create_llm('openai')
            availability['openai'] = openai_client.is_available() if openai_client else False
        except Exception:
            availability['openai'] = False
        
        # Check local OpenAI-compatible
        try:
            local_client = LLMFactory.create_llm('openai-local')
            availability['openai-local'] = local_client.is_available() if local_client else False
        except Exception:
            availability['openai-local'] = False
        
        return availability
    
    @staticmethod
    def get_best_available_llm(**kwargs) -> Optional[BaseLLM]:
        """Get the best available LLM based on priority order"""
        priority_order = ['ollama', 'openai-local', 'openai']
        
        for llm_type in priority_order:
            try:
                llm = LLMFactory.create_llm(llm_type, **kwargs)
                if llm and llm.is_available():
                    logger.info(f"Using {llm_type} as LLM provider")
                    return llm
            except Exception as e:
                logger.debug(f"Failed to create {llm_type}: {e}")
                continue
        
        logger.warning("No LLM services available")
        return None