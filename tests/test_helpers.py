from datetime import timedelta

from custom_components.hikvision_snmp.helpers import (
    decode_octet_string,
    decode_walk_results,
    parse_bool,
    parse_int,
    parse_uptime,
)


def test_decode_octet_string_bytes():
    assert decode_octet_string(b"Hello\x00World  ") == "HelloWorld"


def test_decode_octet_string_str():
    assert decode_octet_string("plain") == "plain"


def test_decode_octet_string_none():
    assert decode_octet_string(None) == ""


def test_decode_octet_string_bad_bytes():
    # must not raise; returns some string
    result = decode_octet_string(b"\xff\xfe\xfd")
    assert isinstance(result, str)


def test_parse_uptime_seconds():
    # 100 * 1/100 s = 1 s
    assert parse_uptime(100) == timedelta(seconds=1)


def test_parse_uptime_days():
    # 8640000 = 1 day
    assert parse_uptime(8640000) == timedelta(days=1)


def test_parse_uptime_zero():
    assert parse_uptime(0) == timedelta(0)


def test_parse_uptime_none():
    assert parse_uptime(None) == timedelta(0)


def test_parse_int_valid():
    assert parse_int("42") == 42
    assert parse_int(42) == 42
    assert parse_int(42.0) == 42


def test_parse_int_invalid_returns_none():
    assert parse_int("abc") is None
    assert parse_int(None) is None


def test_parse_bool_truthy():
    assert parse_bool(1) is True
    assert parse_bool("1") is True


def test_parse_bool_falsy():
    assert parse_bool(0) is False
    assert parse_bool("0") is False


def test_parse_bool_unknown():
    assert parse_bool(7) is None
    assert parse_bool(None) is None


def test_decode_walk_results_basic():
    # Simulate a GETBULK over 1.3.6.1.4.1.39165.1.1.1 subtree
    raw = [
        ("1.3.6.1.4.1.39165.1.1.1.1.0", "DS-7608N-I2"),
        ("1.3.6.1.4.1.39165.1.1.1.3.0", "V3.4.106"),
        ("1.3.6.1.4.1.39165.1.1.1.6.0", 12),
    ]
    out = decode_walk_results(raw, "1.3.6.1.4.1.39165.1.1.1", {
        "model": "1",
        "firmware": "3",
        "cpu": "6",
    })
    assert out["model"]["0"] == "DS-7608N-I2"
    assert out["firmware"]["0"] == "V3.4.106"
    assert out["cpu"]["0"] == 12


def test_decode_walk_results_channel_table():
    raw = [
        ("1.3.6.1.4.1.39165.1.2.1.1.1", "Cam1"),
        ("1.3.6.1.4.1.39165.1.2.1.1.2", "Cam2"),
        ("1.3.6.1.4.1.39165.1.2.1.4.1", 2048),
        ("1.3.6.1.4.1.39165.1.2.1.4.2", 4096),
    ]
    out = decode_walk_results(raw, "1.3.6.1.4.1.39165.1.2.1", {
        "name": "1",
        "bitrate": "4",
    })
    assert out["name"] == {"1": "Cam1", "2": "Cam2"}
    assert out["bitrate"] == {"1": 2048, "2": 4096}


def test_decode_walk_results_filters_other_subtrees():
    raw = [
        ("1.3.6.1.4.1.39165.1.3.1.1.1", "HDD1"),  # disk subtree — must be dropped
        ("1.3.6.1.4.1.39165.1.1.1.3.0", "V1"),
    ]
    out = decode_walk_results(raw, "1.3.6.1.4.1.39165.1.1.1", {"firmware": "3"})
    assert out == {"firmware": {"0": "V1"}}


def test_decode_walk_results_skips_unknown_leaf_prefix():
    raw = [
        ("1.3.6.1.4.1.39165.1.1.1.99.0", "unknown"),  # leaf prefix not in oid_map
        ("1.3.6.1.4.1.39165.1.1.1.3.0", "V1"),
    ]
    out = decode_walk_results(raw, "1.3.6.1.4.1.39165.1.1.1", {"firmware": "3"})
    assert out == {"firmware": {"0": "V1"}}