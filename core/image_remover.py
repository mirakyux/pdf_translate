#!/usr/bin/env python
# -*- coding: UTF-8 -*-
import logging
from typing import Optional, List, Tuple

import cv2
import numpy as np
from PIL import Image

# @Project : pdf_translate 
# @File    : image_remover
# @Author  : yuxiang.jiang
# @Date    : 2025/10/23

logger = logging.getLogger(__name__)


def create_mask(size: Tuple[int, int], boxes: List[Tuple[int, int, int, int]]) -> Image.Image:
    """
    创建一个与传入图片同样大小的掩码图片（L 模式：单通道，0=黑色，255=白色）。

    Args:
        size: 原始图片尺寸 (width, height)
        boxes: 需要清理的矩形区域列表 [(x1, y1, x2, y2), ...]

    Returns:
        Pillow 掩码图片，白色区域表示需要修复/填充的区域。
    """
    mask = Image.new("L", size, 0)
    for box in boxes:
        x1, y1, x2, y2 = box
        # 防御性检查，避免负值或反向坐标造成异常
        w = max(0, x2 - x1)
        h = max(0, y2 - y1)
        if w > 0 and h > 0:
            mask.paste(Image.new("L", (w, h), 255), (max(0, x1), max(0, y1)))
        else:
            logger.debug(f"忽略无效 box: {(x1, y1, x2, y2)}")

    return mask



def clean(image: Image.Image, boxes: list[tuple[int, int, int, int]], method: Optional[str] = None) -> Image.Image:
    """
    根据提供的 boxes 生成掩码并对图像进行修复/填充。

    Args:
        image: 原始 Pillow 图像
        boxes: 需要清理的矩形区域
        method: 清理方法，"telea" 使用 OpenCV inpaint(TELEA)，其他使用简易填充

    Returns:
        清理后的 Pillow 图像（RGB）。
    """
    # 根据boxes创建掩码图片
    mask_image = create_mask(image.size, boxes)
    np_source = np.array(image)
    np_mask = np.array(mask_image)

    if method == "telea":
        cleaned = telea_clean(np_source, np_mask)
    else:
        cleaned = simple_fill_clean(np_source, np_mask)

    # 统一转换为 Pillow RGB 图像
    return Image.fromarray(cleaned.astype('uint8')).convert('RGB')

def telea_clean(image: np.ndarray, mask_image: np.ndarray) -> np.ndarray:
    """使用 OpenCV 的 TELEA 算法进行图像修复。"""
    try:
        result = cv2.inpaint(image, mask_image, 3, cv2.INPAINT_TELEA)
        logger.debug("TELEA算法修复完成")
        return result
    except Exception as e:
        logger.error(f"TELEA算法修复失败: {e}")
        return simple_fill_clean(image, mask_image)

def simple_fill_clean(image: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """
    使用边界像素的均值进行简易填充。当 TELEA 不可用或失败时作为回退方案。

    Args:
        image: 源图像（numpy 数组），支持灰度或 RGB
        mask: 掩码（numpy 数组，255 表示需要填充的区域）

    Returns:
        填充后的图像（numpy 数组）
    """
    result = image.copy()

    # 找到掩码区域
    mask_coords = np.where(mask == 255)

    if len(mask_coords[0]) == 0:
        logger.debug("掩码为空，无需填充")
        return result

    # 使用周围像素的平均值填充
    kernel = np.ones((5, 5), np.uint8)
    dilated_mask = cv2.dilate(mask, kernel, iterations=1)

    # 计算边界区域
    boundary = dilated_mask - mask
    boundary_coords = np.where(boundary == 255)

    if len(boundary_coords[0]) > 0:
        # 使用边界像素的平均值
        if len(image.shape) == 3:
            avg_color = np.mean(image[boundary_coords], axis=0)
            result[mask_coords] = avg_color
        else:
            avg_intensity = np.mean(image[boundary_coords])
            result[mask_coords] = avg_intensity
    else:
        # 如果没有边界，使用白色填充
        if len(image.shape) == 3:
            result[mask_coords] = [255, 255, 255]
        else:
            result[mask_coords] = 255

    logger.debug("简单填充算法完成")
    return result