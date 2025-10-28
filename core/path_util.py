#!/usr/bin/env python
# -*- coding: UTF-8 -*-
import os
from typing import Union

# @Project : pdf_process
# @File    : path_util
# @Author  : yuxiang.jiang
# @Date    : 2025/10/22

def path(relative_path: str) -> str:
    """返回项目根目录下的绝对路径。

    支持传入绝对路径，直接返回规范化结果；传入相对路径时，以项目根目录为基准。
    """
    if os.path.isabs(relative_path):
        return os.path.normpath(relative_path)
    base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    return os.path.normpath(os.path.join(base_path, relative_path))

def resource_path(relative_path: str) -> str:
    """返回 resources 目录下的绝对路径。

    支持传入绝对路径时直接返回规范化结果。
    """
    if os.path.isabs(relative_path):
        return os.path.normpath(relative_path)
    base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'resources'))
    return os.path.normpath(os.path.join(base_path, relative_path))