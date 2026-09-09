"""AWS イベントストリーム（application/vnd.amazon.eventstream）のエンコーダ。

Amazon Bedrock のストリーミング API（InvokeModelWithResponseStream / ConverseStream）は、
HTTP のチャンク転送の上に「AWS 独自のバイナリフレーム」を載せて返します。
boto3（botocore）はこのフレームを解析してイベントを1つずつ yield するため、
モックであってもフレーム形式を正しく組み立てないと `EventStreamError` になります。

1フレームの構造（すべてビッグエンディアン）:

    +----------------+----------------+----------------+
    | total length   | headers length | prelude CRC32  |  各4バイト
    +----------------+----------------+----------------+
    | headers ...                                      |
    +--------------------------------------------------+
    | payload ...                                      |
    +--------------------------------------------------+
    | message CRC32                                    |  4バイト
    +--------------------------------------------------+

- total length = 16 + len(headers) + len(payload)（自分自身の4バイトも含む合計）
- prelude CRC32 = 先頭8バイト（total length + headers length）の CRC32
- message CRC32 = 末尾4バイトを除いた全バイトの CRC32
- ヘッダ1件 = [名前の長さ:1][名前][値の型:1][値の長さ:2][値]
  値の型 7 が UTF-8 文字列。Bedrock のイベントヘッダはすべて型 7 を使う。
"""

from __future__ import annotations

import binascii
import struct

# ヘッダ値の型コード。7 = UTF-8 文字列（Bedrock のイベントはこれだけ使う）
_HEADER_TYPE_STRING = 7


def encode_headers(headers: dict[str, str]) -> bytes:
    """ヘッダ辞書をイベントストリームのヘッダ列にエンコードする。"""
    out = bytearray()
    for name, value in headers.items():
        name_bytes = name.encode("utf-8")
        value_bytes = value.encode("utf-8")
        if len(name_bytes) > 255:
            raise ValueError(f"ヘッダ名が長すぎます: {name}")
        out.append(len(name_bytes))
        out += name_bytes
        out.append(_HEADER_TYPE_STRING)
        out += struct.pack(">H", len(value_bytes))
        out += value_bytes
    return bytes(out)


def encode_message(headers: dict[str, str], payload: bytes) -> bytes:
    """1フレーム分のバイト列を組み立てる。"""
    header_bytes = encode_headers(headers)
    total_length = 16 + len(header_bytes) + len(payload)

    prelude = struct.pack(">II", total_length, len(header_bytes))
    prelude_crc = struct.pack(">I", binascii.crc32(prelude) & 0xFFFFFFFF)

    message_without_crc = prelude + prelude_crc + header_bytes + payload
    message_crc = struct.pack(">I", binascii.crc32(message_without_crc) & 0xFFFFFFFF)
    return message_without_crc + message_crc


def event(event_type: str, payload: bytes) -> bytes:
    """通常のイベント（:message-type = event）を1フレームにする。"""
    return encode_message(
        {
            ":event-type": event_type,
            ":content-type": "application/json",
            ":message-type": "event",
        },
        payload,
    )


def exception(error_code: str, payload: bytes) -> bytes:
    """ストリームの途中で送るエラーイベント（:message-type = exception）。

    ストリーミング中に throttling などが起きたときの挙動を再現するために使います。
    """
    return encode_message(
        {
            ":exception-type": error_code,
            ":content-type": "application/json",
            ":message-type": "exception",
        },
        payload,
    )
