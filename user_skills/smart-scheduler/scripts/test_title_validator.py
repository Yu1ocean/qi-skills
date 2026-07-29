import sys
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.append(SCRIPT_DIR)

from batch_create_events import (
    validate_title,
    build_default_title,
    build_batch_payload,
    extract_base_title_from_input,
    resolve_base_title,
)

def test_validate_title():
    # 1. 标题不以【预占】开头，应该报错
    try:
        validate_title("开会", 2)
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "标题必须以【预占】开头" in str(e)

    # 2. 单对单，2人，标题正常（这里会引发warning但不会报错）
    validate_title("【预占】张三 × 奇楠", 2)
    validate_title("【预占】随便写只要有 × 奇楠", 2)

    # 3. 多人，>=3人，没有具体主题
    try:
        validate_title("【预占】", 3)
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "多人会议必须包含具体主题" in str(e)
        
    try:
        validate_title("【预占】多人会议", 4)
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "多人会议必须包含具体主题" in str(e)

    # 4. 多人，>=3人，有主题
    validate_title("【预占】项目周会", 3)

def test_build_default_title():
    # 2人
    t2 = build_default_title(2, "李四")
    assert t2 == "【预占】李四 × 奇楠"
    
    # 3人
    try:
        build_default_title(3, "王五")
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "必须提供明确的会议主题" in str(e)


def test_extract_base_title_from_input():
    assert extract_base_title_from_input("今天和苏静开【政策P&L预测讨论】") == "政策P&L预测讨论"
    assert extract_base_title_from_input("无括号主题") == ""


def test_resolve_base_title_hard_gate():
    config = {
        "attendees": ["a", "b"],
        "raw_user_input": "今天 17:30 跟苏静聊【政策P&L预测讨论】",
        "base_title": "旧标题",
    }
    assert resolve_base_title(config, 2, "苏静") == "政策P&L预测讨论"

    try:
        resolve_base_title(
            {
                "attendees": ["a", "b"],
                "raw_user_input": "今天 17:30 跟苏静讨论下政策影响",
                "base_title": "",
            },
            2,
            "苏静",
        )
        assert False, "Should raise ValueError"
    except ValueError as e:
        assert "显式主题" in str(e)

if __name__ == "__main__":
    test_validate_title()
    test_build_default_title()
    test_extract_base_title_from_input()
    test_resolve_base_title_hard_gate()
    print("All tests passed!")


def test_build_payload():
    config = {
        "attendees": ["a", "b"],
        "slots": [{"start": "x", "end": "y"}]
    }
    # base_title为空，2人
    payload = build_batch_payload(config)
    assert payload["events"][0]["title"] == "【预占】同事 × 奇楠"
    
    config2 = {
        "attendees": ["a", "b", "c"],
        "slots": [{"start": "x", "end": "y"}],
        "base_title": "项目周会"
    }
    payload2 = build_batch_payload(config2)
    assert payload2["events"][0]["title"] == "【预占】项目周会"

    config2b = {
        "attendees": ["a", "b"],
        "slots": [{"start": "x", "end": "y"}],
        "base_title": "旧标题",
        "raw_user_input": "今天和苏静开【政策P&L预测讨论】",
    }
    payload2b = build_batch_payload(config2b)
    assert payload2b["events"][0]["title"] == "【预占】政策P&L预测讨论"
    
    config3 = {
        "attendees": ["a", "b", "c"],
        "slots": [{"start": "x", "end": "y"}]
    }
    try:
        build_batch_payload(config3)
        assert False, "Should fail"
    except ValueError as e:
        assert "缺少会议主题" in str(e)

    config4 = {
        "attendees": ["a", "b"],
        "slots": [{"start": "x", "end": "y"}],
        "raw_user_input": "今天 17:30 和苏静讨论一下政策影响",
    }
    try:
        build_batch_payload(config4)
        assert False, "Should fail"
    except ValueError as e:
        assert "显式主题" in str(e)

if __name__ == "__main__":
    test_build_payload()
