import unittest

from teleoplab.protocol import (
    KIND_CMD,
    KIND_CTRL,
    KIND_FRAME,
    KIND_STATE,
    Message,
    ProtocolError,
    make_cmd,
    make_ctrl,
    make_frame,
    make_state,
    parse_cmd,
    parse_ctrl,
    parse_frame,
    parse_state,
)


class TestRoundTrip(unittest.TestCase):
    def test_cmd(self):
        msg = make_cmd(7, 123456789, 1.5, -0.25)
        back = Message.decode(msg.encode())
        self.assertEqual(back.kind, KIND_CMD)
        self.assertEqual(back.seq, 7)
        self.assertEqual(back.ts_ns, 123456789)
        vx, vz = parse_cmd(back)
        self.assertAlmostEqual(vx, 1.5, places=5)
        self.assertAlmostEqual(vz, -0.25, places=5)

    def test_state(self):
        msg = make_state(3, 42, 0.1, 0.2, 0.3)
        x, y, theta = parse_state(Message.decode(msg.encode()))
        self.assertAlmostEqual(x, 0.1, places=5)
        self.assertAlmostEqual(y, 0.2, places=5)
        self.assertAlmostEqual(theta, 0.3, places=5)

    def test_ctrl(self):
        msg = make_ctrl(1, 1, 2)
        self.assertEqual(parse_ctrl(Message.decode(msg.encode())), 2)

    def test_frame(self):
        pixels = bytes(range(12))
        msg = make_frame(5, 99, 4, 3, 11, pixels)
        w, h, fid, px = parse_frame(Message.decode(msg.encode()))
        self.assertEqual((w, h, fid), (4, 3, 11))
        self.assertEqual(px, pixels)

    def test_seq_wraps_to_u32(self):
        msg = make_cmd((1 << 32) + 5, 1, 0.0, 0.0)
        self.assertEqual(Message.decode(msg.encode()).seq, 5)

    def test_ts_wraps_to_u64(self):
        msg = make_cmd(1, (1 << 64) + 9, 0.0, 0.0)
        self.assertEqual(Message.decode(msg.encode()).ts_ns, 9)


class TestRejects(unittest.TestCase):
    def test_truncated(self):
        with self.assertRaises(ProtocolError):
            Message.decode(b"TLP1")

    def test_bad_magic(self):
        good = make_cmd(1, 1, 0.0, 0.0).encode()
        with self.assertRaises(ProtocolError):
            Message.decode(b"XXXX" + good[4:])

    def test_unknown_kind(self):
        good = bytearray(make_cmd(1, 1, 0.0, 0.0).encode())
        good[4] = 99
        with self.assertRaises(ProtocolError):
            Message.decode(bytes(good))

    def test_wrong_kind_when_parsing(self):
        with self.assertRaises(ProtocolError):
            parse_state(make_cmd(1, 1, 0.0, 0.0))

    def test_pixel_length_mismatch(self):
        with self.assertRaises(ProtocolError):
            make_frame(1, 1, 4, 3, 0, b"short")

    def test_ctrl_level_out_of_range(self):
        with self.assertRaises(ProtocolError):
            make_ctrl(1, 1, 300)


if __name__ == "__main__":
    unittest.main()
