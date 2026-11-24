import os
import queue
import subprocess
import threading
import time
import unittest
from pathlib import Path

import io
import struct
import tempfile
import wave
import zlib

from cotuong import (
    DEPTH_MODE_TIME_CAP_MS,
    ENGINE_RESTART_LIMIT,
    ENGINE_RESTART_WINDOW,
    engine_restart_allowed,
    ODD_MAX_LOSS_CP,
    OPENING_BOOK,
    OPENING_CATALOGUE,
    NAMED_OPENINGS,
    OPENING_STYLE_CHOICES,
    STYLE_ODD,
    STYLE_VERY_ODD,
    build_opening_go_command,
    catalogue_moves,
    choose_style_move,
    flip_move_rank,
    is_mainstream_opening,
    named_opening_candidates,
    named_opening_from_style,
    opening_name,
    SOUND_NAMES,
    SOUND_RATE,
    XiangqiRules,
    build_go_command,
    choose_varied_move,
    encode_png_rgba,
    ensure_sound_files,
    eval_fraction,
    format_score,
    parse_uci_info,
    piece_sprite_size,
    recommended_hash_mb,
    render_panel_png,
    render_piece_png,
    samples_to_wav,
    score_to_cp,
    synth_sound,
)

START_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"
ENGINE_PATH = Path(__file__).resolve().parent / "engine.exe"


INITIAL_BOARD = [
    list("rnbakabnr"),
    list("........."),
    list(".c.....c."),
    list("p.p.p.p.p"),
    list("........."),
    list("........."),
    list("P.P.P.P.P"),
    list(".C.....C."),
    list("........."),
    list("RNBAKABNR"),
]


def empty_board():
    return [list(".........") for _ in range(10)]


def board_with_kings():
    board = empty_board()
    board[0][4] = 'k'
    board[9][4] = 'K'
    board[5][4] = 'P'  # Chặn hai Tướng nhìn mặt nhau.
    return board


def board_from_fen(fen):
    board = []
    for rank in fen.split()[0].split('/'):
        row = []
        for char in rank:
            if char.isdigit():
                row.extend(['.'] * int(char))
            else:
                row.append(char)
        board.append(row)
    return board


def parse_move(move):
    return (
        (9 - int(move[1]), ord(move[0]) - ord('a')),
        (9 - int(move[3]), ord(move[2]) - ord('a')),
    )


