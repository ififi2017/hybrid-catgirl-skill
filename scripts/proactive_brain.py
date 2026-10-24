#!/usr/bin/env python3
"""Lonely Cat 陪伴模式的“活人感”素材：冷场阶段、记忆钩子、话题轮换、日历。

主人一直没回复时，不再反复拿同一段聊天记录撒娇，而是像一个在过自己日子、也惦记着对方的人：
- 按“连续未回复条数”逐级变短、变轻松，间隔逐步拉长，连续 STOP_AFTER 条没回就安静等待；
- 每次换一个话题（按时段、工作日 / 周末筛选，避开最近用过的）；
- 从 Hermes 记忆（USER.md / MEMORY.md）里挑一两条主人的生活小事作为可选的话头，
  自动过滤技术配置、角色扮演规则和亲密细节；
- 把最近发过的主动消息交给模型，要求不重复开头、意象和话题。

本模块只负责选材和节奏，消息由 Agent 按 templates/proactive-message.prompt.md 写。纯标准库，无依赖。
"""
from __future__ import annotations

import hashlib
import os
import random
import re
from datetime import datetime, timedelta

MEMORY_DIR = os.path.join(os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")), "memories")
MEMORY_FILES = ("USER.md", "MEMORY.md")

HISTORY_KEEP = 12          # 保留最近几条主动消息
AVOID_RECENT_MESSAGES = 6  # 交给模型避免重复的条数
AVOID_TOPICS = 4           # 最近几次用过的话题不再选
AVOID_MEMORY = 2           # 最近几次用过的记忆钩子不再选（记忆条目通常不多，窗口别太大）
STOP_AFTER = 6             # 连续这么多条没回就停，等主人先开口

# 连续未回复条数 → 阶段。interval_hours 是这一条发出后到下一条的间隔。
STAGES = [
    {"name": "想你了", "max_chars": 120, "interval_hours": 4, "use_chat": True,
     "guide": "自然地接上最近聊过的事或记忆里的一个细节，像随口想起来，带点黏人。"},
    {"name": "换个话头", "max_chars": 100, "interval_hours": 6, "use_chat": True,
     "guide": "不再追着上次的话题，换成自己今天的小事或记忆里的另一个点，问一个轻松的小问题。"},
    {"name": "自己找乐子", "max_chars": 80, "interval_hours": 8, "use_chat": False,
     "guide": "主人可能在忙。讲自己刚做的一件具体小事，或分享一个小发现，不追问为什么不回。"},
    {"name": "小声报平安", "max_chars": 60, "interval_hours": 12, "use_chat": False,
     "guide": "很短，语气放松，不撒娇不抱怨，就是让主人知道你在。可以只是一句日常。"},
    {"name": "安静陪着", "max_chars": 40, "interval_hours": 24, "use_chat": False,
     "guide": "一天一句就好，极简、温柔、不要求回复，例如顺手说一句今天的天气或一件小事。"},
    {"name": "最后留言", "max_chars": 50, "interval_hours": 24, "use_chat": False,
     "guide": "告诉主人你先不打扰了，等他忙完随时来找你；不要有委屈或指责。"},
]

# 话题池：(id, 描述, 适用时段)。时段为 None 表示全天可用。
TOPICS = [
    ("cat_daily", "猫猫刚做的一件具体小事（追光斑、霸占键盘、整理自己的小窝、偷吃小鱼干等，自己编一件新的）", None),
    ("weather", "今天的天气/体感（结合季节），顺带一句提醒", None),
    ("food", "吃饭相关：问吃了没、推荐一样吃的、或自己馋了什么", ("中午", "傍晚")),
    ("work_break", "提醒起来活动一下、喝口水、看看远处", ("上午", "下午")),
    ("small_question", "问一个轻松好答的小问题（二选一、今天最想吃啥、周末想干嘛）", None),
    ("share_fact", "分享一个刚知道的冷知识/小发现，用猫猫的口吻转述", None),
    ("little_game", "发起一个一句话就能玩的小游戏（猜猜我在干嘛、成语接龙第一句、二选一）", ("下午", "傍晚", "晚上")),
    ("memory_callback", "从记忆钩子里挑一条自然地提起，像突然想起来", None),
    ("weekend", "周末计划/周末心情", None),
    ("goodnight_soft", "睡前的一句轻声问候，提醒早点休息", ("晚上",)),
    ("morning_soft", "早晨的一句问候，加一个今天的小期待", ("上午",)),
]
WEEKEND_ONLY = {"weekend"}        # 周五到周日才聊周末
WORKDAY_ONLY = {"work_break"}     # 工作日才提醒起来活动

# 固定日期的节日（月, 日）→ 名称
HOLIDAYS = {
    (1, 1): "元旦", (2, 14): "情人节", (3, 8): "妇女节", (4, 1): "愚人节",
    (5, 1): "劳动节", (5, 20): "520", (6, 1): "儿童节", (10, 1): "国庆节",
    (10, 31): "万圣节前夜", (11, 11): "双十一", (12, 24): "平安夜", (12, 25): "圣诞节",
}
WEEKDAYS = "一二三四五六日"

# 记忆里不适合拿来当主动消息话题的内容：技术配置 / 凭据线索、亲密细节、“怎么扮演 / 怎么运维”的规则
_TECH = re.compile(r"https?://|`|/|\\|token|api|base_url|ssh|proxy|config|cron|session|gateway|json|"
                   r"端口|节点|密码|凭据|脚本|部署|仓库|v\d+\.\d+", re.I)
_INTIMATE = re.compile(r"R-?18|NSFW|亲密|色情|露骨|暧昧|L[1-5]")
_META = re.compile(r"模式|触发|切换|skill|Hermes|hermes|GitHub|账号|角色名|称呼|设定|写入记忆|meta|用途|"
                   r"指令|摘要|大纲|角色扮演|应使用|会自行判断|隐私", re.I)


def time_period(hour: int) -> str:
    if 8 <= hour < 12:
        return "上午"
    if 12 <= hour < 14:
        return "中午"
    if 14 <= hour < 18:
        return "下午"
    if 18 <= hour < 21:
        return "傍晚"
    return "晚上"


def season(month: int) -> str:
    return {12: "冬", 1: "冬", 2: "冬", 3: "春", 4: "春", 5: "春",
            6: "夏", 7: "夏", 8: "夏"}.get(month, "秋")


def calendar(now: datetime) -> dict:
    info = {"date": now.strftime("%Y-%m-%d"), "weekday": "周" + WEEKDAYS[now.weekday()],
            "is_weekend": now.weekday() >= 5, "season": season(now.month),
            "time_period": time_period(now.hour), "current_time": now.strftime("%H:%M")}
    for delta in (0, 1):  # 今天或明天的节日
        day = now + timedelta(days=delta)
        if (day.month, day.day) in HOLIDAYS:
            info["holiday"] = ("今天是" if delta == 0 else "明天是") + HOLIDAYS[(day.month, day.day)]
    return info


def memory_hooks(memory_dir: str = MEMORY_DIR) -> list[dict]:
    """把 Hermes 记忆拆成一句一句的生活小事，过滤掉技术配置、扮演规则和亲密细节。"""
    hooks = []
    for name in MEMORY_FILES:
        try:
            with open(os.path.join(memory_dir, name), encoding="utf-8") as f:
                text = f.read()
        except OSError:
            continue
        for block in text.split("§"):
            for sentence in re.split(r"(?<=[。！？!?；;])|\n", block):
                sentence = sentence.strip(" \t*-")
                if not (8 <= len(sentence) <= 120):
                    continue
                if _TECH.search(sentence) or _INTIMATE.search(sentence) or _META.search(sentence):
                    continue
                hooks.append({"id": hashlib.sha1(sentence.encode("utf-8")).hexdigest()[:10],
                              "source": name, "text": sentence})
    return hooks


def unanswered_streak(history: list[dict], last_user_activity: datetime | None) -> int:
    """上次真实互动之后连发了几条没被回的主动消息。"""
    if not history:
        return 0
    if last_user_activity is None:
        return len(history)
    return sum(1 for h in history if datetime.fromisoformat(h["time"]) > last_user_activity)


def stage_for(streak: int) -> dict:
    return STAGES[min(streak, len(STAGES) - 1)]


def pick_topic(history: list[dict], cal: dict, rng: random.Random) -> dict:
    period, friday_to_sunday = cal["time_period"], cal["weekday"] in ("周五", "周六", "周日")

    def fits(t):
        if t[0] in WEEKEND_ONLY and not friday_to_sunday:
            return False
        if t[0] in WORKDAY_ONLY and cal["is_weekend"]:
            return False
        return t[2] is None or period in t[2]

    used = {h.get("topic") for h in history[-AVOID_TOPICS:]}
    candidates = [t for t in TOPICS if t[0] not in used and fits(t)] or [t for t in TOPICS if fits(t)]
    tid, desc, _ = rng.choice(candidates)
    return {"id": tid, "description": desc}


def pick_memory(history: list[dict], rng: random.Random, count: int = 2, memory_dir: str = MEMORY_DIR) -> list[dict]:
    used = {mid for h in history[-AVOID_MEMORY:] for mid in h.get("memory_ids", [])}
    hooks = memory_hooks(memory_dir)
    fresh = [h for h in hooks if h["id"] not in used] or hooks
    rng.shuffle(fresh)
    return fresh[:count]


def build_context(history: list[dict], last_user_activity: datetime | None, now: datetime,
                  rng: random.Random | None = None, memory_dir: str = MEMORY_DIR) -> dict | None:
    """交给 Agent 写主动消息的全部素材。连续未回复达到 STOP_AFTER 时返回 None（不发）。

    返回值里以 "_" 开头的键（_memory_ids、use_recent_chat）给调用方记账用，交给 Agent 前先 pop 掉。
    """
    rng = rng or random.Random()
    streak = unanswered_streak(history, last_user_activity)
    if streak >= STOP_AFTER:
        return None
    stage = stage_for(streak)
    cal = calendar(now)
    hooks = pick_memory(history, rng, memory_dir=memory_dir)
    return {
        "unanswered_streak": streak,
        "stage": {k: stage[k] for k in ("name", "guide", "max_chars")},
        "use_recent_chat": stage["use_chat"],
        "calendar": cal,
        "topic_seed": pick_topic(history, cal, rng),
        "memory_hooks": [h["text"] for h in hooks],
        "_memory_ids": [h["id"] for h in hooks],
        "recent_proactive_messages": [h["message"] for h in history[-AVOID_RECENT_MESSAGES:]],
    }


def next_interval(streak_after_send: int) -> timedelta:
    """这一条发出后（未回复数 = streak_after_send）到下一条的间隔。"""
    return timedelta(hours=STAGES[min(max(streak_after_send, 1) - 1, len(STAGES) - 1)]["interval_hours"])


def record_sent(history: list[dict], message: str, pending: dict | None, now: datetime) -> list[dict]:
    history.append({"time": now.isoformat(), "message": message,
                    "topic": (pending or {}).get("topic"),
                    "memory_ids": (pending or {}).get("memory_ids", [])})
    return history[-HISTORY_KEEP:]


if __name__ == "__main__":
    import json
    print(json.dumps(build_context([], None, datetime.now()), ensure_ascii=False, indent=2))
