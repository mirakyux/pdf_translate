import asyncio
import unittest

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


if __name__ == '__main__':
    unittest.main()