class XiangqiRulesTests(unittest.TestCase):
    def test_every_opening_book_move_is_legal(self):
        for fen, moves in OPENING_BOOK.items():
            board = board_from_fen(fen)
            side = fen.split()[1]
            for move in moves:
                with self.subTest(fen=fen, move=move):
                    start, end = parse_move(move)
                    self.assertTrue(XiangqiRules.is_legal_move(board, start, end, side))

    def test_initial_position_has_44_moves_for_each_side(self):
        self.assertEqual(len(XiangqiRules.legal_moves(INITIAL_BOARD, 'w')), 44)
        self.assertEqual(len(XiangqiRules.legal_moves(INITIAL_BOARD, 'b')), 44)

    def test_cannot_move_wrong_side_or_capture_own_piece(self):
        self.assertFalse(XiangqiRules.is_legal_move(INITIAL_BOARD, (3, 0), (4, 0), 'w'))
        self.assertFalse(XiangqiRules.is_legal_move(INITIAL_BOARD, (9, 0), (9, 1), 'w'))

    def test_rook_cannot_jump_over_pieces(self):
        self.assertFalse(XiangqiRules.is_legal_move(INITIAL_BOARD, (9, 0), (0, 0), 'w'))

    def test_horse_leg_can_be_blocked(self):
        board = [row[:] for row in INITIAL_BOARD]
        self.assertTrue(XiangqiRules.is_legal_move(board, (9, 1), (7, 2), 'w'))
        board[8][1] = 'P'
        self.assertFalse(XiangqiRules.is_legal_move(board, (9, 1), (7, 2), 'w'))

    def test_elephant_eye_and_river(self):
        board = board_with_kings()
        board[9][2] = 'B'
        self.assertTrue(XiangqiRules.is_legal_move(board, (9, 2), (7, 4), 'w'))
        board[8][3] = 'P'
        self.assertFalse(XiangqiRules.is_legal_move(board, (9, 2), (7, 4), 'w'))

        board = board_with_kings()
        board[6][2] = 'B'
        self.assertFalse(XiangqiRules.is_legal_move(board, (6, 2), (4, 4), 'w'))

    def test_advisor_and_king_stay_in_palace(self):
        board = board_with_kings()
        board[9][3] = 'A'
        self.assertTrue(XiangqiRules.is_legal_move(board, (9, 3), (8, 4), 'w'))
        self.assertFalse(XiangqiRules.is_legal_move(board, (9, 3), (8, 2), 'w'))
        self.assertTrue(XiangqiRules.is_legal_move(board, (9, 4), (9, 5), 'w'))
        self.assertFalse(XiangqiRules.is_legal_move(board, (9, 4), (9, 6), 'w'))

    def test_cannon_requires_exactly_one_screen_to_capture(self):
        self.assertTrue(XiangqiRules.is_legal_move(INITIAL_BOARD, (7, 1), (0, 1), 'w'))
        self.assertFalse(XiangqiRules.is_legal_move(INITIAL_BOARD, (7, 1), (2, 1), 'w'))

    def test_pawn_movement_before_and_after_crossing_river(self):
        self.assertTrue(XiangqiRules.is_legal_move(INITIAL_BOARD, (6, 0), (5, 0), 'w'))
        self.assertFalse(XiangqiRules.is_legal_move(INITIAL_BOARD, (6, 0), (6, 1), 'w'))
        self.assertFalse(XiangqiRules.is_legal_move(INITIAL_BOARD, (6, 0), (7, 0), 'w'))

        board = board_with_kings()
        board[4][0] = 'P'
        self.assertTrue(XiangqiRules.is_legal_move(board, (4, 0), (4, 1), 'w'))
        self.assertFalse(XiangqiRules.is_legal_move(board, (4, 0), (5, 0), 'w'))

    def test_flying_generals_and_exposing_the_file(self):
        board = empty_board()
        board[0][4] = 'k'
        board[9][4] = 'K'
        self.assertTrue(XiangqiRules.is_in_check(board, 'w'))
        self.assertTrue(XiangqiRules.is_in_check(board, 'b'))

        board[5][4] = 'R'
        self.assertFalse(XiangqiRules.is_in_check(board, 'w'))
        self.assertFalse(XiangqiRules.is_legal_move(board, (5, 4), (5, 3), 'w'))

    def test_checkmate_and_stalemate_are_both_losses(self):
        stalemate = empty_board()
        stalemate[0][3] = 'k'
        stalemate[9][4] = 'K'
        stalemate[8][0] = 'r'
        stalemate[7][3] = 'r'
        stalemate[7][5] = 'r'
        self.assertEqual(XiangqiRules.game_result(stalemate, 'w'), ('stalemate', 'b'))

        checkmate = empty_board()
        checkmate[0][3] = 'k'
        checkmate[9][4] = 'K'
        checkmate[9][0] = 'r'
        checkmate[8][0] = 'r'
        self.assertEqual(XiangqiRules.game_result(checkmate, 'w'), ('checkmate', 'b'))


def play(board, side, move):
    """Đi một nước (đã kiểm tra hợp lệ) và trả về bên tới lượt tiếp theo."""
    start, end = parse_move(move)
    assert XiangqiRules.is_legal_move(board, start, end, side), move
    board[end[0]][end[1]] = board[start[0]][start[1]]
    board[start[0]][start[1]] = '.'
    return XiangqiRules.opponent(side)


class DrawRulesTests(unittest.TestCase):
    def test_rule60(self):
        self.assertIsNone(XiangqiRules.rule60_result(119))
        self.assertEqual(XiangqiRules.rule60_result(120), ('rule60', None))


