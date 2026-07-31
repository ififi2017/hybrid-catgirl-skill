#!/usr/bin/env python3
"""
通用空闲提醒模板
基于 猫猫 寂寞小猫模式抽象而来，可适配其他角色或场景

使用方法:
1. 复制此文件到新角色目录
2. 修改配置区的常量
3. 自定义消息生成函数
4. 设置 cronjob 定期执行
"""

import json
import os
from datetime import datetime

# ==================== 配置区（需要自定义）====================

# 角色名称（用于状态文件命名）
CHARACTER_NAME = "example_character"

# 提醒间隔（分钟）- 可以定义多个阶段
REMINDER_INTERVALS = [10, 20, 30]  # 第1次10分钟后，第2次20分钟后...

# 最大提醒次数
MAX_REMINDERS = 3

# 状态文件路径
STATE_DIR = os.path.expanduser(f"~/.hermes/state")
STATE_FILE = os.path.join(STATE_DIR, f"{CHARACTER_NAME}_idle.json")

# DEBUG 日志路径
DEBUG_LOG = os.path.join(STATE_DIR, f"{CHARACTER_NAME}_debug.log")
CHAT_HISTORY_FILE = os.path.join(STATE_DIR, f"{CHARACTER_NAME}_chat_history.json")
MAX_HISTORY_MESSAGES = 50

# 是否默认开启 DEBUG
DEBUG_DEFAULT = False

# ==================== 消息生成（需要自定义）====================

def generate_message(count, context):
    """
    根据提醒次数生成消息
    
    Args:
        count: 当前是第几次提醒 (0-based)
        context: 上下文信息（可以包含聊天记录等）
    
    Returns:
        str: 消息内容
    """
    messages = {
        0: [  # 第1次
            "第一次提醒消息",
            "另一种表达...",
        ],
        1: [  # 第2次
            "第二次提醒消息（更强烈）",
        ],
        2: [  # 第3次
            "最后一次提醒",
        ]
    }
    
    import random
    return random.choice(messages.get(count, messages[0]))

# ==================== 核心逻辑（通常不需要修改）====================

def ensure_dir():
    """确保状态目录存在"""
    os.makedirs(STATE_DIR, exist_ok=True)

