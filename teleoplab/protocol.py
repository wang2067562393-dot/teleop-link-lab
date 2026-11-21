"""遥操作链路的报文协议。

设计目标很小：控制端 → 网络 → 机器人 → 画面 这条链路上，每一个报文都能
被独立打时间戳、被独立测量、被独立丢弃。所以协议里只放三样东西：
kind（哪一段）、seq（第几个）、ts_ns（什么时候产生的）。

约定：时间戳一律是 **采集点** 打的单调时钟（time.perf_counter_ns），
不是发送点补的，也不跨机器使用（跨机器需要先做时钟同步，见 README 局限）。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

MAGIC = b"TLP1"

KIND_CMD = 1    # 控制端 → 机器人：速度指令
KIND_STATE = 2  # 机器人 → 控制端：状态回传
KIND_FRAME = 3  # 机器人 → 控制端：视频帧
KIND_CTRL = 4   # 控制端 → 机器人：画质等级请求

KIND_NAMES = {
    KIND_CMD: "cmd",
    KIND_STATE: "state",
    KIND_FRAME: "frame",
    KIND_CTRL: "ctrl",
}

# 大端序，避免在本机回环之外的场景踩字节序的坑
_HEADER = struct.Struct("!4sBBIQ")  # magic, kind, flags, seq(u32), ts_ns(u64)
_CMD = struct.Struct("!ff")
_STATE = struct.Struct("!fff")
_CTRL = struct.Struct("!B")
_FRAME = struct.Struct("!HHI")  # width, height, frame_id

SEQ_MOD = 1 << 32
TS_MOD = 1 << 64


class ProtocolError(ValueError):
    """报文不合法（截断、magic 不符、载荷长度不对）。"""


@dataclass(frozen=True)
class Message:
    kind: int
    seq: int
    ts_ns: int
    payload: bytes = b""

    def encode(self) -> bytes:
        head = _HEADER.pack(MAGIC, self.kind, 0, self.seq % SEQ_MOD, self.ts_ns % TS_MOD)
        return head + self.payload

    @classmethod
    def decode(cls, data: bytes) -> "Message":
        if len(data) < _HEADER.size:
            raise ProtocolError(f"报文过短：{len(data)} < {_HEADER.size}")
        magic, kind, _flags, seq, ts_ns = _HEADER.unpack_from(data, 0)
        if magic != MAGIC:
            raise ProtocolError(f"magic 不符：{magic!r}")
        if kind not in KIND_NAMES:
            raise ProtocolError(f"未知报文类型：{kind}")
        return cls(kind=kind, seq=seq, ts_ns=ts_ns, payload=data[_HEADER.size:])

    @property
    def name(self) -> str:
        return KIND_NAMES[self.kind]


def _expect(msg: Message, kind: int) -> None:
    if msg.kind != kind:
        raise ProtocolError(f"期望 {KIND_NAMES[kind]}，收到 {msg.name}")


def make_cmd(seq: int, ts_ns: int, vx: float, vz: float) -> Message:
    return Message(KIND_CMD, seq, ts_ns, _CMD.pack(vx, vz))


def parse_cmd(msg: Message) -> tuple[float, float]:
    _expect(msg, KIND_CMD)
    if len(msg.payload) != _CMD.size:
        raise ProtocolError("cmd 载荷长度不符")
    return _CMD.unpack(msg.payload)


def make_state(seq: int, ts_ns: int, x: float, y: float, theta: float) -> Message:
    return Message(KIND_STATE, seq, ts_ns, _STATE.pack(x, y, theta))


def parse_state(msg: Message) -> tuple[float, float, float]:
    _expect(msg, KIND_STATE)
    if len(msg.payload) != _STATE.size:
        raise ProtocolError("state 载荷长度不符")
    return _STATE.unpack(msg.payload)


def make_ctrl(seq: int, ts_ns: int, level: int) -> Message:
    if not 0 <= level <= 255:
        raise ProtocolError(f"画质等级越界：{level}")
    return Message(KIND_CTRL, seq, ts_ns, _CTRL.pack(level))


def parse_ctrl(msg: Message) -> int:
    _expect(msg, KIND_CTRL)
    if len(msg.payload) != _CTRL.size:
        raise ProtocolError("ctrl 载荷长度不符")
    return _CTRL.unpack(msg.payload)[0]


def make_frame(
    seq: int, ts_ns: int, width: int, height: int, frame_id: int, pixels: bytes
) -> Message:
    if len(pixels) != width * height:
        raise ProtocolError(f"像素长度 {len(pixels)} != {width}x{height}")
    return Message(KIND_FRAME, seq, ts_ns, _FRAME.pack(width, height, frame_id) + pixels)


def parse_frame(msg: Message) -> tuple[int, int, int, bytes]:
    _expect(msg, KIND_FRAME)
    if len(msg.payload) < _FRAME.size:
        raise ProtocolError("frame 头部不完整")
    width, height, frame_id = _FRAME.unpack_from(msg.payload, 0)
    pixels = msg.payload[_FRAME.size:]
    if len(pixels) != width * height:
        raise ProtocolError(f"像素长度 {len(pixels)} != {width}x{height}")
    return width, height, frame_id, pixels
