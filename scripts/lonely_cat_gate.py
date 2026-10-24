#!/usr/bin/env python3
"""cron 预检闸门：寂寞小猫陪伴模式（Agent 写消息）的前置脚本，只读。

不需要发时最后一行输出 {"wakeAgent": false}，调度器就不唤醒 Agent；
需要发时输出 {"precheck": "due"}，Agent 按 templates/proactive-message.prompt.md 执行。
"""
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lxc_lonely_cat  # noqa: E402

skip = lxc_lonely_cat.companion_precheck(lxc_lonely_cat.load_state(), datetime.now())
if skip:
    print(json.dumps({"precheck": skip}, ensure_ascii=False))
    print(json.dumps({"wakeAgent": False}))
else:
    print(json.dumps({"precheck": "due"}))
