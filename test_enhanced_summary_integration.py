#!/usr/bin/env python3
"""
測試增強總結功能的整合測試
包含各種場景的測試用例
"""

import os
import sys
import logging
from typing import List, Dict

# 添加 src 路徑
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

from infrastructure.llm.llm_environment_checker import LLMEnvironmentChecker, ServiceMode
from infrastructure.llm.enhanced_gemma_service import EnhancedGemmaService
from infrastructure.llm.openai_review_service import OpenAIReviewService
from infrastructure.llm.book_summary_service_factory import BookSummaryServiceFactory


# 設定測試日誌
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class TestDataProvider:
    """測試資料提供者"""
    
    @staticmethod
    def get_test_highlights_short() -> List[str]:
        """短篇測試劃線（適合快速測試）"""
        return [
            "時間管理是成功的關鍵因素之一。",
            "有效的溝通能夠解決大部分的工作問題。",
            "持續學習是個人成長的必要條件。",
            "團隊合作比個人能力更重要。",
            "創新思維能夠帶來突破性的成果。"
        ]
    
    @staticmethod
    def get_test_highlights_medium() -> List[str]:
        """中篇測試劃線（模擬真實書籍）"""
        return [
            "深度工作是在無干擾的狀態下專注進行高認知要求活動的能力。這種能力讓你能夠快速掌握複雜的信息，並在更短時間內產出更好的結果。",
            "網路工具的興起讓人們更容易分心，但也提供了前所未有的連接機會。關鍵在於如何在連接性和專注力之間找到平衡。",
            "要培養深度工作的習慣，需要建立規律的工作節奏。這包括固定的工作時間、專門的工作空間，以及明確的工作目標。",
            "心流狀態是深度工作的理想境界，在這種狀態下，個人完全沈浸在活動中，失去自我意識，時間感也會發生變化。",
            "現代職場的「忙碌文化」往往讓人誤以為忙碌等於生產力，但實際上，深度工作比表面上的忙碌更能創造真正的價值。",
            "社交媒體和即時通訊雖然便利，但會嚴重影響深度思考的能力。需要刻意限制這些工具的使用時間。",
            "培養深度工作的四個策略：哲學方法、節律方法、記者方法和雙峰方法。每個人需要找到最適合自己的方式。",
            "深度工作不僅影響工作效率，也會影響個人的幸福感和成就感。能夠完成有意義的深度工作，本身就是一種獎勵。",
            "學會說「不」是深度工作的重要技能。需要拒絕那些看似重要但實際上會分散注意力的活動和請求。",
            "技術應該為深度工作服務，而不是成為深度工作的障礙。要有意識地選擇和配置工具，最大化其益處。"
        ]
    
    @staticmethod
    def get_test_book_info() -> Dict[str, str]:
        """測試書籍資訊"""
        return {
            "title": "深度工作力：淺薄時代，個人成功的關鍵能力",
            "author": "卡爾・紐波特"
        }


