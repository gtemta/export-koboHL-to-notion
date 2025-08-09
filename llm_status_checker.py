#!/usr/bin/env python3
"""
LLM 服務狀態檢查工具
獨立的診斷工具，幫助用戶檢查和配置 LLM 環境
"""

import os
import sys
from typing import Dict, Any

# 添加 src 路徑
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

from infrastructure.llm.llm_environment_checker import LLMEnvironmentChecker, ServiceMode


def display_banner():
    """顯示工具橫幅"""
    print("=" * 70)
    print("🔍 LLM 服務狀態檢查工具")
    print("檢查 Gemma 本地模型和 OpenAI API 的配置狀態")
    print("=" * 70)


def check_system_requirements():
    """檢查系統需求"""
    print("\n📋 系統需求檢查:")
    
    # 檢查 Python 版本
    python_version = sys.version_info
    if python_version >= (3, 8):
        print(f"✅ Python 版本: {python_version.major}.{python_version.minor}.{python_version.micro}")
    else:
        print(f"❌ Python 版本過舊: {python_version.major}.{python_version.minor}.{python_version.micro}")
        print("   需要 Python 3.8 或更新版本")
    
    # 檢查必要套件
    required_packages = ['requests', 'openai']
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package)
            print(f"✅ {package} 套件已安裝")
        except ImportError:
            print(f"❌ {package} 套件未安裝")
            missing_packages.append(package)
    
    if missing_packages:
        print(f"\n💡 安裝缺失套件: pip install {' '.join(missing_packages)}")


def detailed_service_check():
    """詳細服務檢查"""
    env_checker = LLMEnvironmentChecker()
    status = env_checker.check_environment_status()
    
    print("\n🔍 詳細服務檢查:")
    
    # Gemma 服務檢查
    print("\n🤖 Gemma 本地模型:")
    gemma_url = os.getenv('GEMMA_API_URL', '未設定')
    gemma_model = os.getenv('GEMMA_MODEL', '未設定')
    
    print(f"  API URL: {gemma_url}")
    print(f"  模型名稱: {gemma_model}")
    print(f"  環境變數設定: {'✅' if status['gemma_configured'] else '❌'}")
    print(f"  服務連接: {'✅' if status['gemma_accessible'] else '❌'}")
    
    if status['gemma_configured'] and not status['gemma_accessible']:
        print("  📝 可能的問題:")
        print("    • Ollama 服務未運行")
        print("    • 模型未下載 (使用: ollama pull gemma:7b)")
        print("    • API URL 不正確")
        print("    • 網路連接問題")
    
    # OpenAI 服務檢查
    print("\n🌐 OpenAI API:")
    openai_key = os.getenv('OPENAI_API_KEY', '未設定')
    openai_model = os.getenv('OPENAI_MODEL', '未設定')
    
    if openai_key != '未設定':
        masked_key = f"{openai_key[:8]}...{openai_key[-4:]}" if len(openai_key) > 12 else "****"
        print(f"  API Key: {masked_key}")
    else:
        print(f"  API Key: {openai_key}")
    
    print(f"  模型名稱: {openai_model}")
    print(f"  環境變數設定: {'✅' if status['openai_configured'] else '❌'}")
    print(f"  服務連接: {'✅' if status['openai_accessible'] else '❌'}")
    
    if status['openai_configured'] and not status['openai_accessible']:
        print("  📝 可能的問題:")
        print("    • API Key 無效或過期")
        print("    • 網路連接問題")
        print("    • API 配額不足")
        print("    • 模型名稱不正確")


def show_service_modes():
    """顯示服務模式說明"""
    print("\n🔧 服務模式說明:")
    
    modes = {
        ServiceMode.DISABLED: {
            "name": "停用模式",
            "icon": "❌",
            "condition": "未設定任何 LLM 環境變數",
            "behavior": "跳過 LLM 功能，僅執行基礎書籍同步",
            "use_case": "不需要總結功能，或暫時停用 LLM 服務"
        },
        ServiceMode.GEMMA_ONLY: {
            "name": "Gemma 本地模式", 
            "icon": "🟡",
            "condition": "僅設定 GEMMA_* 環境變數",
            "behavior": "使用 Gemma 生成 16 重點總結",
            "use_case": "本地運算，隱私保護，無需網路"
        },
        ServiceMode.OPENAI_ONLY: {
            "name": "OpenAI 雲端模式",
            "icon": "🔵", 
            "condition": "僅設定 OPENAI_* 環境變數",
            "behavior": "使用 OpenAI 直接生成總結",
            "use_case": "快速設定，高品質結果"
        },
        ServiceMode.FULL_SERVICE: {
            "name": "雙模型協作模式",
            "icon": "🟢",
            "condition": "同時設定 Gemma 和 OpenAI 環境變數",
            "behavior": "Gemma 初始總結 + OpenAI 審核改進",
            "use_case": "最高品質，結合本地和雲端優勢"
        }
    }
    
    for mode, info in modes.items():
        print(f"\n{info['icon']} {info['name']}")
        print(f"  條件: {info['condition']}")
        print(f"  行為: {info['behavior']}")
        print(f"  適用: {info['use_case']}")