def log_debug(message):
    """记录 DEBUG 日志"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    debug_msg = f"[DEBUG {timestamp}] {message}"
    
    state = load_state()
    if state.get("debug", DEBUG_DEFAULT):
        print(debug_msg)
        with open(DEBUG_LOG, 'a') as f:
            f.write(debug_msg + "\n")
    
    return debug_msg

def load_state():
    """加载状态"""
    ensure_dir()
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {
        "last_interaction": None,
        "reminder_count": 0,
        "mode": "inactive",  # inactive | active
        "target": None,
        "debug": DEBUG_DEFAULT
    }

def save_state(state):
    """保存状态"""
    ensure_dir()
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)

def load_chat_history():
    """加载角色聊天历史，不存在时返回空历史。"""
    ensure_dir()
    if os.path.exists(CHAT_HISTORY_FILE):
        with open(CHAT_HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"messages": []}

def save_chat_history(history):
    """保存聊天历史。"""
    ensure_dir()
    with open(CHAT_HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def normalize_message(message):
    """将命令行传入的转义换行/制表符还原为实际字符。"""
    return message.replace("\\n", "\n").replace("\\t", "\t")

def append_message(history, role, content):
    """追加消息并限制历史长度，避免上下文文件无限增长。"""
    history.setdefault("messages", []).append({
        "role": role,
        "content": normalize_message(content),
        "time": datetime.now().isoformat()
    })
    history["messages"] = history["messages"][-MAX_HISTORY_MESSAGES:]

def get_interval(count):
    """获取第 count 次的间隔"""
    if count < len(REMINDER_INTERVALS):
        return REMINDER_INTERVALS[count]
    return None

def check():
    """检查是否应该发送提醒"""
    state = load_state()
    debug_msgs = []
    
    # 检查模式
    if state.get("mode") != "active":
        log_debug("当前不是激活模式，跳过")
        return None
    
    count = state.get("reminder_count", 0)
    if count >= MAX_REMINDERS:
        log_debug(f"已达到最大提醒次数 {MAX_REMINDERS}")
        return None
    
    # 检查时间
    last = state.get("last_interaction")
    if not last:
        log_debug("无互动记录")
        return None
    
    last_time = datetime.fromisoformat(last)
    elapsed = (datetime.now() - last_time).total_seconds() / 60
    interval = get_interval(count)
    
    if interval is None:
        return None
    
    log_debug(f"检查: 已过 {elapsed:.1f} 分钟, 目标 {interval} 分钟")
    
    if elapsed >= interval:
        message = generate_message(count, {})
        
        # 先记录主动消息，确保用户回复时上下文完整
        history = load_chat_history()
        append_message(history, "assistant", message)
        save_chat_history(history)

        # 更新状态（在返回结果前预留提醒名额，防止重复检查）
        state["reminder_count"] = count + 1
        save_state(state)
        
        log_debug(f"✅ 触发第 {count + 1} 次提醒")
        
        return {
            "message": message,
            "target": state.get("target")
        }
    else:
        log_debug(f"还需等待 {interval - elapsed:.1f} 分钟")
    
    return None

def set_mode(mode, target=None):
    """设置模式"""
    state = load_state()
    old_mode = state.get("mode")
    state["mode"] = mode
    
    if mode == "active":
        state["last_interaction"] = datetime.now().isoformat()
        state["reminder_count"] = 0
        log_debug(f"激活模式: 计时器启动")
    else:
        log_debug(f"切换到 {mode} 模式: 计时器暂停")
    
    if target:
        state["target"] = target
    
    save_state(state)

def record_interaction():
    """记录互动"""
    state = load_state()
    old_count = state.get("reminder_count", 0)
    state["last_interaction"] = datetime.now().isoformat()
    state["reminder_count"] = 0
    save_state(state)
    log_debug(f"互动记录: 计数器从 {old_count} 重置")

def set_debug(enabled):
    """设置 DEBUG 开关"""
    state = load_state()
    state["debug"] = enabled
    save_state(state)
    print(f"DEBUG: {'开启' if enabled else '关闭'}")

def show_status():
    """显示状态"""
    state = load_state()
    print(f"=== {CHARACTER_NAME} 状态 ===")
    print(f"模式: {state.get('mode')}")
    print(f"DEBUG: {'开启' if state.get('debug') else '关闭'}")
    print(f"已提醒: {state.get('reminder_count', 0)} 次")
    
    last = state.get("last_interaction")
    if last:
        elapsed = (datetime.now() - datetime.fromisoformat(last)).total_seconds() / 60
        count = state.get("reminder_count", 0)
        interval = get_interval(count)
        print(f"上次互动: {elapsed:.1f} 分钟前")
        if interval:
            print(f"下次提醒: 还需 {max(0, interval - elapsed):.1f} 分钟")
    print("=" * 30)

# ==================== 命令行接口 ====================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("用法: python idle-reminder-template.py <command>")
        print("命令:")
        print("  check              - 检查是否触发")
        print("  activate [target]  - 激活模式")
        print("  deactivate         - 关闭模式")
        print("  interact           - 记录互动")
        print("  debug on|off       - DEBUG 开关")
        print("  status             - 显示状态")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "check":
        result = check()
        if result:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print("{}")
    elif cmd == "activate":
        target = sys.argv[2] if len(sys.argv) > 2 else None
        set_mode("active", target)
    elif cmd == "deactivate":
        set_mode("inactive")
    elif cmd == "interact":
        record_interaction()
    elif cmd == "addmsg":
        if len(sys.argv) < 4:
            print("用法: python idle-reminder-template.py addmsg <role> <content>")
            sys.exit(1)
        history = load_chat_history()
        append_message(history, sys.argv[2], sys.argv[3])
        save_chat_history(history)
    elif cmd == "debug":
        enabled = sys.argv[2] == "on" if len(sys.argv) > 2 else True
        set_debug(enabled)
    elif cmd == "status":
        show_status()
    else:
        print(f"未知命令: {cmd}")
