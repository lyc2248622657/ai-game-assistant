"""策略工具纯函数单测：B站标题清洗 / 材料数量归一 / 攻略链接构造"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.tools.strategy_tools import (  # noqa: E402
    _clean_title,
    _count_to_num,
    _normalize_stage,
    _parse_guide_type,
)


def test_clean_title_removes_em_tags():
    raw = "【<em class=\"keyword\">原神</em>】<em class=\"keyword\">那维莱特</em> 超详细攻略"
    assert _clean_title(raw) == "【原神】那维莱特 超详细攻略"


def test_clean_title_empty():
    assert _clean_title(None) == ""
    assert _clean_title("") == ""


def test_count_to_num_wan():
    assert _count_to_num("3w") == 30000
    assert _count_to_num("18w") == 180000
    assert _count_to_num("3万") == 30000
    assert _count_to_num("5") == 5
    assert _count_to_num("") == 0
    assert _count_to_num(None) == 0
    assert _count_to_num("abc") == 0


def test_normalize_stage():
    """关卡名归一：'第八章 H8-4' → 'H8-4'；'傀影肉鸽N15' 保留主题+N"""
    assert _normalize_stage("第八章 H8-4") == "H8-4"
    assert _normalize_stage("h8-4") == "H8-4"
    assert _normalize_stage("TW-8") == "TW-8"
    assert _normalize_stage("1-7") == "1-7"
    assert "N15" in _normalize_stage("傀影肉鸽N15")
    assert _normalize_stage("傀影肉鸽") == "傀影肉鸽"


def test_parse_guide_type():
    """攻略类型黑话识别：摆完挂机/单核/高配/低配/肉鸽N15"""
    assert _parse_guide_type("摆完挂机怎么打") == "摆完挂机"
    assert _parse_guide_type("挂机作业") == "摆完挂机"
    assert _parse_guide_type("单核怎么过") == "单核"
    assert _parse_guide_type("高配通关") == "高配"
    assert _parse_guide_type("平民低配") == "低配"
    assert _parse_guide_type("肉鸽N15怎么打") == "肉鸽N15"
    assert _parse_guide_type("随便看看") == ""
