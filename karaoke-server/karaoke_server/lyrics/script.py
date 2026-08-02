"""Normalize lyric text to Japanese character forms.

Chinese lyric sites (a major source of Japanese synced lyrics) store Japanese
text with Simplified-Chinese codepoints (热 for 熱, 开 for 開, 绝 for 絶...).
Those glyphs break furigana (fugashi/UniDic can't read them) and silently
weaken alignment (the characters never match the transcription). For songs in
Japanese we convert per character: Simplified -> Traditional via OpenCC, then
Traditional/kyūjitai -> shinjitai via a curated table. Characters that are
already Japanese pass through unchanged; unknown ones degrade gracefully
(kept as-is, exactly the previous behaviour).
"""

from __future__ import annotations

from functools import lru_cache

# Traditional / kyūjitai -> shinjitai for the common cases where the
# Traditional form OpenCC produces differs from the modern Japanese glyph.
_KYU2SHIN = str.maketrans({
    "亞": "亜", "惡": "悪", "壓": "圧", "圍": "囲", "醫": "医", "爲": "為",
    "壹": "壱", "隱": "隠", "榮": "栄", "營": "営", "衞": "衛", "驛": "駅",
    "圓": "円", "緣": "縁", "艷": "艶", "鹽": "塩", "奧": "奥", "應": "応",
    "橫": "横", "歐": "欧", "毆": "殴", "黃": "黄", "溫": "温", "穩": "穏",
    "假": "仮", "價": "価", "畫": "画", "會": "会", "壞": "壊", "懷": "懐",
    "繪": "絵", "擴": "拡", "殼": "殻", "覺": "覚", "學": "学", "嶽": "岳",
    "樂": "楽", "勸": "勧", "卷": "巻", "寬": "寛", "歡": "歓", "觀": "観",
    "關": "関", "陷": "陥", "顏": "顔", "歸": "帰", "氣": "気", "龜": "亀",
    "僞": "偽", "戲": "戯", "犧": "犠", "舊": "旧", "據": "拠", "擧": "挙",
    "虛": "虚", "峽": "峡", "挾": "挟", "狹": "狭", "曉": "暁", "區": "区",
    "驅": "駆", "勳": "勲", "徑": "径", "惠": "恵", "揭": "掲", "溪": "渓",
    "經": "経", "繼": "継", "莖": "茎", "螢": "蛍", "輕": "軽", "鷄": "鶏",
    "藝": "芸", "擊": "撃", "缺": "欠", "儉": "倹", "劍": "剣", "圈": "圏",
    "檢": "検", "權": "権", "獻": "献", "縣": "県", "險": "険", "顯": "顕",
    "驗": "験", "嚴": "厳", "效": "効", "廣": "広", "恆": "恒", "鑛": "鉱",
    "號": "号", "國": "国", "濟": "済", "碎": "砕", "齋": "斎", "劑": "剤",
    "櫻": "桜", "雜": "雑", "參": "参", "慘": "惨", "棧": "桟", "蠶": "蚕",
    "贊": "賛", "殘": "残", "絲": "糸", "齒": "歯", "兒": "児", "辭": "辞",
    "濕": "湿", "實": "実", "寫": "写", "釋": "釈", "壽": "寿", "收": "収",
    "從": "従", "澁": "渋", "獸": "獣", "縱": "縦", "肅": "粛", "處": "処",
    "緖": "緒", "敍": "叙", "燒": "焼", "證": "証", "乘": "乗", "剩": "剰",
    "壤": "壌", "孃": "嬢", "條": "条", "淨": "浄", "狀": "状", "疊": "畳",
    "讓": "譲", "釀": "醸", "觸": "触", "囑": "嘱", "寢": "寝", "愼": "慎",
    "眞": "真", "盡": "尽", "圖": "図", "粹": "粋", "醉": "酔", "隨": "随",
    "髓": "髄", "數": "数", "樞": "枢", "聲": "声", "靜": "静", "齊": "斉",
    "攝": "摂", "竊": "窃", "專": "専", "戰": "戦", "淺": "浅", "潛": "潜",
    "纖": "繊", "踐": "践", "錢": "銭", "禪": "禅", "壯": "壮", "搜": "捜",
    "插": "挿", "巢": "巣", "爭": "争", "總": "総", "聰": "聡", "莊": "荘",
    "裝": "装", "騷": "騒", "增": "増", "藏": "蔵", "臟": "臓", "屬": "属",
    "續": "続", "墮": "堕", "體": "体", "對": "対", "帶": "帯", "滯": "滞",
    "臺": "台", "瀧": "滝", "擇": "択", "澤": "沢", "單": "単", "擔": "担",
    "膽": "胆", "團": "団", "彈": "弾", "斷": "断", "遲": "遅", "晝": "昼",
    "蟲": "虫", "鑄": "鋳", "廳": "庁", "徵": "徴", "聽": "聴", "鎭": "鎮",
    "遞": "逓", "鐵": "鉄", "轉": "転", "點": "点", "傳": "伝", "黨": "党",
    "盜": "盗", "燈": "灯", "當": "当", "德": "徳", "獨": "独", "讀": "読",
    "屆": "届", "繩": "縄", "貳": "弐", "惱": "悩", "腦": "脳", "廢": "廃",
    "拜": "拝", "賣": "売", "麥": "麦", "發": "発", "髮": "髪", "拔": "抜",
    "晚": "晩", "蠻": "蛮", "祕": "秘", "濱": "浜", "甁": "瓶", "拂": "払",
    "佛": "仏", "倂": "併", "變": "変", "邊": "辺", "辯": "弁", "辨": "弁",
    "舖": "舗", "步": "歩", "穗": "穂", "寶": "宝", "豐": "豊", "沒": "没",
    "飜": "翻", "每": "毎", "萬": "万", "滿": "満", "麵": "麺", "默": "黙",
    "彌": "弥", "藥": "薬", "譯": "訳", "豫": "予", "餘": "余", "與": "与",
    "譽": "誉", "搖": "揺", "樣": "様", "謠": "謡", "來": "来", "賴": "頼",
    "亂": "乱", "覽": "覧", "龍": "竜", "兩": "両", "獵": "猟", "綠": "緑",
    "壘": "塁", "淚": "涙", "禮": "礼", "勵": "励", "戾": "戻", "靈": "霊",
    "齡": "齢", "曆": "暦", "歷": "歴", "戀": "恋", "鍊": "錬", "爐": "炉",
    "勞": "労", "樓": "楼", "郞": "郎", "錄": "録", "灣": "湾", "絕": "絶",
    "顚": "顛",
})


@lru_cache(maxsize=1)
def _s2t():
    from opencc import OpenCC

    return OpenCC("s2t")


def _is_cjk_ideograph(ch: str) -> bool:
    o = ord(ch)
    return 0x3400 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF


@lru_cache(maxsize=4096)
def _ja_char(ch: str) -> str:
    if not _is_cjk_ideograph(ch):
        return ch
    converted = _s2t().convert(ch)
    # OpenCC may expand one char to several; keep the original on surprises.
    if len(converted) != 1:
        converted = ch
    return converted.translate(_KYU2SHIN)


def to_japanese_kanji(text: str) -> str:
    """Map Simplified-Chinese / Traditional glyphs in Japanese lyric text to
    their shinjitai forms, character by character (length is preserved)."""
    return "".join(_ja_char(ch) for ch in text)
