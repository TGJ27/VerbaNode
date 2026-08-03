from __future__ import annotations

# Official speaker mapping for sherpa-onnx kokoro-multi-lang-v1_1 /
# kokoro-int8-multi-lang-v1_1 (103 speakers).
_NAMES = [
    "af_maple", "af_sol", "bf_vale",
    "zf_001", "zf_002", "zf_003", "zf_004", "zf_005", "zf_006", "zf_007",
    "zf_008", "zf_017", "zf_018", "zf_019", "zf_021", "zf_022", "zf_023",
    "zf_024", "zf_026", "zf_027", "zf_028", "zf_032", "zf_036", "zf_038",
    "zf_039", "zf_040", "zf_042", "zf_043", "zf_044", "zf_046", "zf_047",
    "zf_048", "zf_049", "zf_051", "zf_059", "zf_060", "zf_067", "zf_070",
    "zf_071", "zf_072", "zf_073", "zf_074", "zf_075", "zf_076", "zf_077",
    "zf_078", "zf_079", "zf_083", "zf_084", "zf_085", "zf_086", "zf_087",
    "zf_088", "zf_090", "zf_092", "zf_093", "zf_094", "zf_099",
    "zm_009", "zm_010", "zm_011", "zm_012", "zm_013", "zm_014", "zm_015",
    "zm_016", "zm_020", "zm_025", "zm_029", "zm_030", "zm_031", "zm_033",
    "zm_034", "zm_035", "zm_037", "zm_041", "zm_045", "zm_050", "zm_052",
    "zm_053", "zm_054", "zm_055", "zm_056", "zm_057", "zm_058", "zm_061",
    "zm_062", "zm_063", "zm_064", "zm_065", "zm_066", "zm_068", "zm_069",
    "zm_080", "zm_081", "zm_082", "zm_089", "zm_091", "zm_095", "zm_096",
    "zm_097", "zm_098", "zm_100",
]


def _category(name: str) -> str:
    if name.startswith("af_"):
        return "American female"
    if name.startswith("bf_"):
        return "British female"
    if name.startswith("zf_"):
        return "Chinese female"
    if name.startswith("zm_"):
        return "Chinese male"
    return "Other"


KOKORO_VOICES: list[dict[str, object]] = [
    {"id": speaker_id, "name": name, "category": _category(name)}
    for speaker_id, name in enumerate(_NAMES)
]
KOKORO_VOICE_BY_ID = {int(item["id"]): str(item["name"]) for item in KOKORO_VOICES}


def voice_name(speaker_id: int | str | None) -> str:
    try:
        value = int(speaker_id) if speaker_id is not None else 0
    except (TypeError, ValueError):
        value = 0
    return KOKORO_VOICE_BY_ID.get(value, f"speaker_{value}")
