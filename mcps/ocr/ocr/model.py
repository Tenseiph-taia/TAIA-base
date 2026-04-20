import threading
import logging
import numpy as np
from paddleocr import PaddleOCR

logger = logging.getLogger("taia-ocr")

_reader = None
_lock = threading.Lock()


def get_reader():
    global _reader
    if _reader is not None:
        return _reader

    with _lock:
        if _reader is not None:
            return _reader

        logger.info("[PaddleOCR] Initializing...")
        _reader = PaddleOCR(
            use_angle_cls=True,
            lang="japan",
            use_gpu=False,
            show_log=False,
            det_limit_side_len=1920,
            rec_batch_num=1,
        )

        # Warm up — forces full model load before returning
        logger.info("[PaddleOCR] Warming up...")
        _reader.ocr(np.zeros((10, 10, 3), dtype=np.uint8), cls=True)

        logger.info("[PaddleOCR] Ready.")
        return _reader