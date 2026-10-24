#!/usr/bin/env python3
"""cron（no-agent）入口：寂寞小猫短程阶段（10–50 分钟模板消息）。

到点时只输出消息正文，由调度器原样投递到 job 的 --deliver 目标；没到点不输出 = 静默。
不唤醒 Agent，不消耗模型 Token，所以可以每 5 分钟跑一次。
"""
import contextlib
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import lxc_lonely_cat  # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):  # DEBUG 日志不进投递内容
    result = lxc_lonely_cat.check_and_trigger()

if result and result.get("message"):
    print(result["message"])
