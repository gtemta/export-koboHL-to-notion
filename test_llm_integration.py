#!/usr/bin/env python3
"""
Test script for LLM integration functionality
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.infrastructure.llm.llm_factory import LLMFactory
from src.application.use_cases.llm_enhanced_sync_use_case import LLMEnhancedSyncUseCase
from llm_config import get_llm_config, load_config_from_env
import DBReader
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_llm_availability():
    """Test which LLM services are available"""
    print("=== Testing LLM Service Availability ===")
    
    availability = LLMFactory.get_available_llms()
    
    for service, available in availability.items():
        status = "✅ Available" if available else "❌ Not Available"
        print(f"{service}: {status}")
    
    return availability

def test_ollama_basic():
    """Test basic Ollama functionality"""
    print("\n=== Testing Ollama Basic Functionality ===")
    
    try:
        ollama = LLMFactory.create_llm('ollama', model_name='llama3.2')
        
        if not ollama or not ollama.is_available():
            print("❌ Ollama not available")
            return False
        
        # Test summary generation
        test_text = "This is a test text about artificial intelligence and machine learning. It discusses various concepts and applications in the field of AI."
        summary = ollama.generate_summary(test_text, max_length=30)
        print(f"Summary: {summary}")
        
        # Test theme extraction
        highlights = [
            "Artificial intelligence is transforming industries",
            "Machine learning algorithms improve with data",
            "Deep learning requires significant computational power"
        ]
        themes = ollama.extract_themes(highlights)
        print(f"Themes: {themes}")
        
        print("✅ Ollama basic test passed")
        return True
        
    except Exception as e:
        print(f"❌ Ollama test failed: {e}")
        return False

def test_enhanced_sync():
    """Test LLM-enhanced sync functionality"""
    print("\n=== Testing LLM-Enhanced Sync ===")
    
    try:
        # Load configuration
        config = load_config_from_env()
        if not config:
            config = get_llm_config('ollama')
        
        if not config:
            print("❌ No LLM configuration available")
            return False
        
        # Initialize enhanced sync
        enhanced_sync = LLMEnhancedSyncUseCase(llm_config=config)
        
        # Check LLM status
        status = enhanced_sync.get_llm_status()
        print(f"LLM Status: {status}")
        
        if not status['llm_available']:
            print("❌ No LLM available for enhanced sync")
            return False
        
        # Get a test book
        books = DBReader.getBookInfoFromDB()
        if not books:
            print("❌ No books found in database")
            return False
        
        # Test with first book
        test_book = books[0]
        print(f"Testing with book: {test_book.get_title()}")
        
        enhanced_data = enhanced_sync.enhance_book_highlights(test_book.get_id())
        
        print(f"Enhanced data keys: {list(enhanced_data.keys())}")
        
        if enhanced_data.get('llm_insights'):
            insights = enhanced_data['llm_insights']
            print(f"Book insights: {insights}")
        
        if enhanced_data.get('enhanced_chapters'):
            print(f"Enhanced chapters count: {len(enhanced_data['enhanced_chapters'])}")
            for i, chapter in enumerate(enhanced_data['enhanced_chapters'][:3]):  # Show first 3
                print(f"  Chapter {i+1}:")
                print(f"    Original: {chapter['original_title']}")
                print(f"    Enhanced: {chapter['enhanced_title']}")
                print(f"    Summary: {chapter['summary'][:100]}..." if chapter['summary'] else "    Summary: None")
        
        print("✅ Enhanced sync test completed")
        return True
        
    except Exception as e:
        print(f"❌ Enhanced sync test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_configuration():
    """Test configuration loading"""
    print("\n=== Testing Configuration ===")
    
    # Test default configs
    for provider in ['ollama', 'openai', 'openai_local']:
        config = get_llm_config(provider)
        print(f"{provider} config: {config}")
    
    # Test environment config
    env_config = load_config_from_env()
    print(f"Environment config: {env_config}")
    
    print("✅ Configuration test completed")

def main():
    """Run all tests"""
    print("🚀 Starting LLM Integration Tests\n")
    
    # Test availability
    availability = test_llm_availability()
    
    # Test configuration
    test_configuration()
    
    # Test Ollama if available
    if availability.get('ollama', False):
        test_ollama_basic()
    else:
        print("\n⚠️  Skipping Ollama tests - service not available")
        print("   To test Ollama:")
        print("   1. Install Ollama: https://ollama.ai")
        print("   2. Run: ollama pull llama3.2")
        print("   3. Start Ollama service")
    
    # Test enhanced sync
    test_enhanced_sync()
    
    print("\n🏁 LLM Integration Tests Complete")
    print("\nNext steps:")
    print("1. Install and configure your preferred LLM service")
    print("2. Set environment variables (see llm_config.py)")
    print("3. Run: python uploadToNotion.py (with LLM enhancements)")

if __name__ == "__main__":
    main()