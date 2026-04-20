"""
Image preprocessing for better OCR quality.

KEY INSIGHT: PaddleOCR does NOT need binarized input. It was trained
on grayscale/color images. Binary thresholding DESTROYS CJK characters
by merging thin strokes and eliminating fine detail.

Pipeline:
  1. Grayscale conversion
  2. Gentle denoise (lower strength to preserve strokes)
  3. CLAHE contrast enhancement (moderate clip limit)
  4. Optional: upscale small images for better character recognition
  5. Optional: deskew (only if angle detection is reliable)

Binarization is REMOVED. It was the primary cause of garbled CJK output.
"""

import cv2
import numpy as np
import logging

from .config import ENABLE_PREPROCESSING

logger = logging.getLogger("taia-ocr")


def preprocess_image(img_bytes: bytes) -> bytes:
    """Preprocess image for better OCR results. Returns PNG bytes."""
    if not ENABLE_PREPROCESSING:
        return img_bytes

    try:
        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            logger.warning("cv2.imdecode returned None — image may be corrupt")
            return img_bytes

        h, w = img.shape[:2]
        logger.debug("Input image: %dx%d", w, h)

        # 1. Grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 2. Gentle denoise — h=7 (was 10, too aggressive for CJK thin strokes)
        denoised = cv2.fastNlMeansDenoising(
            gray, None,
            h=7,                # reduced from 10 — preserves thin strokes
            templateWindowSize=7,
            searchWindowSize=21,
        )

        # 3. CLAHE contrast enhancement — clipLimit=1.5 (was 2.0, too aggressive)
        #    Lower clip limit = less amplification of noise in flat regions
        clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8))
        enhanced = clahe.apply(denoised)

        # 4. Upscale small images — PaddleOCR works best at 300+ DPI equivalent
        #    If the image is small (likely low DPI scan), scale up 2x
        min_dimension = min(w, h)
        if min_dimension < 1000:
            scale_factor = 2.0
            enhanced = _upscale(enhanced, scale_factor)
            logger.debug("Upscaled %.1fx (min dim was %dpx)", scale_factor, min_dimension)
        elif min_dimension < 1500:
            scale_factor = 1.5
            enhanced = _upscale(enhanced, scale_factor)
            logger.debug("Upscaled %.1fx (min dim was %dpx)", scale_factor, min_dimension)

        # 5. Deskew — ONLY if angle is confident and small
        enhanced = _deskew(enhanced)

        # Encode back to PNG
        success, buf = cv2.imencode(".png", enhanced)
        if not success:
            logger.warning("cv2.imencode failed")
            return img_bytes

        result_bytes = buf.tobytes()
        logger.debug("Preprocessed image: %d bytes", len(result_bytes))
        return result_bytes

    except Exception:
        logger.error("Preprocessing failed", exc_info=True)
        return img_bytes


def _upscale(gray: np.ndarray, factor: float) -> np.ndarray:
    """
    Upscale a grayscale image using Lanczos interpolation.
    Lanczos preserves sharp edges better than bilinear.
    """
    h, w = gray.shape
    new_w = int(w * factor)
    new_h = int(h * factor)
    return cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)


def _deskew(img: np.ndarray) -> np.ndarray:
    """
    Correct small rotation in scanned documents.
    Uses Hough line transform for more reliable angle detection
    than the contour-based method.
    Only corrects angles < 5° to avoid overcorrecting.
    """
    try:
        # Method 1: Hough lines (more reliable for documents with text lines)
        angle = _detect_angle_hough(img)
        if angle is not None:
            return _rotate(img, angle)

        # Method 2: Fallback to minAreaRect (original method, but more conservative)
        angle = _detect_angle_contour(img)
        if angle is not None:
            return _rotate(img, angle)

        return img

    except Exception:
        logger.debug("Deskew failed", exc_info=True)
        return img


def _detect_angle_hough(img: np.ndarray):
    """
    Detect document angle using Hough line transform.
    More reliable for documents with clear text lines.
    Returns angle in degrees or None.
    """
    try:
        # Edge detection
        edges = cv2.Canny(img, 50, 150, apertureSize=3)

        # Detect lines
        lines = cv2.HoughLinesP(
            edges, rho=1, theta=np.pi / 180,
            threshold=100, minLineLength=100, maxLineGap=10,
        )

        if lines is None or len(lines) < 5:
            return None

        # Compute angles of all detected lines
        angles = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            if x2 - x1 == 0:
                continue
            angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
            # Only consider near-horizontal lines (text lines)
            if abs(angle) < 15:
                angles.append(angle)

        if len(angles) < 3:
            return None

        # Median angle (robust to outliers)
        median_angle = np.median(angles)

        # Only correct small angles — large angles indicate a real tilt
        # that's probably not a scanning artifact
        if abs(median_angle) < 0.3 or abs(median_angle) > 5:
            return None

        logger.debug("Hough deskew angle: %.2f°", median_angle)
        return median_angle

    except Exception:
        return None


def _detect_angle_contour(img: np.ndarray):
    """
    Detect angle using minAreaRect on text contours.
    Fallback method — more conservative than before.
    """
    try:
        coords = np.column_stack(np.where(img > 0))
        if len(coords) < 100:
            return None

        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle

        # More conservative: only correct < 5° (was 15°)
        if abs(angle) < 0.3 or abs(angle) > 5:
            return None

        logger.debug("Contour deskew angle: %.2f°", angle)
        return angle

    except Exception:
        return None


def _rotate(img: np.ndarray, angle: float) -> np.ndarray:
    """Rotate image by given angle, preserving size and filling with white."""
    h, w = img.shape
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)

    # Use white (255) as border value for grayscale
    rotated = cv2.warpAffine(
        img, M, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=255,
    )
    return rotated