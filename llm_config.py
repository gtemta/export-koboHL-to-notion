"""
Configuration file for LLM integration settings
"""
import os
from typing import Dict, Any, Optional

# Default LLM configurations
LLM_CONFIGS = {
    'ollama': {
        'type': 'ollama',
        'model_name': 'llama3.2',  # or 'qwen2.5', 'mistral', etc.
        'host': 'http://localhost:11434',
        'timeout': 30
    },
    
    'openai': {
        'type': 'openai',
        'model_name': 'gpt-3.5-turbo',
        'api_key': os.getenv('OPENAI_API_KEY')
    },
    
    'openai_local': {
        'type': 'openai-local',
        'model_name': 'local-model',
        'api_key': 'dummy-key',
        'base_url': 'http://localhost:5000/v1'  # text-generation-webui default
    }
}

# Feature flags for LLM functionality
LLM_FEATURES = {
    'enhance_chapter_titles': True,
    'generate_chapter_summaries': True,
    'extract_themes': True,
    'sentiment_analysis': True,
    'book_insights': True
}

def get_llm_config(provider: str = 'auto') -> Optional[Dict[str, Any]]:
    """
    Get LLM configuration for specified provider
    
    Args:
        provider: LLM provider name ('ollama', 'openai', 'openai_local', 'auto')
        
    Returns:
        Configuration dict or None
    """
    if provider == 'auto':
        return {'type': 'auto'}
    
    return LLM_CONFIGS.get(provider)

def is_feature_enabled(feature: str) -> bool:
    """Check if a specific LLM feature is enabled"""
    return LLM_FEATURES.get(feature, False)

# Environment variable overrides
def load_config_from_env() -> Dict[str, Any]:
    """Load LLM configuration from environment variables"""
    config = {}
    
    # LLM provider selection
    llm_provider = os.getenv('LLM_PROVIDER', 'auto')
    config['type'] = llm_provider
    
    # Ollama specific settings
    if llm_provider == 'ollama':
        config.update({
            'model_name': os.getenv('OLLAMA_MODEL', 'llama3.2'),
            'host': os.getenv('OLLAMA_HOST', 'http://localhost:11434'),
            'timeout': int(os.getenv('OLLAMA_TIMEOUT', '30'))
        })
    
    # OpenAI specific settings
    elif llm_provider == 'openai':
        config.update({
            'model_name': os.getenv('OPENAI_MODEL', 'gpt-3.5-turbo'),
            'api_key': os.getenv('OPENAI_API_KEY')
        })
    
    # Local OpenAI-compatible API settings
    elif llm_provider == 'openai-local':
        config.update({
            'model_name': os.getenv('LOCAL_MODEL_NAME', 'local-model'),
            'base_url': os.getenv('LOCAL_API_URL', 'http://localhost:5000/v1'),
            'api_key': os.getenv('LOCAL_API_KEY', 'dummy-key')
        })
    
    return config

# Usage example:
# 1. Set environment variable: export LLM_PROVIDER=ollama
# 2. Or use default config: config = get_llm_config('ollama')
# 3. Initialize: llm_sync = LLMEnhancedSyncUseCase(llm_config=config)