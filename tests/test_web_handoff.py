import base64
from urllib.parse import parse_qs, urlsplit

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.services.web_handoff import (
    build_internal_test_human_handoff_reply,
    build_web_handoff_url,
    build_web_human_handoff_reply,
    get_web_handoff_system_code,
)


TEST_TOKEN_KEY = "1234567890abcdef"
TEST_TIMESTAMP = 1700000000


def decrypt_test_token(token: str) -> str:
    encoded = token + ("=" * (-len(token) % 4))
    encrypted = base64.urlsafe_b64decode(encoded)
    decryptor = Cipher(
        algorithms.AES(TEST_TOKEN_KEY.encode("ascii")),
        modes.ECB(),
    ).decryptor()
    padded_plaintext = decryptor.update(encrypted) + decryptor.finalize()
    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    return (unpadder.update(padded_plaintext) + unpadder.finalize()).decode("utf-8")


def assert_handoff_url(url: str, expected_path: str, expected_identifier: str) -> None:
    parsed = urlsplit(url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == expected_path
    token = parse_qs(parsed.query)["token"][0]
    assert "+" not in token
    assert "/" not in token
    assert "=" not in token
    assert decrypt_test_token(token) == f"{expected_identifier}+{TEST_TIMESTAMP}"


def test_web_handoff_system_code_mapping():
    assert get_web_handoff_system_code({"company_code": "pktv"}) == "P"
    assert get_web_handoff_system_code({"company_code": "wctv"}) == "W"
    assert get_web_handoff_system_code({"company_code": "cltv"}) == "L"
    assert get_web_handoff_system_code({"company_code": "tdtv"}) == "T"
    assert get_web_handoff_system_code({"company_code": "cnt"}) == "N"
    assert get_web_handoff_system_code({"company_code": "toplight"}) == "A"
    assert get_web_handoff_system_code({"company_code": "hya"}) == "J"
    assert get_web_handoff_system_code({"company_code": "tycable"}) == "K"
    assert get_web_handoff_system_code({"company_code": "tinp"}) == "Y"


def test_web_handoff_url_uses_custnum_before_user_id():
    memory = {
        "company_code": "hya",
        "known_info": {
            "custnum": "C12345",
            "external_user_id": "guest_001",
        },
    }

    assert_handoff_url(
        build_web_handoff_url(memory, now=TEST_TIMESTAMP, key=TEST_TOKEN_KEY),
        "http://pweb.topmso.com.tw:96/smartCustomerService/real/C12345/0/J",
        "C12345",
    )


def test_web_handoff_url_uses_external_user_id_when_no_custnum():
    memory = {
        "company_code": "tycable",
        "known_info": {
            "external_user_id": "guest_001",
        },
    }

    assert_handoff_url(
        build_web_handoff_url(memory, now=TEST_TIMESTAMP, key=TEST_TOKEN_KEY),
        "http://pweb.topmso.com.tw:96/smartCustomerService/real/guest_001/0/K",
        "guest_001",
    )


def test_web_handoff_url_uses_channel_context_external_user_id():
    memory = {
        "company_code": "toplight",
        "channel_context": {
            "external_user_id": "flow_7788",
        },
    }

    assert_handoff_url(
        build_web_handoff_url(memory, now=TEST_TIMESTAMP, key=TEST_TOKEN_KEY),
        "http://pweb.topmso.com.tw:96/smartCustomerService/real/flow_7788/0/A",
        "flow_7788",
    )


def test_web_handoff_reply_format():
    memory = {
        "company_code": "tinp",
        "known_info": {"custnum": "1071272"},
    }
    reply = build_web_human_handoff_reply(
        memory,
        now=TEST_TIMESTAMP,
        key=TEST_TOKEN_KEY,
    )

    assert reply.startswith(
        "此項需由真人文字客服協助處理。<br>"
        '請按 <a href="http://pweb.topmso.com.tw:96/smartCustomerService/real/'
        '1071272/0/Y?token='
    )
    assert reply.endswith(
        '">轉真人文字客服</a><br>'
        "或者繼續提問"
    )
    token = reply.split("?token=", 1)[1].split('"', 1)[0]
    assert decrypt_test_token(token) == f"1071272+{TEST_TIMESTAMP}"
    assert "【轉真人客服】" not in reply
    assert "請由真人客服接手" not in reply


def test_internal_test_handoff_reply_uses_local_click_marker():
    reply = build_internal_test_human_handoff_reply()

    assert reply == (
        "此項需由真人文字客服協助處理。<br>"
        '請按 <a href="#internal-human-handoff" data-internal-human-handoff="1">'
        "轉真人文字客服</a><br>"
        "或者繼續提問"
    )
    assert "【轉真人客服】" not in reply
    assert "請由真人客服接手" not in reply