def show_quick_setup():
    """顯示快速設定指南"""
    print("\n🚀 快速設定指南:")
    
    print("\n方案一: 僅使用 Gemma 本地模型 (推薦)")
    print("1. 安裝 Ollama:")
    print("   • macOS: brew install ollama")
    print("   • Linux: curl -fsSL https://ollama.ai/install.sh | sh")
    print("   • Windows: 下載安裝包 https://ollama.ai")
    print("")
    print("2. 下載和啟動模型:")
    print("   ollama pull gemma:7b")
    print("   ollama serve")
    print("")
    print("3. 設定環境變數:")
    print("   export GEMMA_API_URL=http://localhost:11434/api/generate")
    print("   export GEMMA_MODEL=gemma:7b")
    
    print("\n方案二: 使用 OpenAI API")
    print("1. 獲取 API Key: https://platform.openai.com/api-keys")
    print("2. 設定環境變數:")
    print("   export OPENAI_API_KEY=your_api_key_here")
    print("   export OPENAI_MODEL=gpt-4")
    
    print("\n方案三: 雙模型協作 (最佳效果)")
    print("1. 同時完成方案一和方案二的設定")
    print("2. 系統將自動使用雙模型協作模式")
    
    print("\n💾 持久化設定 (推薦):")
    print("將環境變數加入 ~/.bashrc 或 ~/.zshrc:")
    print("echo 'export GEMMA_API_URL=http://localhost:11434/api/generate' >> ~/.bashrc")
    print("echo 'export GEMMA_MODEL=gemma:7b' >> ~/.bashrc")


def test_integration():
    """測試整合功能"""
    print("\n🧪 整合功能測試:")
    
    try:
        from infrastructure.llm.book_summary_service_factory import BookSummaryServiceFactory
        
        # 初始化服務工廠
        factory = BookSummaryServiceFactory()
        
        # 檢查服務可用性
        if factory.is_service_available():
            print("✅ 服務工廠初始化成功")
            
            # 獲取服務狀態
            status = factory.get_service_status()
            service_mode = status['service_mode']
            
            print(f"✅ 當前服務模式: {service_mode.value}")
            
            # 測試基礎功能
            print("🔄 測試基礎功能...")
            
            # 模擬測試資料
            test_title = "測試書籍"
            test_author = "測試作者"
            test_highlights = [
                "這是第一條測試劃線內容，用來測試總結功能是否正常運作。",
                "這是第二條測試劃線內容，包含了一些重要的概念和想法。",
                "第三條測試內容展示了作者的核心觀點和理念。"
            ]
            
            # 執行測試
            result = factory.process_book_summary(test_title, test_author, test_highlights)
            
            if result.success:
                print("✅ 總結功能測試成功")
                print(f"📊 使用模式: {result.service_mode_used.value}")
                if result.final_summary:
                    print(f"📝 生成重點數: {len(result.final_summary.summary_points)}")
            else:
                print("❌ 總結功能測試失敗")
                print(f"錯誤: {result.error_message}")
            
        else:
            print("❌ LLM 服務不可用")
            
    except Exception as e:
        print(f"❌ 整合測試失敗: {e}")


def interactive_checker():
    """互動式檢查器"""
    while True:
        print("\n" + "="*50)
        print("🔍 LLM 服務檢查選單")
        print("="*50)
        print("1. 完整狀態檢查")
        print("2. 系統需求檢查") 
        print("3. 詳細服務檢查")
        print("4. 服務模式說明")
        print("5. 快速設定指南")
        print("6. 整合功能測試")
        print("0. 退出")
        print("="*50)
        
        choice = input("請選擇檢查項目 (0-6): ").strip()
        
        if choice == "0":
            print("👋 檢查完成，再見！")
            break
        elif choice == "1":
            check_system_requirements()
            detailed_service_check()
            show_service_modes()
            env_checker = LLMEnvironmentChecker()
            env_checker.display_status_report()
        elif choice == "2":
            check_system_requirements()
        elif choice == "3":
            detailed_service_check()
        elif choice == "4":
            show_service_modes()
        elif choice == "5":
            show_quick_setup()
        elif choice == "6":
            test_integration()
        else:
            print("❌ 無效選項，請重新選擇")


def main():
    """主程式"""
    display_banner()
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "--quick":
            check_system_requirements()
            detailed_service_check()
            env_checker = LLMEnvironmentChecker()
            env_checker.display_status_report()
        elif sys.argv[1] == "--setup":
            show_quick_setup()
        elif sys.argv[1] == "--test":
            test_integration()
        elif sys.argv[1] == "--help":
            print("\n用法:")
            print("  python llm_status_checker.py           # 互動式檢查")
            print("  python llm_status_checker.py --quick   # 快速狀態檢查")
            print("  python llm_status_checker.py --setup   # 顯示設定指南")
            print("  python llm_status_checker.py --test    # 執行整合測試")
        else:
            print("❌ 未知參數，使用 --help 查看用法")
    else:
        interactive_checker()


if __name__ == "__main__":
    main()