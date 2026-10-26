# -*- coding: utf-8 -*-
"""RimWorld Chronicle:从 .rws 存档提取编年史素材(纯标准库)。

流水线: extract(存档→dict) -> defs(游戏目录→中文 def 词典) -> storyline(→00-04 素材文档)
         -> voices(→05 角色台词速查) -> writing(可选:配置 OpenAI 兼容 LLM API,
         基于素材直接生成小说草稿到 novel/)
GUI 入口见仓库根目录 app.py;命令行入口 python -m chronicle.pipeline / python -m chronicle.writing。
"""
__version__ = "0.2.0"