class UciHelperTests(unittest.TestCase):
    def test_engine_restart_is_rate_limited(self):
        now = 1000.0
        allowed, recent = engine_restart_allowed([], now)
        self.assertTrue(allowed)
        self.assertEqual(recent, [])
        crashes = [now - 1.0] * ENGINE_RESTART_LIMIT
        allowed, recent = engine_restart_allowed(crashes, now)
        self.assertFalse(allowed)
        # Crash cũ ngoài cửa sổ thời gian không còn tính.
        old = [now - ENGINE_RESTART_WINDOW - 1.0] * ENGINE_RESTART_LIMIT
        allowed, recent = engine_restart_allowed(old + [now - 2.0], now)
        self.assertTrue(allowed)
        self.assertEqual(recent, [now - 2.0])

    def test_parse_cp_info_line(self):
        info = parse_uci_info(
            "info depth 12 seldepth 24 multipv 1 score cp 27 nodes 45245 nps 1103536 "
            "hashfull 21 tbhits 0 time 41 pv h2e2 h9g7 h0g2"
        )
        self.assertEqual(info['depth'], 12)
        self.assertEqual(info['multipv'], 1)
        self.assertEqual(info['score'], ('cp', 27))
        self.assertIsNone(info['bound'])
        self.assertEqual(info['pv'], ['h2e2', 'h9g7', 'h0g2'])

    def test_parse_mate_and_bound(self):
        info = parse_uci_info("info depth 20 multipv 2 score mate -3 upperbound nodes 1 pv a0a1")
        self.assertEqual(info['score'], ('mate', -3))
        self.assertEqual(info['multipv'], 2)
        self.assertEqual(info['bound'], 'upperbound')

    def test_parse_ignores_lines_without_score(self):
        self.assertIsNone(parse_uci_info("info string NNUE evaluation using pikafish.nnue"))
        self.assertIsNone(parse_uci_info("info depth 5 currmove h2e2 currmovenumber 1"))

    def test_format_score_from_red_point_of_view(self):
        self.assertEqual(format_score(('cp', 31)), "+0.31")
        self.assertEqual(format_score(('cp', 31), flip=True), "-0.31")
        self.assertEqual(format_score(('cp', 0)), "0.00")
        self.assertEqual(format_score(('mate', 3)), "+M3")
        self.assertEqual(format_score(('mate', -2), flip=True), "+M2")

    def test_mate_scores_rank_above_any_cp(self):
        self.assertGreater(score_to_cp(('mate', 5)), score_to_cp(('cp', 5000)))
        self.assertGreater(score_to_cp(('mate', 2)), score_to_cp(('mate', 5)))
        self.assertLess(score_to_cp(('mate', -2)), score_to_cp(('mate', -5)))

    def test_choose_varied_move_respects_threshold_and_depth(self):
        def line(depth, cp, move):
            return {'depth': depth, 'score': ('cp', cp), 'bound': None, 'pv': [move, 'x']}

        candidates = {1: line(20, 50, 'best'), 2: line(20, 35, 'close'),
                      3: line(20, 10, 'bad'), 4: line(19, 49, 'stale')}

        class RecordingRng:
            def choice(self, pool):
                self.pool = [pv[0] for pv in pool]
                return pool[0]

        rng = RecordingRng()
        choose_varied_move(candidates, 20, rng)
        self.assertEqual(sorted(rng.pool), ['best', 'close'])
        self.assertIsNone(choose_varied_move({}, 20))

    def test_build_go_command(self):
        self.assertEqual(build_go_command("5 giây / nước"), "go movetime 5000")
        self.assertEqual(
            build_go_command("Độ sâu 24"), f"go depth 24 movetime {DEPTH_MODE_TIME_CAP_MS}"
        )
        self.assertEqual(build_go_command("1 giây / nước", ponder=True),
                         "go ponder movetime 1000")

    def test_recommended_hash(self):
        self.assertEqual(recommended_hash_mb(32768), 2048)
        self.assertEqual(recommended_hash_mb(4096), 512)
        self.assertEqual(recommended_hash_mb(1000), 64)
        self.assertEqual(recommended_hash_mb(0), 256)


