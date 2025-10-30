import asyncio
import unittest
from pathlib import Path

import cv2
import numpy as np
from babeldoc.docvision.base_doclayout import DocLayoutModel
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

    def test_layout_detect(self):
        layout_det = DocLayoutModel.load_onnx()
        _path = "C:/Users/yuxiang.jiang/Documents/00trans/test_3.jpg"
        image = cv2.imread(_path)
        jpg_ = layout_det.predict(image)[0]

        _save_debug_image(
            image,
            jpg_
        )


def _save_debug_image(image: np.ndarray, layout):
    debug_image = image.copy()
    for box in layout.boxes:
        x0, y0, x1, y1 = box.xyxy
        cv2.rectangle(
            debug_image,
            (int(x0), int(y0)),
            (int(x1), int(y1)),
            (0, 255, 0),
            2,
        )
        # Add text label
        cv2.putText(
            debug_image,
            layout.names[box.cls],
            (int(x0), int(y0) - 5),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 0),
            1,
        )
    img_bgr = cv2.cvtColor(debug_image, cv2.COLOR_RGB2BGR)

    # Save the image
    output_path = "C:/Users/yuxiang.jiang/Documents/00trans/u_test_1.jpg"
    cv2.imwrite(output_path, img_bgr)


if __name__ == '__main__':
    unittest.main()