class EnhancedSummaryIntegrationTester:
    """增強總結整合測試器"""
    
    def __init__(self):
        self.env_checker = LLMEnvironmentChecker()
        self.factory = BookSummaryServiceFactory()
        self.test_results = []
    
    def run_all_tests(self):
        """執行所有測試"""
        print("🚀 開始增強總結功能整合測試")
        print("=" * 60)
        
        # 1. 環境檢查測試
        self.test_environment_checker()
        
        # 2. 服務工廠測試
        self.test_service_factory()
        
        # 3. Gemma 服務測試（如果可用）
        if self.env_checker.is_service_available('gemma'):
            self.test_gemma_service()
        
        # 4. OpenAI 服務測試（如果可用）
        if self.env_checker.is_service_available('openai'):
            self.test_openai_service()
        
        # 5. 完整流程測試
        self.test_full_integration()
        
        # 6. 錯誤處理測試
        self.test_error_handling()
        
        # 顯示測試總結
        self.display_test_summary()
    
    def test_environment_checker(self):
        """測試環境檢查器"""
        print("\n🔍 測試環境檢查器...")
        
        try:
            # 檢查環境狀態
            status = self.env_checker.check_environment_status()
            
            assert isinstance(status, dict), "環境狀態應該返回字典"
            assert 'service_mode' in status, "狀態中應包含服務模式"
            assert isinstance(status['service_mode'], ServiceMode), "服務模式應為 ServiceMode 枚舉"
            
            print("✅ 環境檢查器測試通過")
            self.test_results.append(("環境檢查器", True, None))
            
            # 顯示當前狀態
            print(f"   當前服務模式: {status['service_mode'].value}")
            print(f"   Gemma 可用: {status['gemma_accessible']}")
            print(f"   OpenAI 可用: {status['openai_accessible']}")
            
        except Exception as e:
            print(f"❌ 環境檢查器測試失敗: {e}")
            self.test_results.append(("環境檢查器", False, str(e)))
    
    def test_service_factory(self):
        """測試服務工廠"""
        print("\n🏭 測試服務工廠...")
        
        try:
            # 檢查工廠初始化
            assert self.factory is not None, "服務工廠應該成功初始化"
            
            # 檢查狀態獲取
            status = self.factory.get_service_status()
            assert isinstance(status, dict), "工廠狀態應返回字典"
            
            # 檢查服務可用性
            is_available = self.factory.is_service_available()
            assert isinstance(is_available, bool), "服務可用性應返回布林值"
            
            print("✅ 服務工廠測試通過")
            self.test_results.append(("服務工廠", True, None))
            
        except Exception as e:
            print(f"❌ 服務工廠測試失敗: {e}")
            self.test_results.append(("服務工廠", False, str(e)))
    
    def test_gemma_service(self):
        """測試 Gemma 服務"""
        print("\n🤖 測試 Gemma 服務...")
        
        try:
            gemma_service = EnhancedGemmaService()
            
            # 檢查服務可用性
            if not gemma_service.is_available():
                print("⚠️  Gemma 服務不可用，跳過測試")
                self.test_results.append(("Gemma服務", False, "服務不可用"))
                return
            
            # 測試總結生成
            book_info = TestDataProvider.get_test_book_info()
            test_highlights = TestDataProvider.get_test_highlights_short()
            
            result = gemma_service.generate_book_summary(
                book_info["title"], 
                book_info["author"], 
                test_highlights
            )
            
            # 驗證結果
            assert result is not None, "總結結果不應為空"
            assert hasattr(result, 'generation_success'), "結果應包含成功狀態"
            
            if result.generation_success:
                assert len(result.summary_points) > 0, "成功時應有總結重點"
                print(f"   生成重點數: {len(result.summary_points)}")
                print("✅ Gemma 服務測試通過")
                self.test_results.append(("Gemma服務", True, None))
            else:
                print(f"⚠️  Gemma 總結生成失敗: {result.error_message}")
                self.test_results.append(("Gemma服務", False, result.error_message))
            
        except Exception as e:
            print(f"❌ Gemma 服務測試失敗: {e}")
            self.test_results.append(("Gemma服務", False, str(e)))
    
    def test_openai_service(self):
        """測試 OpenAI 服務"""
        print("\n🌐 測試 OpenAI 服務...")
        
        try:
            openai_service = OpenAIReviewService()
            
            # 檢查服務可用性
            if not openai_service.is_available():
                print("⚠️  OpenAI 服務不可用，跳過測試")
                self.test_results.append(("OpenAI服務", False, "服務不可用"))
                return
            
            print("✅ OpenAI 服務可用")
            self.test_results.append(("OpenAI服務", True, None))
            
        except Exception as e:
            print(f"❌ OpenAI 服務測試失敗: {e}")
            self.test_results.append(("OpenAI服務", False, str(e)))
    
    def test_full_integration(self):
        """測試完整整合流程"""
        print("\n🔄 測試完整整合流程...")
        
        try:
            # 獲取測試資料
            book_info = TestDataProvider.get_test_book_info()
            test_highlights = TestDataProvider.get_test_highlights_medium()
            
            # 執行完整處理流程
            result = self.factory.process_book_summary(
                book_info["title"],
                book_info["author"], 
                test_highlights
            )
            
            # 驗證結果
            assert result is not None, "處理結果不應為空"
            assert hasattr(result, 'success'), "結果應包含成功狀態"
            assert hasattr(result, 'service_mode_used'), "結果應包含使用的服務模式"
            
            print(f"   使用服務模式: {result.service_mode_used.value}")
            print(f"   處理狀態: {'✅ 成功' if result.success else '❌ 失敗'}")
            
            if result.success:
                print(f"   最終總結重點數: {len(result.final_summary.summary_points) if result.final_summary else 0}")
                
            if result.processing_time:
                print(f"   處理時間: {result.processing_time:.2f} 秒")
            
            # 顯示部分結果
            if result.success and result.final_summary and result.final_summary.summary_points:
                print("\n   前3個總結重點預覽:")
                for i, point in enumerate(result.final_summary.summary_points[:3], 1):
                    print(f"   {i}. 【{point.title}】{point.description[:30]}...")
            
            print("✅ 完整整合流程測試通過")
            self.test_results.append(("完整整合", True, None))
            
        except Exception as e:
            print(f"❌ 完整整合流程測試失敗: {e}")
            self.test_results.append(("完整整合", False, str(e)))
    
    def test_error_handling(self):
        """測試錯誤處理"""
        print("\n🚨 測試錯誤處理...")
        
        try:
            # 測試空劃線內容
            result = self.factory.process_book_summary(
                "測試書籍", "測試作者", []
            )
            
            # 應該優雅地處理空劃線
            assert result is not None, "空劃線應返回結果對象"
            
            # 測試異常長的劃線
            very_long_highlights = ["很長的劃線內容 " * 1000] * 10
            result = self.factory.process_book_summary(
                "測試書籍", "測試作者", very_long_highlights
            )
            
            assert result is not None, "長劃線應返回結果對象"
            
            print("✅ 錯誤處理測試通過")
            self.test_results.append(("錯誤處理", True, None))
            
        except Exception as e:
            print(f"❌ 錯誤處理測試失敗: {e}")
            self.test_results.append(("錯誤處理", False, str(e)))
    
    def display_test_summary(self):
        """顯示測試總結"""
        print("\n" + "=" * 60)
        print("📊 測試結果總結")
        print("=" * 60)
        
        total_tests = len(self.test_results)
        passed_tests = sum(1 for _, success, _ in self.test_results if success)
        failed_tests = total_tests - passed_tests
        
        print(f"📈 測試統計:")
        print(f"   總測試數: {total_tests}")
        print(f"   通過: {passed_tests} ✅")
        print(f"   失敗: {failed_tests} ❌")
        print(f"   成功率: {(passed_tests/total_tests*100) if total_tests > 0 else 0:.1f}%")
        
        print(f"\n📋 詳細結果:")
        for test_name, success, error in self.test_results:
            status = "✅ 通過" if success else "❌ 失敗"
            print(f"   {test_name:12} | {status}")
            if not success and error:
                print(f"                   錯誤: {error}")
        
        # 給出建議
        if failed_tests > 0:
            print(f"\n💡 改進建議:")
            if not self.env_checker.is_service_available():
                print("   • 設定 LLM 環境變數以啟用總結功能")
                print("   • 使用 llm_status_checker.py --setup 查看設定指南")
            
            failed_services = [name for name, success, _ in self.test_results if not success]
            if "Gemma服務" in failed_services:
                print("   • 檢查 Ollama 服務是否正在運行")
                print("   • 確認 Gemma 模型是否已下載")
            
            if "OpenAI服務" in failed_services:
                print("   • 檢查 OpenAI API Key 是否有效")
                print("   • 確認網路連接和 API 配額")
        else:
            print(f"\n🎉 所有測試通過！系統運行正常。")


def main():
    """主程式"""
    if len(sys.argv) > 1 and sys.argv[1] == "--quick":
        print("🚀 快速整合測試")
        
        # 快速檢查
        env_checker = LLMEnvironmentChecker()
        status = env_checker.check_environment_status()
        
        print(f"服務模式: {status['service_mode'].value}")
        print(f"Gemma: {'✅' if status['gemma_accessible'] else '❌'}")
        print(f"OpenAI: {'✅' if status['openai_accessible'] else '❌'}")
        
        if status['service_mode'] != ServiceMode.DISABLED:
            print("執行簡單功能測試...")
            factory = BookSummaryServiceFactory()
            result = factory.process_book_summary(
                "測試", "作者", ["測試劃線內容"]
            )
            print(f"功能測試: {'✅ 通過' if result.success else '❌ 失敗'}")
    else:
        # 完整測試
        tester = EnhancedSummaryIntegrationTester()
        tester.run_all_tests()


if __name__ == "__main__":
    main()