class OpeningStyleTests(unittest.TestCase):
    def test_every_catalogue_move_is_legal_from_the_start_for_both_sides(self):
        for side in ('w', 'b'):
            for move in catalogue_moves(side):
                with self.subTest(side=side, move=move):
                    start, end = parse_move(move)
                    self.assertTrue(XiangqiRules.is_legal_move(INITIAL_BOARD, start, end, side))

    def test_flip_and_names(self):
        self.assertEqual(flip_move_rank("h2e2"), "h7e7")
        self.assertEqual(opening_name(["h2d2"], 0), "Quá cung pháo")
        self.assertEqual(opening_name(["h2e2", "h7e7"], 1), "Thuận pháo")
        self.assertEqual(opening_name(["h2e2", "b7e7"], 1), "Nghịch pháo")
        self.assertEqual(opening_name(["c3c4", "h7e7"], 1), "Pháo đầu (hậu)")
        self.assertEqual(opening_name(["h2e2", "h9g7"], 1), "Lên mã")
        self.assertEqual(opening_name(["b2c2"], 0), "Khai cuộc tự do")
        self.assertIsNone(opening_name(["h2e2"], 1))
        self.assertIsNone(opening_name(["h2e2", "h9g7", "h0g2"], 2))
        self.assertTrue(is_mainstream_opening("h2e2", 'w'))
        self.assertTrue(is_mainstream_opening("h9g7", 'b'))
        self.assertFalse(is_mainstream_opening("e0e1", 'w'))
        self.assertEqual(len(set(OPENING_CATALOGUE)), len(OPENING_CATALOGUE))

    @staticmethod
    def lines(*entries, depth=16):
        return {i + 1: {'depth': depth, 'score': ('cp', cp), 'bound': None, 'pv': [mv, 'x']}
                for i, (mv, cp) in enumerate(entries)}

    class RecordingRng:
        def choice(self, pool):
            self.pool = sorted(info['pv'][0] for info in pool)
            return pool[0]

    def test_odd_picks_only_unusual_moves_within_threshold(self):
        candidates = self.lines(("h2e2", 20), ("h2d2", 8), ("h0i2", 0),
                                ("a3a4", 20 - ODD_MAX_LOSS_CP - 1), ("e3e4", -79))
        rng = self.RecordingRng()
        choose_style_move(candidates, 'w', STYLE_ODD, rng)
        self.assertEqual(rng.pool, ["h0i2", "h2d2"])

    def test_very_odd_prefers_bigger_deviations_then_falls_back(self):
        candidates = self.lines(("h2e2", 20), ("h2d2", 8), ("e3e4", -79), ("h2h9", -200))
        rng = self.RecordingRng()
        choose_style_move(candidates, 'w', STYLE_VERY_ODD, rng)
        self.assertEqual(rng.pool, ["e3e4"])
        rng = self.RecordingRng()
        choose_style_move(self.lines(("h2e2", 20), ("h2d2", 8)), 'w', STYLE_VERY_ODD, rng)
        self.assertEqual(rng.pool, ["h2d2"])

    def test_falls_back_to_best_move_when_every_unusual_move_is_bad(self):
        candidates = self.lines(("h9g7", -25), ("b9c7", -21), ("h7f7", -357), ("e9e8", -419))
        self.assertEqual(choose_style_move(candidates, 'b', STYLE_VERY_ODD)[0], "b9c7")

    def test_ignores_stale_lines_from_older_depths(self):
        candidates = self.lines(("h2e2", 20), ("h2d2", 8))
        candidates[3] = {'depth': 10, 'score': ('cp', 15), 'bound': None, 'pv': ['h0i2', 'x']}
        rng = self.RecordingRng()
        choose_style_move(candidates, 'w', STYLE_ODD, rng)
        self.assertEqual(rng.pool, ["h2d2"])

    def test_named_opening_choices(self):
        self.assertIn("• Tuần hà pháo", OPENING_STYLE_CHOICES)
        self.assertIn("• Tướng lên", OPENING_STYLE_CHOICES)
        self.assertEqual(named_opening_from_style("• Tướng lên"), "Tướng lên")
        self.assertIsNone(named_opening_from_style(STYLE_ODD))
        for name in NAMED_OPENINGS:
            with self.subTest(name=name):
                self.assertTrue(named_opening_candidates([], catalogue_moves('w'), name))
                self.assertTrue(named_opening_candidates(["h2e2"], catalogue_moves('b'), name))

    def test_named_opening_candidates(self):
        red, black = catalogue_moves('w'), catalogue_moves('b')
        self.assertEqual(sorted(named_opening_candidates([], red, "Tuần hà pháo")),
                         ["b2b4", "h2h4"])
        self.assertEqual(named_opening_candidates([], red, "Tướng lên"), ["e0e1"])
        self.assertEqual(named_opening_candidates(["h2e2"], black, "Tướng lên"), ["e9e8"])
        self.assertEqual(named_opening_candidates(["h2e2"], black, "Tuần hà pháo"),
                         ["h7h5", "b7b5"])
        # Thuận/Nghịch pháo phụ thuộc cột Pháo đầu của Đỏ.
        self.assertEqual(named_opening_candidates(["h2e2"], black, "Thuận pháo"), ["h7e7"])
        self.assertEqual(named_opening_candidates(["b2e2"], black, "Thuận pháo"), ["b7e7"])
        self.assertEqual(named_opening_candidates(["h2e2"], black, "Nghịch pháo"), ["b7e7"])
        # Không áp dụng được thì lùi về Pháo đầu.
        self.assertEqual(sorted(named_opening_candidates([], red, "Thuận pháo")),
                         ["b2e2", "h2e2"])
        self.assertEqual(sorted(named_opening_candidates(["c3c4"], black, "Nghịch pháo")),
                         ["b7e7", "h7e7"])
        # Tên gốc vẫn dùng được cho Đen dù tên hiển thị khác ("Khởi mã" -> "Lên mã").
        self.assertEqual(sorted(named_opening_candidates(["h2e2"], black, "Khởi mã")),
                         ["b9c7", "h9g7"])
        # Không có nước hợp lệ hoặc đã qua nước đầu.
        self.assertEqual(named_opening_candidates([], [], "Tướng lên"), [])
        self.assertEqual(named_opening_candidates(["h2e2", "h9g7"], red, "Tướng lên"), [])

    def test_opening_search_gets_enough_time(self):
        self.assertEqual(build_opening_go_command("1 giây / nước"), "go movetime 3000")
        self.assertEqual(build_opening_go_command("10 giây / nước"), "go movetime 10000")
        self.assertEqual(build_opening_go_command("Độ sâu 24"), "go movetime 5000")


