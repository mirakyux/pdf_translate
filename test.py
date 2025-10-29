import asyncio
import unittest

from rapidocr import RapidOCR, OCRVersion

from main import TranslationRequest, start_translation


class MyTestCase(unittest.TestCase):
    def test_translate(self):
        request = TranslationRequest(file_id="test",
                                     lang_in="en",
                                     lang_out="zh",
                                     qps=1,
                                     model="gpt-4o-mini",
                                     debug=False,
                                     glossary_ids=[])
        asyncio.run(start_translation(request))
    def test_rapid(self):
        rapidocr = RapidOCR(params={
            "Det.ocr_version": OCRVersion.PPOCRV5,
            "Cls.ocr_version": OCRVersion.PPOCRV4,
            "Rec.ocr_version": OCRVersion.PPOCRV5,
        })
        result = rapidocr("C:/Users/yuxiang.jiang/Documents/00trans/tttt1.png")
        result.vis("C:/Users/yuxiang.jiang/Documents/00trans/u_tttt1.png")


if __name__ == '__main__':
    unittest.main()
