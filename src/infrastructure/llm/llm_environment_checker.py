import os
import requests
import logging
from typing import Dict, Any, List
from enum import Enum

logger = logging.getLogger(__name__)


class ServiceMode(Enum):
    """LLM 服務運作模式"""
    DISABLED = "disabled"
    GEMMA_ONLY = "gemma_only"
    OPENAI_ONLY = "openai_only"
    FULL_SERVICE = "full_service"


class LLMEnvironmentChecker:
    """LLM 環境檢查器"""
    
    def __init__(self):
        self.required_env_vars = {
            'gemma': ['GEMMA_API_URL', 'GEMMA_MODEL'],
            'openai': ['OPENAI_API_KEY'],
        }
        
        self.default_values = {
            'GEMMA_API_URL': 'http://localhost:11434/api/generate',
            'GEMMA_MODEL': 'gemma:7b',
            'OPENAI_MODEL': 'gpt-4',
            'SUMMARY_POINTS': '16'
        }
    
    def check_environment_status(self) -> Dict[str, Any]:
        """檢查 LLM 環境設定狀態"""
        status = {
            'gemma_configured': self._check_gemma_env_vars(),
            'openai_configured': self._check_openai_env_vars(),
            'gemma_accessible': False,
            'openai_accessible': False,
            'service_mode': ServiceMode.DISABLED,
            'recommendations': [],
            'config_values': self._get_current_config()
        }
        
        # 測試服務可用性
        if status['gemma_configured']:
            status['gemma_accessible'] = self._test_gemma_connection()
        
        if status['openai_configured']:
            status['openai_accessible'] = self._test_openai_connection()
        
        # 決定服務模式
        status['service_mode'] = self._determine_service_mode(
            status['gemma_accessible'], 
            status['openai_accessible']
        )
        
        # 產生設定建議
        status['recommendations'] = self._generate_recommendations(status)
        
        return status
    
    def _check_gemma_env_vars(self) -> bool:
        """檢查 Gemma 環境變數"""
        for var in self.required_env_vars['gemma']:
            if not os.getenv(var):
                logger.debug(f"Missing environment variable: {var}")
                return False
        return True
    
    def _check_openai_env_vars(self) -> bool:
        """檢查 OpenAI 環境變數"""
        for var in self.required_env_vars['openai']:
            if not os.getenv(var):
                logger.debug(f"Missing environment variable: {var}")
                return False
        return True
    
    def _test_gemma_connection(self) -> bool:
        """測試 Gemma API 連接"""
        try:
            api_url = os.getenv('GEMMA_API_URL')
            model = os.getenv('GEMMA_MODEL')
            
            if not api_url or not model:
                return False
            
            # 簡單的連接測試
            test_payload = {
                "model": model,
                "prompt": "Hello",
                "stream": False,
                "options": {"num_predict": 1}
            }
            
            response = requests.post(
                api_url,
                json=test_payload,
                timeout=10
            )
            
            if response.status_code == 200:
                logger.info("Gemma API connection successful")
                return True
            else:
                logger.warning(f"Gemma API connection failed: {response.status_code}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.warning(f"Gemma API connection test failed: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error testing Gemma connection: {e}")
            return False
    
    def _test_openai_connection(self) -> bool:
        """測試 OpenAI API 連接"""
        try:
            from openai import OpenAI
            
            api_key = os.getenv('OPENAI_API_KEY')
            if not api_key:
                return False
            
            client = OpenAI(api_key=api_key)
            
            # 簡單的連接測試
            response = client.chat.completions.create(
                model=os.getenv('OPENAI_MODEL', 'gpt-3.5-turbo'),
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=1
            )
            
            if response.choices:
                logger.info("OpenAI API connection successful")
                return True
            else:
                logger.warning("OpenAI API connection failed: no response")
                return False
                
        except ImportError:
            logger.warning("OpenAI package not installed")
            return False
        except Exception as e:
            logger.warning(f"OpenAI API connection test failed: {e}")
            return False
    
    def _determine_service_mode(self, gemma_accessible: bool, openai_accessible: bool) -> ServiceMode:
        """根據可用服務決定運作模式"""
        if gemma_accessible and openai_accessible:
            return ServiceMode.FULL_SERVICE
        elif gemma_accessible:
            return ServiceMode.GEMMA_ONLY
        elif openai_accessible:
            return ServiceMode.OPENAI_ONLY
        else:
            return ServiceMode.DISABLED
    
    def _get_current_config(self) -> Dict[str, str]:
        """獲取當前配置值"""
        config = {}
        for key, default in self.default_values.items():
            config[key] = os.getenv(key, default)
        return config
    
    def _generate_recommendations(self, status: Dict[str, Any]) -> List[str]:
        """產生設定建議"""
        recommendations = []
        
        if not status['gemma_configured']:
            recommendations.append("設定 Gemma 環境變數:")
            recommendations.append("  export GEMMA_API_URL=http://localhost:11434/api/generate")
            recommendations.append("  export GEMMA_MODEL=gemma:7b")
        elif status['gemma_configured'] and not status['gemma_accessible']:
            recommendations.append("Gemma 環境變數已設定但無法連接，請檢查:")
            recommendations.append("  1. Ollama 服務是否正在運行")
            recommendations.append("  2. 模型是否已下載 (ollama pull gemma:7b)")
            recommendations.append("  3. API URL 是否正確")
        
        if not status['openai_configured']:
            recommendations.append("設定 OpenAI 環境變數 (可選):")
            recommendations.append("  export OPENAI_API_KEY=your_api_key")
            recommendations.append("  export OPENAI_MODEL=gpt-4")
        elif status['openai_configured'] and not status['openai_accessible']:
            recommendations.append("OpenAI 環境變數已設定但無法連接，請檢查:")
            recommendations.append("  1. API Key 是否有效")
            recommendations.append("  2. 網路連接是否正常")
            recommendations.append("  3. API 配額是否充足")
        
        if status['service_mode'] == ServiceMode.DISABLED:
            recommendations.append("目前 LLM 功能未啟用，基礎書籍同步功能仍可正常使用")
        
        return recommendations
    
    def display_status_report(self, status: Dict[str, Any] = None) -> None:
        """顯示狀態報告"""
        if status is None:
            status = self.check_environment_status()
        
        print("=" * 60)
        print("📊 LLM 服務狀態檢查")
        print("=" * 60)
        
        # 服務狀態
        gemma_status = "✅ 已配置並可連接" if status['gemma_accessible'] else (
            "⚠️  已配置但無法連接" if status['gemma_configured'] else "❌ 未配置"
        )
        openai_status = "✅ 已配置並可連接" if status['openai_accessible'] else (
            "⚠️  已配置但無法連接" if status['openai_configured'] else "❌ 未配置"
        )
        
        print(f"Gemma 本地模型: {gemma_status}")
        print(f"OpenAI API:     {openai_status}")
        print(f"服務模式:       {self._get_service_mode_description(status['service_mode'])}")
        
        # 當前配置
        print("\n📋 當前配置:")
        for key, value in status['config_values'].items():
            masked_value = self._mask_sensitive_value(key, value)
            print(f"  {key}: {masked_value}")
        
        # 建議
        if status['recommendations']:
            print("\n💡 設定建議:")
            for recommendation in status['recommendations']:
                if recommendation.startswith(" "):
                    print(f"    {recommendation}")
                else:
                    print(f"  • {recommendation}")
        
        print("\n" + "=" * 60)
    
    def _get_service_mode_description(self, mode: ServiceMode) -> str:
        """獲取服務模式描述"""
        descriptions = {
            ServiceMode.DISABLED: "❌ 停用 (未設定環境變數)",
            ServiceMode.GEMMA_ONLY: "🟡 僅 Gemma 總結",
            ServiceMode.OPENAI_ONLY: "🔵 僅 OpenAI 總結", 
            ServiceMode.FULL_SERVICE: "🟢 完整服務 (Gemma + OpenAI)"
        }
        return descriptions.get(mode, "未知模式")
    
    def _mask_sensitive_value(self, key: str, value: str) -> str:
        """遮蔽敏感信息"""
        if 'API_KEY' in key and value and len(value) > 8:
            return f"{value[:4]}...{value[-4:]}"
        return value
    
    def is_service_available(self, service_type: str = None) -> bool:
        """檢查特定服務是否可用"""
        status = self.check_environment_status()
        
        if service_type == 'gemma':
            return status['gemma_accessible']
        elif service_type == 'openai':
            return status['openai_accessible']
        else:
            # 檢查是否有任何服務可用
            return status['service_mode'] != ServiceMode.DISABLED
    
    def get_service_mode(self) -> ServiceMode:
        """獲取當前服務模式"""
        status = self.check_environment_status()
        return status['service_mode']