def decode_png_rgba(png):
    """Giải mã PNG RGBA 8 bit không lọc (đúng định dạng encode_png_rgba tạo ra)."""
    assert png[:8] == b'\x89PNG\r\n\x1a\n'
    pos, idat, width, height = 8, b'', 0, 0
    while pos < len(png):
        length, tag = struct.unpack('>I4s', png[pos:pos + 8])
        data = png[pos + 8:pos + 8 + length]
        crc = struct.unpack('>I', png[pos + 8 + length:pos + 12 + length])[0]
        assert crc == zlib.crc32(tag + data) & 0xFFFFFFFF
        if tag == b'IHDR':
            width, height, depth, color_type = struct.unpack('>IIBB', data[:10])
            assert (depth, color_type) == (8, 6)
        elif tag == b'IDAT':
            idat += data
        pos += 12 + length
    raw = zlib.decompress(idat)
    stride = width * 4 + 1
    rows = [raw[y * stride + 1:(y + 1) * stride] for y in range(height)]
    assert all(raw[y * stride] == 0 for y in range(height))
    return width, height, rows


class GraphicsTests(unittest.TestCase):
    def test_png_roundtrip(self):
        pixels = bytes([255, 0, 0, 255, 0, 255, 0, 128, 0, 0, 255, 0, 9, 9, 9, 9])
        width, height, rows = decode_png_rgba(encode_png_rgba(2, 2, pixels))
        self.assertEqual((width, height), (2, 2))
        self.assertEqual(b''.join(rows), pixels)

    def test_piece_sprite_is_opaque_inside_and_clear_at_corner(self):
        radius = 20
        for side in ('w', 'b'):
            for lifted in (False, True):
                width, height, rows = decode_png_rgba(render_piece_png(radius, side, lifted))
                size = piece_sprite_size(radius, lifted)
                self.assertEqual((width, height), (size, size))
                center = rows[height // 2][(width // 2) * 4:(width // 2) * 4 + 4]
                self.assertEqual(center[3], 255)
                self.assertEqual(rows[0][3], 0)

    def test_panel_has_rounded_transparent_corners(self):
        width, height, rows = decode_png_rgba(render_panel_png(60, 30, 10, '#112233', 0.8))
        self.assertEqual(rows[0][3], 0)
        middle = rows[15][30 * 4:30 * 4 + 4]
        self.assertAlmostEqual(middle[3], round(0.8 * 255), delta=2)

    def test_eval_fraction(self):
        self.assertEqual(eval_fraction(('cp', 0)), 0.5)
        self.assertGreater(eval_fraction(('cp', 200)), 0.5)
        self.assertLess(eval_fraction(('cp', 200), flip=True), 0.5)
        self.assertEqual(eval_fraction(('mate', 3)), 1.0)
        self.assertEqual(eval_fraction(('mate', 3), flip=True), 0.0)
        self.assertEqual(eval_fraction(('mate', 0)), 0.0)
        self.assertEqual(eval_fraction(('mate', 0), flip=True), 1.0)


class SoundTests(unittest.TestCase):
    def test_every_sound_is_normalised_and_encodes_to_wav(self):
        for name in SOUND_NAMES:
            with self.subTest(name=name):
                samples = synth_sound(name)
                self.assertGreater(len(samples), SOUND_RATE // 20)
                self.assertLessEqual(max(abs(v) for v in samples), 1.0)
                with wave.open(io.BytesIO(samples_to_wav(samples))) as wav:
                    self.assertEqual(wav.getframerate(), SOUND_RATE)
                    self.assertEqual(wav.getsampwidth(), 2)
                    self.assertEqual(wav.getnframes(), len(samples))

    def test_unknown_sound_raises(self):
        with self.assertRaises(ValueError):
            synth_sound('nope')

    def test_ensure_sound_files_creates_and_reuses(self):
        with tempfile.TemporaryDirectory() as directory:
            files = ensure_sound_files(directory)
            self.assertEqual(set(files), set(SOUND_NAMES))
            mtimes = {name: path.stat().st_mtime_ns for name, path in files.items()}
            again = ensure_sound_files(directory)
            self.assertEqual({n: p.stat().st_mtime_ns for n, p in again.items()}, mtimes)


@unittest.skipUnless(os.name == 'nt' and ENGINE_PATH.exists(), "cần engine.exe trên Windows")
class EngineProtocolTests(unittest.TestCase):
    """Kiểm tra các giả định về giao thức UCI mà giao diện dựa vào."""

    def setUp(self):
        self.proc = subprocess.Popen(
            [str(ENGINE_PATH)], cwd=str(ENGINE_PATH.parent), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        self.lines = queue.Queue()
        threading.Thread(target=self._reader, daemon=True).start()
        self.send("uci")
        self.send("setoption name Hash value 64")
        self.send("setoption name Ponder value true")
        self.send("isready")
        self.wait_for(lambda line: line == "readyok")

    def tearDown(self):
        self.send("quit")
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.proc.stdin.close()
        self.proc.stdout.close()

    def _reader(self):
        try:
            for line in self.proc.stdout:
                self.lines.put(line.strip())
        except (OSError, ValueError):
            pass

    def send(self, command):
        self.proc.stdin.write(command + "\n")
        self.proc.stdin.flush()

    def wait_for(self, predicate, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                line = self.lines.get(timeout=0.1)
            except queue.Empty:
                continue
            if predicate(line):
                return line
        self.fail("engine không trả lời kịp")

    def test_position_with_move_list_gives_legal_reply(self):
        moves = ["h2e2", "h9g7", "h0g2"]
        self.send(f"position fen {START_FEN} moves " + " ".join(moves))
        self.send("go depth 8")
        best = self.wait_for(lambda line: line.startswith("bestmove")).split()[1]
        board = board_from_fen(START_FEN)
        side = 'w'
        for move in moves:
            side = play(board, side, move)
        start, end = parse_move(best)
        self.assertTrue(XiangqiRules.is_legal_move(board, start, end, side))

    def test_ponder_waits_for_ponderhit(self):
        self.send(f"position fen {START_FEN} moves h2e2 h9g7")
        self.send("go ponder depth 6")
        time.sleep(1.0)  # depth 6 xong rất nhanh, nhưng phải chờ ponderhit.
        seen = []
        while not self.lines.empty():
            seen.append(self.lines.get())
        self.assertFalse(any(line.startswith("bestmove") for line in seen))
        self.send("ponderhit")
        self.wait_for(lambda line: line.startswith("bestmove"))

    def test_stop_during_ponder_returns_exactly_one_bestmove(self):
        self.send(f"position fen {START_FEN} moves h2e2 h9g7")
        self.send("go ponder movetime 5000")
        time.sleep(0.3)
        self.send("stop")
        self.wait_for(lambda line: line.startswith("bestmove"))
        self.send("isready")
        seen = []
        line = None
        while line != "readyok":
            line = self.wait_for(lambda _line: True)
            seen.append(line)
        self.assertFalse(any(item.startswith("bestmove") for item in seen))


if __name__ == '__main__':
    unittest.main()
