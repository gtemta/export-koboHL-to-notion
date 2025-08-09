import unittest
from src.domain.services.chapter_extractor import (
    ChapterExtractor, 
    TextContentExtractor, 
    ContentIdExtractor,
    ContainerPathExtractor
)


class TestTextContentExtractor(unittest.TestCase):
    def setUp(self):
        self.extractor = TextContentExtractor()
    
    def test_chinese_chapter_extraction(self):
        """測試中文章節標題提取"""
        data = {'text': '第一章：開始的地方'}
        result = self.extractor.extract(data)
        self.assertEqual(result, '第一章：開始的地方')
    
    def test_english_chapter_extraction(self):
        """測試英文章節標題提取"""  
        data = {'text': 'Chapter 1: The Beginning'}
        result = self.extractor.extract(data)
        self.assertEqual(result, 'Chapter 1: The Beginning')
    
    def test_numbered_chapter_extraction(self):
        """測試數字章節標題提取"""
        data = {'text': '1. 序言'}
        result = self.extractor.extract(data)
        self.assertEqual(result, '1. 序言')
    
    def test_long_text_rejection(self):
        """測試長文本拒絕提取"""
        long_text = "這是一段很長的文本" * 20
        data = {'text': long_text}
        result = self.extractor.extract(data)
        self.assertIsNone(result)
    
    def test_empty_text_rejection(self):
        """測試空文本處理"""
        data = {'text': ''}
        result = self.extractor.extract(data)
        self.assertIsNone(result)


class TestContentIdExtractor(unittest.TestCase):
    def setUp(self):
        self.extractor = ContentIdExtractor()
    
    def test_section_optimization(self):
        """測試Section格式優化"""
        data = {'content_id': 'book!OEBPS!Text/Section0008.xhtml'}
        result = self.extractor.extract(data)
        self.assertEqual(result, '第8章')
    
    def test_large_section_optimization(self):
        """測試大數字Section格式優化"""
        data = {'content_id': 'book!OEBPS!Text/Section0015.xhtml'}
        result = self.extractor.extract(data)
        self.assertEqual(result, '章節15')
    
    def test_regular_file_extraction(self):
        """測試普通文件名提取"""
        data = {'content_id': 'book!OEBPS!Text/prologue.xhtml'}
        result = self.extractor.extract(data)
        self.assertEqual(result, 'prologue')
    
    def test_item_xhtml_format(self):
        """測試item!xhtml格式"""
        data = {'content_id': 'book!item!xhtml/chapter01.xhtml'}
        result = self.extractor.extract(data)
        self.assertEqual(result, 'chapter01')


class TestContainerPathExtractor(unittest.TestCase):
    def setUp(self):
        self.extractor = ContainerPathExtractor()
    
    def test_container_path_extraction(self):
        """測試從容器路徑提取"""
        data = {'start_container_path': 'OEBPS/Text/chapter02.xhtml#kobo.1.1'}
        result = self.extractor.extract(data)
        self.assertEqual(result, 'chapter02')


class TestChapterExtractor(unittest.TestCase):
    def setUp(self):
        self.extractor = ChapterExtractor()
    
    def test_text_content_priority(self):
        """測試文本內容提取優先級最高"""
        data = {
            'text': '第一章：開始',
            'content_id': 'book!OEBPS!Text/Section0008.xhtml',
            'start_container_path': 'OEBPS/Text/chapter02.xhtml'
        }
        result = self.extractor.extract_chapter_name(data)
        self.assertEqual(result, '第一章：開始')
    
    def test_content_id_fallback(self):
        """測試ContentID作為備選方案"""
        data = {
            'text': '這是一段普通的高亮內容，不是章節標題',
            'content_id': 'book!OEBPS!Text/Section0008.xhtml'
        }
        result = self.extractor.extract_chapter_name(data)
        self.assertEqual(result, '第8章')
    
    def test_unknown_chapter_fallback(self):
        """測試未知章節備選"""
        data = {
            'text': '無法識別的內容',
            'content_id': 'invalid_format'
        }
        result = self.extractor.extract_chapter_name(data)
        self.assertEqual(result, '未知章節')


if __name__ == '__main__':
    unittest.main()