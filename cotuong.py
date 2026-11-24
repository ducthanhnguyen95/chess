import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox
import array
import base64
import io
import subprocess
import struct
import sys
import tempfile
import threading
import copy
import os
import random # Thư viện để bốc ngẫu nhiên nước đi trong Book
import math
import queue
import time
import wave
import zlib
from collections import deque
from pathlib import Path

try:
    import winsound
except ImportError:  # Cho phép phần luật chạy trên hệ điều hành không phải Windows.
    winsound = None


class XiangqiRules:
    """Luật cờ tướng độc lập với giao diện và engine."""

    @staticmethod
    def side_of(piece):
        if piece == '.':
            return None
        return 'w' if piece.isupper() else 'b'

    @staticmethod
    def opponent(side):
        return 'b' if side == 'w' else 'w'

    @staticmethod
    def in_palace(side, row, col):
        if not (3 <= col <= 5):
            return False
        return 7 <= row <= 9 if side == 'w' else 0 <= row <= 2

    @staticmethod
    def count_between(board, start, end):
        sr, sc = start
        er, ec = end
        if sr == er:
            step = 1 if ec > sc else -1
            return sum(board[sr][c] != '.' for c in range(sc + step, ec, step))
        if sc == ec:
            step = 1 if er > sr else -1
            return sum(board[r][sc] != '.' for r in range(sr + step, er, step))
        return -1

    @classmethod
    def piece_can_move(cls, board, start, end):
        """Kiểm tra cách đi của quân, chưa xét việc tự đưa Tướng vào chiếu."""
        sr, sc = start
        er, ec = end
        piece = board[sr][sc]
        if piece == '.' or start == end:
            return False

        side = cls.side_of(piece)
        dr, dc = er - sr, ec - sc
        adr, adc = abs(dr), abs(dc)
        kind = piece.upper()

        if kind == 'R':
            return (sr == er or sc == ec) and cls.count_between(board, start, end) == 0

        if kind == 'N':
            if (adr, adc) not in ((2, 1), (1, 2)):
                return False
            if adr == 2:
                leg = (sr + (1 if dr > 0 else -1), sc)
            else:
                leg = (sr, sc + (1 if dc > 0 else -1))
            return board[leg[0]][leg[1]] == '.'

        if kind == 'B':
            if (adr, adc) != (2, 2):
                return False
            # Tượng không được qua sông.
            if side == 'w' and er < 5:
                return False
            if side == 'b' and er > 4:
                return False
            return board[(sr + er) // 2][(sc + ec) // 2] == '.'

        if kind == 'A':
            return (adr, adc) == (1, 1) and cls.in_palace(side, er, ec)

        if kind == 'K':
            # Hai Tướng có thể "nhìn mặt" và chiếu nhau trên cùng một cột.
            target = board[er][ec]
            if (target.upper() == 'K' and cls.side_of(target) != side
                    and sc == ec and cls.count_between(board, start, end) == 0):
                return True
            return adr + adc == 1 and cls.in_palace(side, er, ec)

        if kind == 'C':
            if sr != er and sc != ec:
                return False
            screens = cls.count_between(board, start, end)
            if board[er][ec] == '.':
                return screens == 0
            return screens == 1

        if kind == 'P':
            forward = -1 if side == 'w' else 1
            if dr == forward and dc == 0:
                return True
            crossed_river = sr <= 4 if side == 'w' else sr >= 5
            return crossed_river and dr == 0 and adc == 1

        return False

    @classmethod
    def find_king(cls, board, side):
        wanted = 'K' if side == 'w' else 'k'
        for row in range(10):
            for col in range(9):
                if board[row][col] == wanted:
                    return row, col
        return None

    @classmethod
    def is_in_check(cls, board, side):
        king = cls.find_king(board, side)
        if king is None:
            return True
        enemy = cls.opponent(side)
        for row in range(10):
            for col in range(9):
                if cls.side_of(board[row][col]) == enemy:
                    if cls.piece_can_move(board, (row, col), king):
                        return True
        return False

    @classmethod
    def is_legal_move(cls, board, start, end, side):
        sr, sc = start
        er, ec = end
        if not (0 <= sr < 10 and 0 <= er < 10 and 0 <= sc < 9 and 0 <= ec < 9):
            return False

        source = board[sr][sc]
        target = board[er][ec]
        if cls.side_of(source) != side or cls.side_of(target) == side:
            return False
        # Ván phải kết thúc bằng chiếu bí/hết nước, không cho bắt Tướng trực tiếp.
        if target.upper() == 'K':
            return False
        if not cls.piece_can_move(board, start, end):
            return False

        next_board = copy.deepcopy(board)
        next_board[er][ec] = source
        next_board[sr][sc] = '.'
        return not cls.is_in_check(next_board, side)

    @classmethod
    def legal_moves(cls, board, side):
        moves = []
        for sr in range(10):
            for sc in range(9):
                if cls.side_of(board[sr][sc]) != side:
                    continue
                for er in range(10):
                    for ec in range(9):
                        if cls.is_legal_move(board, (sr, sc), (er, ec), side):
                            moves.append(((sr, sc), (er, ec)))
        return moves

    @classmethod
    def game_result(cls, board, side_to_move):
        if cls.legal_moves(board, side_to_move):
            return None
        reason = 'checkmate' if cls.is_in_check(board, side_to_move) else 'stalemate'
        return reason, cls.opponent(side_to_move)

    # 60 nước mỗi bên (120 nửa nước) không ăn quân thì xử hòa, giống Pikafish.
    RULE60_PLIES = 120

    @classmethod
    def rule60_result(cls, halfmove_clock):
        """Trả về ('rule60', None) khi đủ 60 nước không ăn quân, ngược lại None.

        Theo yêu cầu, trọng tài KHÔNG xử lặp nước (hòa) hay chiếu dai (thua):
        dù thế cờ lặp lại bao nhiêu lần, ván vẫn tiếp tục.
        """
        if halfmove_clock >= cls.RULE60_PLIES:
            return 'rule60', None
        return None


# ---------------------------------------------------------------------------
# Giao tiếp UCI: các hàm thuần, không phụ thuộc giao diện để dễ kiểm thử.
# ---------------------------------------------------------------------------

# (nhãn hiển thị, loại giới hạn, giá trị). Thời gian tính bằng mili giây.
SEARCH_LIMITS = [
    ("1 giây / nước", "movetime", 1000),
    ("3 giây / nước", "movetime", 3000),
    ("5 giây / nước", "movetime", 5000),
    ("10 giây / nước", "movetime", 10000),
    ("30 giây / nước", "movetime", 30000),
    ("Độ sâu 16", "depth", 16),
    ("Độ sâu 20", "depth", 20),
    ("Độ sâu 24", "depth", 24),
    ("Độ sâu 28", "depth", 28),
]
DEFAULT_SEARCH_LIMIT = "5 giây / nước"
# Chế độ độ sâu vẫn có trần thời gian để máy không nghĩ hàng chục phút.
DEPTH_MODE_TIME_CAP_MS = 180000

# Pikafish thỉnh thoảng crash (0xC0000005) ở lượt tìm MultiPV lớn + searchmoves
# của khai cuộc Lạ/Rất lạ. Khi đó GUI tự mở lại engine và tính lại nước, nhưng
# chỉ tối đa ENGINE_RESTART_LIMIT lần trong ENGINE_RESTART_WINDOW giây để
# không lặp vô hạn nếu engine hỏng thật (thiếu RAM, file .nnue lỗi...).
ENGINE_RESTART_LIMIT = 3
ENGINE_RESTART_WINDOW = 60.0


def engine_restart_allowed(crash_times, now):
    """-> (được khởi động lại không, danh sách thời điểm crash còn trong cửa sổ)."""
    recent = [t for t in crash_times if now - t < ENGINE_RESTART_WINDOW]
    return len(recent) < ENGINE_RESTART_LIMIT, recent

# Đa dạng khai cuộc: trong bấy nhiêu nửa nước đầu, chọn ngẫu nhiên trong các
# nước tốt nhất của engine mà điểm kém nước tốt nhất không quá ngưỡng.
VARIETY_PLIES = 12
VARIETY_MULTIPV = 3
VARIETY_THRESHOLD_CP = 20

MATE_SCORE_CP = 100000


def find_search_limit(label):
    for item in SEARCH_LIMITS:
        if item[0] == label:
            return item
    return next(item for item in SEARCH_LIMITS if item[0] == DEFAULT_SEARCH_LIMIT)


def search_limit_short(label):
    _label, kind, value = find_search_limit(label)
    return f"{value // 1000}s" if kind == "movetime" else f"D{value}"


def build_go_command(label, ponder=False):
    _label, kind, value = find_search_limit(label)
    prefix = "go ponder" if ponder else "go"
    if kind == "movetime":
        return f"{prefix} movetime {value}"
    return f"{prefix} depth {value} movetime {DEPTH_MODE_TIME_CAP_MS}"


def parse_uci_info(line):
    """Đọc dòng 'info ... score ...'. Trả về dict hoặc None nếu không có điểm."""
    parts = line.split()
    if not parts or parts[0] != "info" or "score" not in parts:
        return None
    info = {'depth': None, 'multipv': 1, 'score': None, 'bound': None, 'pv': []}
    i = 1
    try:
        while i < len(parts):
            token = parts[i]
            if token == "depth":
                info['depth'] = int(parts[i + 1])
                i += 2
            elif token == "multipv":
                info['multipv'] = int(parts[i + 1])
                i += 2
            elif token == "score":
                kind = parts[i + 1]
                if kind not in ("cp", "mate"):
                    return None
                info['score'] = (kind, int(parts[i + 2]))
                i += 3
                if i < len(parts) and parts[i] in ("lowerbound", "upperbound"):
                    info['bound'] = parts[i]
                    i += 1
            elif token == "pv":
                info['pv'] = parts[i + 1:]
                break
            elif token == "string":
                return None
            else:
                i += 1
    except (IndexError, ValueError):
        return None
    if info['score'] is None or info['depth'] is None:
        return None
    return info


def score_to_cp(score):
    """Quy điểm về centipawn để so sánh; chiếu bí được coi là rất lớn."""
    kind, value = score
    if kind == "cp":
        return value
    if value > 0:
        return MATE_SCORE_CP - value
    return -MATE_SCORE_CP - value


def format_score(score, flip=False):
    """Hiển thị điểm theo góc nhìn bên Đỏ: '+0.31', '-1.20', '+M3', '-M5'."""
    kind, value = score
    if flip:
        value = -value
    if kind == "mate":
        # mate 0 nghĩa là bên đang đi đã bị chiếu bí.
        if value == 0:
            return "-M0" if not flip else "+M0"
        return f"{'+' if value > 0 else '-'}M{abs(value)}"
    pawns = value / 100.0
    sign = "+" if pawns > 0 else ""
    return f"{sign}{pawns:.2f}"


def choose_varied_move(candidates, threshold_cp, rng=random):
    """Chọn ngẫu nhiên một PV trong các dòng MultiPV gần bằng nước tốt nhất.

    candidates: {multipv: info} lấy từ parse_uci_info (chỉ các dòng không bound).
    Trả về danh sách nước của PV được chọn, hoặc None nếu không đủ dữ liệu.
    """
    best = candidates.get(1)
    if not best or not best['pv']:
        return None
    best_cp = score_to_cp(best['score'])
    pool = [
        info['pv'] for info in candidates.values()
        if info['pv'] and info['depth'] == best['depth']
        and score_to_cp(info['score']) >= best_cp - threshold_cp
    ]
    return rng.choice(pool) if pool else best['pv']


# ---------------------------------------------------------------------------
# Phong cách khai cuộc: cho máy đi những khai cuộc lạ ở nước đầu của mỗi bên,
# nhưng luôn để Pikafish chấm điểm và chỉ chọn nước lạ không mất quá ngưỡng.
# ---------------------------------------------------------------------------

STYLE_STANDARD = "Chuẩn"
STYLE_VARIED = "Đa dạng"
STYLE_ODD = "Lạ"
STYLE_VERY_ODD = "Rất lạ"
OPENING_STYLES = [STYLE_STANDARD, STYLE_VARIED, STYLE_ODD, STYLE_VERY_ODD]

# Mất tối đa bấy nhiêu centipawn so với nước tốt nhất (đo bằng Pikafish).
ODD_MAX_LOSS_CP = 40
VERY_ODD_MAX_LOSS_CP = 130
# Lượt tìm kiếm chấm điểm khai cuộc dùng MultiPV nhiều dòng nên cần đủ thời gian.
OPENING_SEARCH_MIN_MS = 3000
OPENING_SEARCH_DEPTH_MODE_MS = 5000

# Nước đầu tiên viết theo góc nhìn bên Đỏ; nước của Đen được lật hàng rồi tra.
OPENING_CATALOGUE = {
    'h2e2': "Pháo đầu", 'b2e2': "Pháo đầu",
    'c3c4': "Tiên nhân chỉ lộ", 'g3g4': "Tiên nhân chỉ lộ",
    'c0e2': "Phi tượng", 'g0e2': "Phi tượng",
    'h0g2': "Khởi mã", 'b0c2': "Khởi mã",
    'h2f2': "Sĩ giác pháo", 'b2d2': "Sĩ giác pháo",
    'h2d2': "Quá cung pháo", 'b2f2': "Quá cung pháo",
    'h2h4': "Tuần hà pháo", 'b2b4': "Tuần hà pháo",
    'h2i2': "Biên pháo", 'b2a2': "Biên pháo",
    'e3e4': "Trung binh",
    'a3a4': "Biên binh", 'i3i4': "Biên binh",
    'h0i2': "Biên mã", 'b0a2': "Biên mã",
    'i0i1': "Hoành xa", 'a0a1': "Hoành xa",
    'd0e1': "Thượng sĩ", 'f0e1': "Thượng sĩ",
    'e0e1': "Tướng lên",
    'h2h9': "Pháo đổi mã", 'b2b9': "Pháo đổi mã",
}
MAINSTREAM_OPENINGS = {"Pháo đầu", "Tiên nhân chỉ lộ", "Phi tượng", "Khởi mã"}
# Tên gọi riêng khi Đen đi các nước tương ứng.
BLACK_OPENING_NAMES = {
    "Pháo đầu": "Pháo đầu (hậu)",
    "Tiên nhân chỉ lộ": "Tiến tốt 3/7",
    "Khởi mã": "Lên mã",
    "Trung binh": "Trung tốt",
    "Biên binh": "Biên tốt",
}


def flip_move_rank(move):
    """Lật hàng của nước đi (góc Đen <-> góc Đỏ), giữ nguyên cột."""
    return f"{move[0]}{9 - int(move[1])}{move[2]}{9 - int(move[3])}"


def catalogue_name(move, side):
    key = move if side == 'w' else flip_move_rank(move)
    return OPENING_CATALOGUE.get(key)


def is_mainstream_opening(move, side):
    return catalogue_name(move, side) in MAINSTREAM_OPENINGS


def catalogue_moves(side):
    """Các nước đầu trong danh mục, đã đổi sang góc của bên cần đi."""
    if side == 'w':
        return list(OPENING_CATALOGUE)
    return [flip_move_rank(move) for move in OPENING_CATALOGUE]


def opening_name(moves, ply):
    """Tên khai cuộc của nước thứ ply (0 = nước đầu của Đỏ, 1 = của Đen)."""
    if ply > 1 or ply >= len(moves):
        return None
    side = 'w' if ply == 0 else 'b'
    move = moves[ply]
    name = catalogue_name(move, side)
    if name is None:
        return "Khai cuộc tự do"
    if side == 'w':
        return name
    if name == "Pháo đầu" and catalogue_name(moves[0], 'w') == "Pháo đầu":
        # Hai Pháo đầu cùng phía cột là Thuận pháo, khác phía là Nghịch pháo.
        return "Thuận pháo" if move[0] == moves[0][0] else "Nghịch pháo"
    return BLACK_OPENING_NAMES.get(name, name)


# Khai cuộc chọn đích danh: nước đầu của máy (Đỏ hay Đen) bắt buộc là khai cuộc này.
NAMED_OPENING_PREFIX = "• "
SAME_SIDE_CANNON = "Thuận pháo"
OPPOSITE_SIDE_CANNON = "Nghịch pháo"
NAMED_OPENINGS = (["Pháo đầu", SAME_SIDE_CANNON, OPPOSITE_SIDE_CANNON]
                  + [name for name in dict.fromkeys(OPENING_CATALOGUE.values())
                     if name != "Pháo đầu"])
OPENING_STYLE_CHOICES = OPENING_STYLES + [NAMED_OPENING_PREFIX + name for name in NAMED_OPENINGS]


def named_opening_from_style(style):
    """'• Tuần hà pháo' -> 'Tuần hà pháo'; các phong cách chung -> None."""
    if style.startswith(NAMED_OPENING_PREFIX):
        return style[len(NAMED_OPENING_PREFIX):]
    return None


def named_opening_candidates(moves, legal_moves, name):
    """Các nước (trong legal_moves) tạo ra khai cuộc tên name ở nước kế tiếp.

    Ưu tiên khớp đúng tên hiển thị (vd. Thuận pháo); nếu không có thì khớp theo
    danh mục gốc (Đen đi "Khởi mã" là "Lên mã"; Thuận/Nghịch pháo khi không áp
    dụng được thì lùi về Pháo đầu).
    """
    ply = len(moves)
    if ply > 1:
        return []
    side = 'w' if ply == 0 else 'b'
    exact = [m for m in legal_moves if opening_name(moves + [m], ply) == name]
    if exact:
        return exact
    base = "Pháo đầu" if name in (SAME_SIDE_CANNON, OPPOSITE_SIDE_CANNON) else name
    return [m for m in legal_moves if catalogue_name(m, side) == base]


def build_opening_go_command(label):
    _label, kind, value = find_search_limit(label)
    if kind == "movetime":
        return f"go movetime {max(OPENING_SEARCH_MIN_MS, value)}"
    return f"go movetime {OPENING_SEARCH_DEPTH_MODE_MS}"


def choose_style_move(candidates, side, style, rng=random):
    """Chọn nước khai cuộc lạ từ các dòng MultiPV đã chấm điểm.

    - Lạ: nước ngoài nhóm khai cuộc phổ biến, mất không quá ODD_MAX_LOSS_CP.
    - Rất lạ: ưu tiên nước mất từ ODD_MAX_LOSS_CP tới VERY_ODD_MAX_LOSS_CP;
      không có thì lùi về mức Lạ.
    Không có nước lạ nào đủ an toàn thì trả về nước tốt nhất của engine.
    """
    best = candidates.get(1)
    if not best or not best['pv']:
        return None
    lines = [info for info in candidates.values()
             if info['pv'] and info['depth'] >= best['depth'] - 1]
    best_cp = max(score_to_cp(info['score']) for info in lines)

    def loss(info):
        return best_cp - score_to_cp(info['score'])

    odd = [info for info in lines if not is_mainstream_opening(info['pv'][0], side)]
    mild = [info for info in odd if loss(info) <= ODD_MAX_LOSS_CP]
    wild = [info for info in odd
            if ODD_MAX_LOSS_CP < loss(info) <= VERY_ODD_MAX_LOSS_CP]
    pool = (wild or mild) if style == STYLE_VERY_ODD else mild
    if not pool:
        return max(lines, key=lambda info: score_to_cp(info['score']))['pv']
    return rng.choice(pool)['pv']


def recommended_hash_mb(total_ram_mb=None, cap_mb=2048):
    """Hash bằng khoảng 1/8 RAM, làm tròn xuống lũy thừa của 2, trong [64, cap]."""
    if total_ram_mb is None:
        total_ram_mb = total_physical_memory_mb()
    if not total_ram_mb:
        return 256
    target = max(64, min(cap_mb, total_ram_mb // 8))
    size = 64
    while size * 2 <= target:
        size *= 2
    return size


def total_physical_memory_mb():
    try:
        if os.name == 'nt':
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ('dwLength', ctypes.c_ulong),
                    ('dwMemoryLoad', ctypes.c_ulong),
                    ('ullTotalPhys', ctypes.c_ulonglong),
                    ('ullAvailPhys', ctypes.c_ulonglong),
                    ('ullTotalPageFile', ctypes.c_ulonglong),
                    ('ullAvailPageFile', ctypes.c_ulonglong),
                    ('ullTotalVirtual', ctypes.c_ulonglong),
                    ('ullAvailVirtual', ctypes.c_ulonglong),
                    ('ullAvailExtendedVirtual', ctypes.c_ulonglong),
                ]

            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return status.ullTotalPhys // (1024 * 1024)
            return None
        return os.sysconf('SC_PAGE_SIZE') * os.sysconf('SC_PHYS_PAGES') // (1024 * 1024)
    except (AttributeError, ValueError, OSError):
        return None


def eval_fraction(score, flip=False):
    """Tỷ lệ thanh ưu thế (0 = Đen thắng hẳn, 1 = Đỏ thắng hẳn)."""
    kind, value = score
    if flip:
        value = -value
    if kind == "mate":
        if value == 0:
            # Bên đang đi bị chiếu bí: flip=True nghĩa là Đen đang đi.
            return 1.0 if flip else 0.0
        return 1.0 if value > 0 else 0.0
    return 0.5 + 0.5 * math.tanh(value / 600.0)


# ---------------------------------------------------------------------------
# Đồ họa: Tk trên Windows không khử răng cưa hình tròn, nên quân cờ và hiệu ứng
# được vẽ thành ảnh RGBA bằng Python thuần (độ phủ tính từ khoảng cách) rồi
# mã hóa PNG để tk.PhotoImage hiển thị, có cả độ trong suốt mềm.
# ---------------------------------------------------------------------------

def encode_png_rgba(width, height, rgba):
    stride = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw.extend(rgba[y * stride:(y + 1) * stride])

    def chunk(tag, data):
        return (struct.pack('>I', len(data)) + tag + data
                + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF))

    header = struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header)
            + chunk(b'IDAT', zlib.compress(bytes(raw), 6)) + chunk(b'IEND', b''))


def hex_to_rgb(color):
    color = color.lstrip('#')
    return tuple(int(color[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return '#' + ''.join(f"{max(0, min(255, round(c * 255))):02X}" for c in rgb)


def mix_rgb(a, b, t):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def mix_hex(a, b, t):
    return rgb_to_hex(mix_rgb(hex_to_rgb(a), hex_to_rgb(b), max(0.0, min(1.0, t))))


def _clamp01(value):
    return 0.0 if value < 0.0 else 1.0 if value > 1.0 else value


def _smoothstep(edge0, edge1, x):
    t = _clamp01((x - edge0) / (edge1 - edge0))
    return t * t * (3.0 - 2.0 * t)


def ease_out_cubic(t):
    return 1.0 - (1.0 - t) ** 3


def ease_in_out_cubic(t):
    return 4.0 * t * t * t if t < 0.5 else 1.0 - (-2.0 * t + 2.0) ** 3 / 2.0


class SpriteBuffer:
    """Bộ đệm RGBA (premultiplied). Mỗi lớp vẽ bằng shader(x, y) -> (r, g, b, a)."""

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.data = [0.0] * (width * height * 4)

    def paint(self, shader, box=None):
        x0, y0, x1, y1 = box or (0, 0, self.width, self.height)
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1 = min(self.width, int(math.ceil(x1)))
        y1 = min(self.height, int(math.ceil(y1)))
        data = self.data
        for py in range(y0, y1):
            cy = py + 0.5
            base = py * self.width
            for px in range(x0, x1):
                result = shader(px + 0.5, cy)
                if result is None:
                    continue
                r, g, b, a = result
                if a <= 0.0:
                    continue
                if a > 1.0:
                    a = 1.0
                j = (base + px) * 4
                inv = 1.0 - a
                data[j] = r * a + data[j] * inv
                data[j + 1] = g * a + data[j + 1] * inv
                data[j + 2] = b * a + data[j + 2] * inv
                data[j + 3] = a + data[j + 3] * inv

    def to_png(self):
        data = self.data
        out = bytearray(len(data))
        for i in range(0, len(data), 4):
            a = data[i + 3]
            if a <= 0.0:
                continue
            out[i] = min(255, int(data[i] / a * 255 + 0.5))
            out[i + 1] = min(255, int(data[i + 1] / a * 255 + 0.5))
            out[i + 2] = min(255, int(data[i + 2] / a * 255 + 0.5))
            out[i + 3] = min(255, int(a * 255 + 0.5))
        return encode_png_rgba(self.width, self.height, out)


PIECE_FACE_LIGHT = hex_to_rgb('#FFF9EC')
PIECE_FACE_DARK = hex_to_rgb('#E6CB98')
PIECE_RIM_LIGHT = hex_to_rgb('#EDCD93')
PIECE_RIM_DARK = hex_to_rgb('#8A5E31')
PIECE_SHADOW = hex_to_rgb('#2A1606')
PIECE_INK = {'w': '#B3261E', 'b': '#18222D'}
PIECE_GLYPHS = {
    'R': '車', 'N': '傌', 'B': '相', 'A': '仕', 'K': '帥', 'C': '炮', 'P': '兵',
    'r': '車', 'n': '馬', 'b': '象', 'a': '士', 'k': '將', 'c': '砲', 'p': '卒',
}


def piece_sprite_size(radius, lifted=False):
    return 2 * int(math.ceil(radius * (1.8 if lifted else 1.5)))


def render_piece_png(radius, side, lifted=False):
    """Quân cờ gỗ ngà: bóng đổ mềm, gờ vát nổi, vòng khắc màu theo phe.

    Tâm ảnh trùng tâm quân; chữ được vẽ bằng font của Tk đè lên trên.
    """
    size = piece_sprite_size(radius, lifted)
    c = size / 2.0
    R = radius
    buf = SpriteBuffer(size, size)

    off_x, off_y = (0.12 * R, 0.36 * R) if lifted else (0.05 * R, 0.14 * R)
    blur = (0.45 if lifted else 0.22) * R
    shadow_alpha = 0.32 if lifted else 0.48
    sx, sy = c + off_x, c + off_y
    sr, sg, sb = PIECE_SHADOW

    def shadow(x, y):
        d = math.hypot(x - sx, y - sy)
        a = shadow_alpha * (1.0 - _smoothstep(R - blur, R + blur, d))
        return (sr, sg, sb, a) if a > 0.003 else None

    buf.paint(shadow)

    ink = hex_to_rgb(PIECE_INK[side])
    ring_r = 0.78 * R
    ring_hw = max(0.65, 0.045 * R)
    hx, hy = c - 0.32 * R, c - 0.38 * R

    def body(x, y):
        dx, dy = x - c, y - c
        d = math.hypot(dx, dy)
        cov = R - d + 0.5
        if cov <= 0.0:
            return None
        light = _clamp01(0.5 - (dx * 0.6 + dy * 0.8) / (2.0 * R))
        hd = math.hypot(x - hx, y - hy)
        col = mix_rgb(PIECE_FACE_LIGHT, PIECE_FACE_DARK, _clamp01(hd / (1.55 * R)))
        rim_t = _smoothstep(0.83 * R, 0.92 * R, d)
        if rim_t > 0.0:
            col = mix_rgb(col, mix_rgb(PIECE_RIM_DARK, PIECE_RIM_LIGHT, light), rim_t)
        ring = _clamp01(ring_hw - abs(d - ring_r) + 0.5)
        if ring > 0.0:
            col = mix_rgb(col, ink, ring * 0.92)
        spec = 0.30 * (1.0 - _smoothstep(0.0, 0.6 * R, hd)) * (1.0 - rim_t)
        if spec > 0.0:
            col = mix_rgb(col, (1.0, 1.0, 1.0), spec)
        return (col[0], col[1], col[2], min(1.0, cov))

    buf.paint(body, (c - R - 1, c - R - 1, c + R + 2, c + R + 2))
    return buf.to_png()


def render_glow_png(radius, color, alpha, inner=0.0):
    """Quầng sáng tròn mờ dần ra ngoài (inner: phần lõi giữ nguyên độ đậm)."""
    size = 2 * int(math.ceil(radius)) + 2
    c = size / 2.0
    r, g, b = hex_to_rgb(color)
    core = inner * radius
    buf = SpriteBuffer(size, size)

    def shader(x, y):
        d = math.hypot(x - c, y - c)
        if d >= radius:
            return None
        if d <= core:
            return (r, g, b, alpha)
        t = (d - core) / (radius - core)
        return (r, g, b, alpha * (1.0 - _smoothstep(0.0, 1.0, t)))

    buf.paint(shader)
    return buf.to_png()


def render_ring_png(radius, width, color, alpha, glow=0.0):
    """Vòng tròn khử răng cưa, có thể kèm quầng sáng mềm hai bên."""
    spread = glow * radius
    size = 2 * int(math.ceil(radius + width + spread)) + 2
    c = size / 2.0
    r, g, b = hex_to_rgb(color)
    half = width / 2.0
    buf = SpriteBuffer(size, size)

    def shader(x, y):
        edge = abs(math.hypot(x - c, y - c) - radius)
        a = alpha * _clamp01(half - edge + 0.5)
        if spread > 0.0:
            a = max(a, alpha * 0.45 * (1.0 - _smoothstep(0.0, spread, edge - half)))
        return (r, g, b, a) if a > 0.003 else None

    buf.paint(shader)
    return buf.to_png()


def render_dot_png(radius, color, alpha):
    size = 2 * int(math.ceil(radius)) + 2
    c = size / 2.0
    r, g, b = hex_to_rgb(color)
    buf = SpriteBuffer(size, size)

    def shader(x, y):
        cov = radius - math.hypot(x - c, y - c) + 0.5
        return (r, g, b, alpha * min(1.0, cov)) if cov > 0.0 else None

    buf.paint(shader)
    return buf.to_png()


def render_panel_png(width, height, radius, fill, alpha, border=None,
                     border_alpha=1.0, border_width=1.0):
    """Hình chữ nhật bo góc bán trong suốt (banner kết quả, thông báo)."""
    fr, fg, fb = hex_to_rgb(fill)
    br, bg, bb = hex_to_rgb(border) if border else (0.0, 0.0, 0.0)
    hw, hh = width / 2.0, height / 2.0
    radius = min(radius, hw, hh)
    buf = SpriteBuffer(width, height)

    def shader(x, y):
        qx = abs(x - hw) - (hw - radius)
        qy = abs(y - hh) - (hh - radius)
        d = (math.hypot(max(qx, 0.0), max(qy, 0.0))
             + min(max(qx, qy), 0.0) - radius)
        cov = _clamp01(0.5 - d)
        if cov <= 0.0:
            return None
        shade = 0.07 * (1.0 - y / height)
        r, g, b = fr + (1 - fr) * shade, fg + (1 - fg) * shade, fb + (1 - fb) * shade
        a = alpha
        if border:
            band = _clamp01(border_width - abs(d + border_width / 2.0) + 0.5)
            if band > 0.0:
                t = band * border_alpha
                r, g, b = r + (br - r) * t, g + (bg - g) * t, b + (bb - b) * t
                a = a + (1.0 - a) * t
        return (r, g, b, a * cov)

    buf.paint(shader)
    return buf.to_png()


# ---------------------------------------------------------------------------
# Âm thanh: tổng hợp bằng Python thuần (gõ gỗ, chuông FM), ghi WAV vào thư mục
# tạm một lần rồi phát bất đồng bộ bằng winsound.PlaySound.
# ---------------------------------------------------------------------------

SOUND_RATE = 22050
SOUND_VERSION = 1
SOUND_NAMES = ('select', 'move', 'capture', 'invalid', 'check', 'victory', 'draw', 'start')


def _silence(seconds):
    return [0.0] * int(seconds * SOUND_RATE)


def _add_knock(buf, start, pitch, gain, rng):
    """Tiếng quân gỗ đặt xuống bàn: vài mode cộng hưởng tắt nhanh + tiếng tách."""
    f0 = 360.0 * pitch
    modes = ((f0, 42.0, 1.0), (f0 * 2.71, 62.0, 0.55),
             (f0 * 5.19, 95.0, 0.26), (f0 * 0.43, 30.0, 0.55))
    i0 = int(start * SOUND_RATE)
    length = min(len(buf) - i0, int(0.22 * SOUND_RATE))
    click_len = int(0.006 * SOUND_RATE)
    lowpass = 0.0
    two_pi = 2.0 * math.pi
    for k in range(length):
        t = k / SOUND_RATE
        v = 0.0
        for freq, decay, amp in modes:
            v += amp * math.exp(-decay * t) * math.sin(two_pi * freq * t)
        if k < click_len:
            lowpass += 0.55 * (rng.uniform(-1.0, 1.0) - lowpass)
            v += lowpass * 1.8 * (1.0 - k / click_len)
        buf[i0 + k] += gain * v * min(1.0, k / 12.0 + 0.2)


def _add_bell(buf, start, freq, gain, decay):
    """Chuông FM ngắn, sáng."""
    i0 = int(start * SOUND_RATE)
    length = min(len(buf) - i0, int(min(6.0 / decay, 2.5) * SOUND_RATE))
    two_pi = 2.0 * math.pi
    for k in range(length):
        t = k / SOUND_RATE
        env = math.exp(-decay * t) * min(1.0, t / 0.004)
        mod = 1.8 * math.exp(-6.0 * t) * math.sin(two_pi * freq * 1.4 * t)
        v = math.sin(two_pi * freq * t + mod)
        v += 0.25 * math.exp(-7.0 * t) * math.sin(two_pi * freq * 2.01 * t)
        buf[i0 + k] += gain * env * v


def _add_tone(buf, start, freq, gain, duration):
    i0 = int(start * SOUND_RATE)
    length = min(len(buf) - i0, int(duration * SOUND_RATE))
    two_pi = 2.0 * math.pi
    for k in range(length):
        t = k / SOUND_RATE
        env = min(1.0, t / 0.008) * math.exp(-5.0 * t / duration)
        buf[i0 + k] += gain * env * (math.sin(two_pi * freq * t)
                                     + 0.2 * math.sin(two_pi * freq * 2 * t))


def _finish_sound(buf, peak):
    top = max((abs(v) for v in buf), default=0.0) or 1.0
    scale = peak / top
    fade = min(len(buf), int(0.012 * SOUND_RATE))
    out = [v * scale for v in buf]
    for k in range(fade):
        out[len(out) - 1 - k] *= k / fade
    return out


def synth_sound(name):
    """Trả về danh sách mẫu float trong [-1, 1] cho hiệu ứng âm thanh."""
    rng = random.Random(sum(map(ord, name)))
    if name == 'select':
        buf = _silence(0.12)
        _add_knock(buf, 0.0, 2.4, 1.0, rng)
        return _finish_sound(buf, 0.22)
    if name == 'move':
        buf = _silence(0.28)
        _add_knock(buf, 0.0, 1.0, 1.0, rng)
        return _finish_sound(buf, 0.75)
    if name == 'capture':
        buf = _silence(0.36)
        _add_knock(buf, 0.0, 0.82, 1.0, rng)
        _add_knock(buf, 0.05, 1.38, 0.75, rng)
        return _finish_sound(buf, 0.85)
    if name == 'invalid':
        buf = _silence(0.32)
        _add_tone(buf, 0.0, 233.0, 1.0, 0.12)
        _add_tone(buf, 0.11, 175.0, 1.0, 0.18)
        return _finish_sound(buf, 0.28)
    if name == 'check':
        buf = _silence(0.8)
        _add_bell(buf, 0.0, 987.8, 1.0, 5.0)
        _add_bell(buf, 0.12, 1318.5, 1.0, 4.5)
        return _finish_sound(buf, 0.5)
    if name == 'victory':
        buf = _silence(1.9)
        for i, freq in enumerate((523.25, 659.25, 783.99, 1046.5)):
            _add_bell(buf, i * 0.12, freq, 1.0, 3.2)
        for freq in (523.25, 659.25, 783.99):
            _add_bell(buf, 0.55, freq, 0.55, 2.2)
        return _finish_sound(buf, 0.55)
    if name == 'draw':
        buf = _silence(1.2)
        _add_bell(buf, 0.0, 659.25, 1.0, 3.0)
        _add_bell(buf, 0.2, 523.25, 1.0, 2.6)
        return _finish_sound(buf, 0.45)
    if name == 'start':
        buf = _silence(0.5)
        _add_knock(buf, 0.0, 1.6, 0.5, rng)
        _add_knock(buf, 0.06, 1.2, 0.6, rng)
        _add_knock(buf, 0.13, 1.9, 0.4, rng)
        _add_bell(buf, 0.19, 1567.98, 0.35, 6.0)
        return _finish_sound(buf, 0.45)
    raise ValueError(f"Không có âm thanh '{name}'")


def samples_to_wav(samples):
    pcm = array.array('h', (int(max(-1.0, min(1.0, v)) * 32767) for v in samples))
    if pcm.itemsize != 2:
        raise RuntimeError("array 'h' phải là số nguyên 16 bit")
    if sys.byteorder == 'big':
        pcm.byteswap()
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SOUND_RATE)
        wav.writeframes(pcm.tobytes())
    return stream.getvalue()


def ensure_sound_files(directory):
    """Tạo (nếu chưa có) và trả về {tên: đường dẫn WAV}."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    files = {}
    for name in SOUND_NAMES:
        path = directory / f"{name}.wav"
        if not path.exists():
            temp = path.with_suffix('.tmp')
            temp.write_bytes(samples_to_wav(synth_sound(name)))
            os.replace(temp, path)
        files[name] = path
    return files


def default_sound_dir():
    return Path(tempfile.gettempdir()) / f"yago_lite_sounds_v{SOUND_VERSION}"


OPENING_BOOK = {
    # Thế khởi đầu chuẩn.
    "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1": [
        "h2e2", "b2e2", "h0g2", "b0c2", "c3c4", "g3g4"
    ],
    # Sau Pháo đầu h2e2.
    "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C2C4/9/RNBAKABNR b - - 0 1": [
        "h9g7", "b9c7"
    ],
    # Sau Khởi mã h0g2.
    "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C4NC1/9/RNBAKAB1R b - - 0 1": [
        "h9g7", "g6g5", "c6c5"
    ],
}


# --- Widget tùy chọn tự vẽ (bo góc khử răng cưa bằng sprite PNG) -----------

UI_TWEEN_SECONDS = 0.14


def animations_enabled(gui):
    variable = getattr(gui, 'animation_var', None)
    return variable is None or variable.get()


class SegmentedControl:
    """Thanh chọn nhiều đoạn (kiểu iOS): một biến, mỗi đoạn một giá trị.

    Nếu giá trị của biến không thuộc thanh này thì không đoạn nào sáng
    (dùng khi hai thanh cùng chia nhau một biến, ví dụ thời gian và độ sâu).
    """

    def __init__(self, gui, parent, variable, options, bg, command=None, height=30):
        self.gui = gui
        self.variable = variable
        self.options = list(options)
        self.command = command
        self.height = height
        self.canvas = tk.Canvas(parent, height=height, bg=bg, highlightthickness=0,
                                bd=0, cursor='hand2')
        self.hover = None
        self.pos = None
        self.anim_job = None
        self.canvas.bind('<Configure>', lambda _e: self.snap())
        self.canvas.bind('<Button-1>', self.on_click)
        self.canvas.bind('<Motion>', self.on_motion)
        self.canvas.bind('<Leave>', lambda _e: self.set_hover(None))
        variable.trace_add('write', lambda *_: self.on_variable())

    def pack(self, **kw):
        self.canvas.pack(**kw)
        return self

    def grid(self, **kw):
        self.canvas.grid(**kw)
        return self

    def selected_index(self):
        value = self.variable.get()
        for index, (option_value, _label) in enumerate(self.options):
            if option_value == value:
                return index
        return None

    def segment_width(self):
        return (self.canvas.winfo_width() - 4) / len(self.options)

    def index_at(self, x):
        width = self.segment_width()
        if width <= 0:
            return None
        return max(0, min(len(self.options) - 1, int((x - 2) // width)))

    def target_pos(self):
        index = self.selected_index()
        return None if index is None else index * self.segment_width()

    def snap(self):
        self.cancel_tween()
        self.pos = self.target_pos()
        self.redraw()

    def cancel_tween(self):
        if self.anim_job is not None:
            try:
                self.canvas.after_cancel(self.anim_job)
            except tk.TclError:
                pass
            self.anim_job = None

    def on_variable(self):
        target = self.target_pos()
        if target is None or self.pos is None or not animations_enabled(self.gui):
            self.snap()
            return
        self.cancel_tween()
        start, began = self.pos, time.perf_counter()

        def step():
            t = min(1.0, (time.perf_counter() - began) / UI_TWEEN_SECONDS)
            self.pos = start + (target - start) * ease_out_cubic(t)
            self.redraw()
            self.anim_job = self.canvas.after(15, step) if t < 1.0 else None

        step()

    def on_click(self, event):
        index = self.index_at(event.x)
        if index is None:
            return
        value = self.options[index][0]
        if self.command:
            self.command(value)
        else:
            self.variable.set(value)

    def on_motion(self, event):
        self.set_hover(self.index_at(event.x))

    def set_hover(self, index):
        if index != self.hover:
            self.hover = index
            self.redraw()

    def redraw(self):
        canvas = self.canvas
        canvas.delete('all')
        width, height = canvas.winfo_width(), self.height
        if width < 20:
            return
        colors = self.gui.colors
        track = self.gui.sprite(
            ('ui_track', width, height),
            lambda: render_panel_png(width, height, 8, '#0F172A', 1.0, border='#334155')
        )
        canvas.create_image(0, 0, image=track, anchor='nw')
        seg_w = self.segment_width()
        pill_w, pill_h = max(4, int(round(seg_w))), height - 4
        selected = self.selected_index()
        if self.hover is not None and self.hover != selected:
            hover = self.gui.sprite(
                ('ui_pill', pill_w, pill_h, '#1E293B'),
                lambda: render_panel_png(pill_w, pill_h, 6, '#1E293B', 1.0)
            )
            canvas.create_image(2 + self.hover * seg_w, 2, image=hover, anchor='nw')
        if self.pos is not None:
            pill = self.gui.sprite(
                ('ui_pill', pill_w, pill_h, colors['accent_dark']),
                lambda: render_panel_png(pill_w, pill_h, 6, colors['accent_dark'], 1.0)
            )
            canvas.create_image(2 + self.pos, 2, image=pill, anchor='nw')
        for index, (_value, label) in enumerate(self.options):
            is_selected = index == selected
            color = ('#FFFFFF' if is_selected
                     else '#E2E8F0' if index == self.hover else colors['muted'])
            canvas.create_text(
                2 + seg_w * (index + 0.5), height / 2, text=label, fill=color,
                font=("Segoe UI", 9, "bold" if is_selected else "normal")
            )


class ToggleSwitch:
    """Công tắc gạt bật/tắt gắn với một BooleanVar; núm trượt khi đổi trạng thái."""

    WIDTH, HEIGHT, KNOB = 38, 22, 8

    def __init__(self, gui, parent, variable, bg):
        self.gui = gui
        self.variable = variable
        self.canvas = tk.Canvas(parent, width=self.WIDTH, height=self.HEIGHT, bg=bg,
                                highlightthickness=0, bd=0, cursor='hand2')
        self.pos = 1.0 if variable.get() else 0.0
        self.anim_job = None
        self.canvas.bind('<Button-1>', lambda _e: self.toggle())
        variable.trace_add('write', lambda *_: self.on_variable())
        self.redraw()

    def toggle(self):
        self.variable.set(not self.variable.get())

    def on_variable(self):
        target = 1.0 if self.variable.get() else 0.0
        if self.anim_job is not None:
            try:
                self.canvas.after_cancel(self.anim_job)
            except tk.TclError:
                pass
            self.anim_job = None
        if not animations_enabled(self.gui):
            self.pos = target
            self.redraw()
            return
        start, began = self.pos, time.perf_counter()

        def step():
            t = min(1.0, (time.perf_counter() - began) / UI_TWEEN_SECONDS)
            self.pos = start + (target - start) * ease_out_cubic(t)
            self.redraw()
            self.anim_job = self.canvas.after(15, step) if t < 1.0 else None

        step()

    def redraw(self):
        canvas = self.canvas
        canvas.delete('all')
        w, h, knob = self.WIDTH, self.HEIGHT, self.KNOB
        color = self.gui.colors['accent_dark'] if self.pos >= 0.5 else '#334155'
        track = self.gui.sprite(
            ('ui_switch', color),
            lambda: render_panel_png(w, h, h / 2, color, 1.0)
        )
        canvas.create_image(0, 0, image=track, anchor='nw')
        dot = self.gui.sprite(('ui_knob',), lambda: render_dot_png(knob, '#F8FAFC', 1.0))
        x = h / 2 + (w - h) * self.pos
        canvas.create_image(x, h / 2, image=dot)


class OptionList:
    """Danh sách lựa chọn dạng radio, mỗi dòng một giá trị (dùng cho thế cờ)."""

    ROW = 28

    def __init__(self, gui, parent, variable, options, bg, command=None):
        self.gui = gui
        self.variable = variable
        self.options = list(options)
        self.command = command
        self.canvas = tk.Canvas(parent, height=self.ROW * len(self.options), bg=bg,
                                highlightthickness=0, bd=0, cursor='hand2')
        self.hover = None
        self.canvas.bind('<Configure>', lambda _e: self.redraw())
        self.canvas.bind('<Button-1>', self.on_click)
        self.canvas.bind('<Motion>', self.on_motion)
        self.canvas.bind('<Leave>', lambda _e: self.set_hover(None))
        variable.trace_add('write', lambda *_: self.redraw())

    def pack(self, **kw):
        self.canvas.pack(**kw)
        return self

    def index_at(self, y):
        index = int(y // self.ROW)
        return index if 0 <= index < len(self.options) else None

    def on_click(self, event):
        index = self.index_at(event.y)
        if index is None:
            return
        value = self.options[index][0]
        if self.command:
            self.command(value)
        else:
            self.variable.set(value)

    def on_motion(self, event):
        self.set_hover(self.index_at(event.y))

    def set_hover(self, index):
        if index != self.hover:
            self.hover = index
            self.redraw()

    def redraw(self):
        canvas = self.canvas
        canvas.delete('all')
        width = canvas.winfo_width()
        if width < 20:
            return
        colors = self.gui.colors
        row_h = self.ROW - 2
        value = self.variable.get()
        for index, (option_value, label) in enumerate(self.options):
            top = index * self.ROW
            selected = option_value == value
            if selected or index == self.hover:
                fill = '#0C2D48' if selected else '#1E293B'
                border = colors['accent_dark'] if selected else None
                key = ('ui_row', width, row_h, fill, border)
                image = self.gui.sprite(
                    key, lambda: render_panel_png(width, row_h, 6, fill, 1.0, border=border)
                )
                canvas.create_image(0, top + 1, image=image, anchor='nw')
            cy = top + self.ROW / 2
            ring_color = colors['accent'] if selected else '#64748B'
            ring = self.gui.sprite(('ui_ring', ring_color),
                                   lambda: render_ring_png(6, 1.6, ring_color, 1.0))
            canvas.create_image(16, cy, image=ring)
            if selected:
                dot = self.gui.sprite(('ui_dot', colors['accent']),
                                      lambda: render_dot_png(3.2, colors['accent'], 1.0))
                canvas.create_image(16, cy, image=dot)
            canvas.create_text(
                32, cy, text=label, anchor='w',
                fill=colors['text'] if selected else '#CBD5E1',
                font=("Segoe UI", 9, "bold" if selected else "normal")
            )


class Tooltip:
    """Chú thích nhỏ hiện khi rê chuột lâu lên một widget (nút chỉ có biểu tượng).

    text có thể là hàm để lấy nội dung mới mỗi lần hiện (ví dụ trạng thái hiện tại).
    """

    DELAY_MS = 450

    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.window = None
        self.job = None
        widget.bind('<Enter>', self.schedule, add='+')
        widget.bind('<Leave>', self.hide, add='+')
        widget.bind('<ButtonPress>', self.hide, add='+')

    def schedule(self, _event=None):
        self.cancel()
        self.job = self.widget.after(self.DELAY_MS, self.show)

    def cancel(self):
        if self.job is not None:
            try:
                self.widget.after_cancel(self.job)
            except tk.TclError:
                pass
            self.job = None

    def show(self):
        self.job = None
        text = self.text() if callable(self.text) else self.text
        if not text or not self.widget.winfo_ismapped():
            return
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.attributes('-topmost', True)
        tk.Label(self.window, text=text, font=("Segoe UI", 9), bg='#0F172A', fg='#F8FAFC',
                 padx=8, pady=4, highlightthickness=1,
                 highlightbackground='#334155').pack()
        self.window.update_idletasks()
        x = self.widget.winfo_rootx() - self.window.winfo_width() - 8
        if x < 0:
            x = self.widget.winfo_rootx() + self.widget.winfo_width() + 8
        y = (self.widget.winfo_rooty() + self.widget.winfo_height() // 2
             - self.window.winfo_height() // 2)
        self.window.geometry(f"+{x}+{y}")

    def hide(self, _event=None):
        self.cancel()
        if self.window is not None:
            try:
                self.window.destroy()
            except tk.TclError:
                pass
            self.window = None


OPENING_STYLE_HINTS = {
    STYLE_STANDARD: "Mạnh nhất: luôn đi nước Pikafish cho là tốt nhất.",
    STYLE_VARIED: (f"Đổi bài trong {VARIETY_PLIES // 2} nước đầu mỗi bên, "
                   "chỉ chọn nước gần tốt nhất."),
    STYLE_ODD: f"Nước đầu là khai cuộc ít gặp, mất tối đa ~{ODD_MAX_LOSS_CP / 100:.1f} tốt.",
    STYLE_VERY_ODD: f"Khai cuộc dị, có thể mất tới ~{VERY_ODD_MAX_LOSS_CP / 100:.1f} tốt.",
    'named': "Nước đầu của máy bắt buộc là khai cuộc chọn bên dưới.",
}
OPENING_MODE_NAMED = 'named'
BOARD_MODES = ["Cờ tiêu chuẩn", "Cả 2 bên Liệt Tốt 5", "Cả 2 bên Liệt Tốt 1", "Đỏ Chấp 1 Mã"]


class YagoLiteGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Yago Lite Pro v6 - Opening Book Integration")
        self.root.geometry("920x800") 
        self.root.configure(bg="#1E1E1E")
        
        self.initial_board = [
            ['r','n','b','a','k','a','b','n','r'],
            ['.','.','.','.','.','.','.','.','.'],
            ['.','c','.','.','.','.','.','c','.'],
            ['p','.','p','.','p','.','p','.','p'],
            ['.','.','.','.','.','.','.','.','.'],
            ['.','.','.','.','.','.','.','.','.'],
            ['P','.','P','.','P','.','P','.','P'],
            ['.','C','.','.','.','.','.','C','.'],
            ['.','.','.','.','.','.','.','.','.'],
            ['R','N','B','A','K','A','B','N','R']
        ]
        
        self.board = copy.deepcopy(self.initial_board)
        self.selected_piece = None
        self.engine_process = None
        self.is_engine_thinking = False
        self.engine_stopping = False
        self.search_cancelled = False
        self.active_search_source = None
        self.pending_book_job = None
        self.turn = 'w'
        self.game_over = False
        self.winner = None
        self.captured_by = {'w': [], 'b': []}

        # Lịch sử để engine biết lặp nước / luật 60 nước.
        self.start_fen = None
        self.move_list = []
        self.halfmove_clock = 0

        # Trạng thái engine.
        self.engine_ready = False
        self.engine_closing = False
        self.engine_output_tail = deque(maxlen=8)
        self.engine_crash_times = []
        # Luồng đọc engine chỉ đẩy việc vào hàng đợi; luồng Tk tự lấy ra xử lý.
        self.ui_queue = queue.Queue()
        self.search_after_drain = False
        self.is_pondering = False
        self.ponder_moves = None
        self.search_mode = 'normal'
        self.pending_opening_toast = None
        self.current_multipv = 1
        self.pv_candidates = {}

        self.state_stack = []
        self.is_flipped = False 
        self.last_move = None 
        self.is_animating = False
        self.animation_job = None
        self.animation_hidden_square = None
        self.board_scale = 1.0

        # Đồ họa và hiệu ứng.
        self.sprites = {}
        self.static_key = None
        self.effects = []
        self.fx_job = None
        self.resize_job = None
        self.hover_square = None
        self.check_pulse_active = False
        self.banner_dismissed = False
        self.result_title = ""
        self.result_reason = ""
        self.eval_fraction = 0.5
        self.eval_target = 0.5
        self.eval_tween_active = False
        self.status_tone = 'normal'
        self.status_pulse_job = None
        self.turn_indicator_state = None
        self.sound_files = {}

        self.colors = {
            'window': '#0B1120',
            'panel': '#111827',
            'card': '#1F2937',
            'card_alt': '#172033',
            'text': '#F8FAFC',
            'muted': '#94A3B8',
            'accent': '#38BDF8',
            'accent_dark': '#0284C7',
            'gold': '#F59E0B',
            'danger': '#EF4444',
            'success': '#22C55E',
            'board': '#E2B26B',
            'board_light': '#F2CC85',
            'board_line': '#5B3417',
        }
        
        # Cấu hình phần cứng
        self.cpu_threads = os.cpu_count() or 4
        # Chừa 2 luồng cho Windows và giao diện để máy vẫn phản hồi tốt.
        self.engine_threads = max(1, self.cpu_threads - 2)
        # Hash theo RAM thực tế: máy ít RAM không bị engine cấp phát thất bại.
        self.hash_size = recommended_hash_mb()

        self.opening_book = OPENING_BOOK

        self.reset_game_history()
        self.setup_ui()
        self.poll_ui_queue()
        if winsound is not None:
            threading.Thread(target=self.prepare_sounds, daemon=True).start()
        self.init_engine()
        self.root.protocol("WM_DELETE_WINDOW", self.close_app)

    def setup_ui(self):
        self.root.title("Yago Lite Pro — Cờ Tướng Pikafish")
        self.root.geometry("980x720")
        self.root.minsize(980, 720)
        self.root.configure(bg=self.colors['window'])

        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure(
            'Yago.TCombobox',
            fieldbackground=self.colors['card_alt'],
            background=self.colors['card_alt'],
            foreground=self.colors['text'],
            arrowcolor=self.colors['accent'],
            bordercolor='#334155',
            lightcolor='#334155',
            darkcolor='#334155',
            padding=6,
        )
        style.map(
            'Yago.TCombobox',
            fieldbackground=[('readonly', '#0F172A')],
            foreground=[('readonly', self.colors['text'])],
        )
        # Ô chọn khai cuộc theo tên khi đang dùng phong cách khác: chữ mờ đi.
        style.configure(
            'YagoDim.TCombobox',
            fieldbackground=self.colors['card_alt'],
            background=self.colors['card_alt'],
            foreground=self.colors['muted'],
            arrowcolor='#64748B',
            bordercolor='#334155',
            lightcolor='#334155',
            darkcolor='#334155',
            padding=6,
        )
        style.map(
            'YagoDim.TCombobox',
            fieldbackground=[('readonly', '#0F172A')],
            foreground=[('readonly', self.colors['muted'])],
        )
        # Danh sách thả xuống của Combobox cũng theo tông tối.
        self.root.option_add('*TCombobox*Listbox.background', '#0F172A')
        self.root.option_add('*TCombobox*Listbox.foreground', self.colors['text'])
        self.root.option_add('*TCombobox*Listbox.selectBackground', self.colors['accent_dark'])
        self.root.option_add('*TCombobox*Listbox.selectForeground', '#FFFFFF')
        self.root.option_add('*TCombobox*Listbox.font', ("Segoe UI", 9))

        self.main_frame = tk.Frame(self.root, bg=self.colors['window'])
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=18, pady=18)
        self.main_frame.grid_rowconfigure(0, weight=1)
        # Khu bàn cờ nhận toàn bộ không gian dư; bảng điều khiển luôn rộng 370 px.
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_columnconfigure(1, weight=0, minsize=370)

        self.board_area = tk.Frame(self.main_frame, bg=self.colors['window'])
        self.board_area.grid(row=0, column=0, sticky='nsew', padx=(0, 16))
        self.board_area.grid_rowconfigure(0, weight=1)
        self.board_area.grid_columnconfigure(0, weight=1)

        self.board_frame = tk.Frame(
            self.board_area, bg='#070B14', bd=0, padx=8, pady=8
        )
        # Không dùng sticky để Tk tự căn giữa bàn cờ trong vùng co giãn.
        self.board_frame.grid(row=0, column=0)

        self.canvas = tk.Canvas(
            self.board_frame,
            width=540,
            height=600,
            bg=self.colors['board'],
            highlightthickness=1,
            highlightbackground='#D9963B',
            cursor='hand2',
        )
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<Motion>", self.on_canvas_motion)
        self.canvas.bind("<Leave>", self.on_canvas_leave)

        self.capture_bar = tk.Frame(
            self.board_frame, bg='#070B14', height=58
        )
        self.capture_bar.pack(fill=tk.X, pady=(8, 0))
        self.capture_bar.grid_propagate(False)
        self.capture_bar.grid_columnconfigure(0, weight=1, uniform='capture_trays')
        self.capture_bar.grid_columnconfigure(1, weight=0)
        self.capture_bar.grid_columnconfigure(2, weight=1, uniform='capture_trays')
        self.capture_bar.grid_rowconfigure(0, weight=1)

        self.red_capture_frame = tk.Frame(
            self.capture_bar, bg='#27151B', padx=7, pady=3,
            highlightthickness=1, highlightbackground='#7F1D1D'
        )
        self.red_capture_frame.grid(
            row=0, column=0, sticky='nsew', padx=(0, 6)
        )
        self.lbl_red_capture_title = tk.Label(
            self.red_capture_frame, text="ĐỎ ĐÃ ĂN", font=("Segoe UI", 7, "bold"),
            fg='#FCA5A5', bg='#27151B'
        )
        self.lbl_red_capture_title.pack(anchor='w')
        self.red_capture_canvas = tk.Canvas(
            self.red_capture_frame, height=34, bg='#27151B',
            highlightthickness=0, bd=0
        )
        self.red_capture_canvas.pack(fill=tk.X, expand=True)

        self.capture_divider = tk.Frame(
            self.capture_bar, bg='#64748B', width=2
        )
        self.capture_divider.grid(row=0, column=1, sticky='ns')

        self.black_capture_frame = tk.Frame(
            self.capture_bar, bg='#162219', padx=7, pady=3,
            highlightthickness=1, highlightbackground='#365A3B'
        )
        self.black_capture_frame.grid(
            row=0, column=2, sticky='nsew', padx=(6, 0)
        )
        self.lbl_black_capture_title = tk.Label(
            self.black_capture_frame, text="ĐEN ĐÃ ĂN", font=("Segoe UI", 7, "bold"),
            fg='#A7C7A0', bg='#162219'
        )
        self.lbl_black_capture_title.pack(anchor='e')
        self.black_capture_canvas = tk.Canvas(
            self.black_capture_frame, height=34, bg='#162219',
            highlightthickness=0, bd=0
        )
        self.black_capture_canvas.pack(fill=tk.X, expand=True)
        
        self.control_frame = tk.Frame(
            self.main_frame, bg=self.colors['panel'], width=370
        )
        self.control_frame.grid(row=0, column=1, sticky='ns')
        self.control_frame.pack_propagate(False)

        header = tk.Frame(self.control_frame, bg=self.colors['panel'])
        header.pack(fill=tk.X, padx=18, pady=(10, 6))
        title_row = tk.Frame(header, bg=self.colors['panel'])
        title_row.pack(fill=tk.X)
        tk.Label(
            title_row, text="YAGO LITE", font=("Segoe UI", 20, "bold"),
            fg=self.colors['text'], bg=self.colors['panel']
        ).pack(side=tk.LEFT)
        self.btn_collapse = self.make_button(
            title_row, "»", self.colors['panel'], self.toggle_panel
        )
        self.btn_collapse.config(font=("Segoe UI", 14, "bold"), fg=self.colors['muted'],
                                 width=2, pady=0)
        self.btn_collapse.pack(side=tk.RIGHT)
        Tooltip(self.btn_collapse, "Thu gọn bảng điều khiển (Ctrl+B)")
        subtitle_row = tk.Frame(header, bg=self.colors['panel'])
        subtitle_row.pack(fill=tk.X)
        tk.Label(
            subtitle_row, text="XIANGQI  •  PIKAFISH ENGINE", font=("Segoe UI", 8, "bold"),
            fg=self.colors['accent'], bg=self.colors['panel']
        ).pack(side=tk.LEFT)
        hash_text = (f"{self.hash_size // 1024} GB" if self.hash_size >= 1024
                     else f"{self.hash_size} MB")
        tk.Label(
            subtitle_row,
            text=f"⚡ {self.engine_threads}/{self.cpu_threads} luồng  •  Hash {hash_text}",
            font=("Segoe UI", 8), fg=self.colors['muted'], bg=self.colors['panel']
        ).pack(side=tk.RIGHT)

        engine_card = tk.Frame(self.control_frame, bg=self.colors['card'], padx=14, pady=10)
        engine_card.pack(fill=tk.X, padx=18, pady=(0, 10))
        score_row = tk.Frame(engine_card, bg=self.colors['card'])
        score_row.pack(fill=tk.X)
        self.lbl_eval = tk.Label(
            score_row, text="+0.00", font=("Consolas", 19, "bold"),
            fg=self.colors['success'], bg=self.colors['card']
        )
        self.lbl_eval.pack(side=tk.LEFT)
        self.lbl_depth = tk.Label(
            score_row, text="DEPTH 0/24", font=("Consolas", 9, "bold"),
            fg=self.colors['muted'], bg=self.colors['card']
        )
        self.lbl_depth.pack(side=tk.RIGHT)
        # Thanh ưu thế: phần đỏ là lợi thế của Đỏ, phần xám là của Đen.
        self.eval_bar = tk.Canvas(
            engine_card, height=8, bg=self.colors['card'], highlightthickness=0, bd=0
        )
        self.eval_bar.pack(fill=tk.X, pady=(6, 0))
        self.eval_bar.bind('<Configure>', lambda _event: self.draw_eval_bar())
        self.lbl_opening = tk.Label(
            engine_card, text="", font=("Segoe UI", 8), anchor='w',
            fg=self.colors['muted'], bg=self.colors['card']
        )
        self.lbl_opening.pack(fill=tk.X, pady=(5, 0))

        # Tạo biến tùy chọn trước để mọi widget gắn được ngay khi dựng.
        self.auto_reply_var = tk.BooleanVar(value=True)
        # Sách nhỏ và chọn ngẫu nhiên nên yếu hơn Pikafish: mặc định tắt.
        self.use_book_var = tk.BooleanVar(value=False)
        self.ponder_var = tk.BooleanVar(value=True)
        self.sound_var = tk.BooleanVar(value=True)
        self.animation_var = tk.BooleanVar(value=True)
        self.mode_var = tk.StringVar(value=BOARD_MODES[0])
        self.limit_var = tk.StringVar(value=DEFAULT_SEARCH_LIMIT)
        # opening_style_var là nguồn duy nhất engine đọc (một giá trị trong
        # OPENING_STYLE_CHOICES). Hai biến sau chỉ phản chiếu nó lên giao diện.
        self.opening_style_var = tk.StringVar(value=STYLE_STANDARD)
        self.opening_mode_var = tk.StringVar(value=STYLE_STANDARD)
        self.named_opening_var = tk.StringVar(value=NAMED_OPENINGS[0])

        btn_frame = tk.Frame(self.control_frame, bg=self.colors['panel'])
        btn_frame.pack(fill=tk.X, padx=18)
        btn_frame.columnconfigure((0, 1, 2), weight=1, uniform='actions')
        self.btn_go = self.make_button(
            btn_frame, "⚙  MÁY ĐI", self.colors['accent_dark'], self.trigger_engine, bold=True
        )
        self.btn_go.grid(row=0, column=0, columnspan=3, sticky='ew', pady=(0, 6), ipady=7)
        self.btn_undo = self.make_button(btn_frame, "↶  Đi lại", '#334155', self.undo_move)
        self.btn_undo.grid(row=1, column=0, sticky='ew', padx=(0, 3), ipady=4)
        self.btn_flip = self.make_button(btn_frame, "⇅  Lật bàn", '#334155', self.flip_board)
        self.btn_flip.grid(row=1, column=1, sticky='ew', padx=3, ipady=4)
        self.btn_new = self.make_button(btn_frame, "＋  Ván mới", '#991B1B', self.new_game)
        self.btn_new.grid(row=1, column=2, sticky='ew', padx=(3, 0), ipady=4)

        # Ba thẻ thay cho khối tùy chọn dồn cục: lịch sử, cài đặt máy, cài đặt ván.
        self.tab_var = tk.StringVar(value='moves')
        self.tab_bar = SegmentedControl(
            self, self.control_frame, self.tab_var,
            [('moves', "Nước đi"), ('engine', "Máy chơi"), ('game', "Ván & hiển thị")],
            bg=self.colors['panel'], command=self.show_tab, height=32
        ).pack(fill=tk.X, padx=18, pady=(10, 8))
        self.tab_host = tk.Frame(self.control_frame, bg=self.colors['panel'])
        # Chừa chỗ cho thanh trạng thái đặt bằng place() ở đáy bảng.
        self.tab_host.pack(fill=tk.BOTH, expand=True, padx=18, pady=(0, 44))
        self.tabs = {
            'moves': self.build_moves_tab(self.tab_host),
            'engine': self.build_engine_tab(self.tab_host),
            'game': self.build_game_tab(self.tab_host),
        }
        self.show_tab('moves')

        self.limit_var.trace_add('write', lambda *_: self.update_depth_label_display())
        self.opening_style_var.trace_add('write', lambda *_: self.sync_opening_controls())
        self.sync_opening_controls()

        status_frame = tk.Frame(self.control_frame, bg='#0F172A', padx=12, pady=9)
        status_frame.place(relx=0, rely=1, relwidth=1, anchor='sw')
        self.status_dot = tk.Label(
            status_frame, text="●", font=("Segoe UI", 9),
            fg=self.colors['success'], bg='#0F172A'
        )
        self.status_dot.pack(side=tk.LEFT, padx=(0, 7))
        self.lbl_status = tk.Label(
            status_frame, text="Lượt Đỏ", font=("Segoe UI", 9),
            fg=self.colors['muted'], bg='#0F172A', anchor='w'
        )
        self.lbl_status.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.draw_board()
        self.update_captured_display()
        self.update_depth_label_display()
        self.update_opening_label()
        self.board_area.bind('<Configure>', self.on_board_area_resize)
        self.panel_collapsed = False
        self.build_rail()
        self.root.bind('<Control-b>', self.toggle_panel)
        self.root.bind('<Control-B>', self.toggle_panel)

    def make_button(self, parent, text, color, command, bold=False):
        """Nút phẳng; màu hover tính từ màu nền hiện tại.

        Nhờ vậy nút MÁY ĐI đổi sang vàng ("ĐANG TÍNH...") không bị hover trả về xanh.
        """
        button = tk.Button(
            parent, text=text, command=command, bg=color,
            activebackground=mix_hex(color, '#FFFFFF', 0.14), fg='white',
            activeforeground='white', relief=tk.FLAT, bd=0, cursor='hand2',
            font=("Segoe UI", 10, "bold" if bold else "normal")
        )

        def on_enter(_event):
            base = button.cget('bg')
            button.hover_base = base
            button.hover_color = mix_hex(base, '#FFFFFF', 0.14)
            button.config(bg=button.hover_color, activebackground=button.hover_color)

        def on_leave(_event):
            # Nếu nền đã bị đổi trong lúc hover (trạng thái máy) thì giữ màu mới.
            if button.cget('bg') == getattr(button, 'hover_color', None):
                button.config(bg=button.hover_base)

        button.bind('<Enter>', on_enter)
        button.bind('<Leave>', on_leave)
        return button

    def set_go_button(self, text, bg):
        """Đổi chữ/màu nút MÁY ĐI; nút ⚙ trên thanh thu gọn đổi màu theo."""
        self.btn_go.config(text=text, bg=bg)
        rail_go = getattr(self, 'rail_go', None)
        if rail_go is not None:
            rail_go.config(bg=bg)

    def set_eval_label(self, text, color):
        self.lbl_eval.config(text=text, fg=color)
        rail_eval_label = getattr(self, 'rail_eval_label', None)
        if rail_eval_label is not None:
            rail_eval_label.config(text=text, fg=color)

    def build_rail(self):
        """Thanh dọc hẹp thay cho bảng điều khiển khi thu gọn: các nút chính,
        điểm số, thanh ưu thế dọc và chấm trạng thái (rê chuột để xem chi tiết)."""
        panel = self.colors['panel']
        self.rail = tk.Frame(self.main_frame, bg=panel, width=58)
        self.rail.pack_propagate(False)

        def rail_button(text, color, command, tip, pady=(0, 6)):
            button = self.make_button(self.rail, text, color, command)
            button.config(font=("Segoe UI Symbol", 15), width=2, height=1)
            button.pack(fill=tk.X, padx=8, pady=pady, ipady=2)
            Tooltip(button, tip)
            return button

        expand = rail_button("«", panel, self.toggle_panel,
                             "Mở bảng điều khiển (Ctrl+B)", pady=(10, 10))
        expand.config(fg=self.colors['muted'], font=("Segoe UI", 15, "bold"))
        self.rail_go = rail_button("⚙", self.btn_go.cget('bg'), self.trigger_engine, "Máy đi")
        rail_button("↶", '#334155', self.undo_move, "Đi lại")
        rail_button("⇅", '#334155', self.flip_board, "Lật bàn")
        rail_button("＋", '#991B1B', self.new_game, "Ván mới", pady=(0, 12))

        self.rail_dot = tk.Label(self.rail, text="●", font=("Segoe UI", 11), bg=panel,
                                 fg=self.status_dot.cget('fg'), cursor='question_arrow')
        self.rail_dot.pack(side=tk.BOTTOM, pady=(6, 10))
        Tooltip(self.rail_dot, lambda: self.lbl_status.cget('text'))
        self.rail_eval_label = tk.Label(
            self.rail, text=self.lbl_eval.cget('text'), font=("Consolas", 8, "bold"),
            fg=self.lbl_eval.cget('fg'), bg=panel
        )
        self.rail_eval_label.pack(pady=(0, 4))
        self.rail_eval = tk.Canvas(self.rail, width=10, bg=panel, highlightthickness=0, bd=0)
        self.rail_eval.pack(fill=tk.Y, expand=True)
        self.rail_eval.bind('<Configure>', lambda _event: self.draw_rail_eval_bar())

    def toggle_panel(self, _event=None):
        self.set_panel_collapsed(not self.panel_collapsed)
        return 'break'

    def set_panel_collapsed(self, collapsed):
        """Thu gọn: bàn cờ chiếm gần hết cửa sổ, cửa sổ được thu nhỏ hơn mức tối thiểu cũ."""
        if collapsed == self.panel_collapsed:
            return
        self.panel_collapsed = collapsed
        if collapsed:
            self.control_frame.grid_remove()
            self.main_frame.grid_columnconfigure(1, minsize=0)
            self.rail.grid(row=0, column=1, sticky='ns')
            self.root.minsize(640, 720)
        else:
            self.rail.grid_remove()
            self.main_frame.grid_columnconfigure(1, minsize=370)
            self.control_frame.grid()
            self.root.minsize(980, 720)
            self.root.update_idletasks()
            if self.root.state() == 'normal' and self.root.winfo_width() < 980:
                self.root.geometry(f"980x{max(720, self.root.winfo_height())}")
        self.draw_rail_eval_bar()

    def section_label(self, parent, text, bg, hint=None, pady=(0, 0)):
        row = tk.Frame(parent, bg=bg)
        row.pack(fill=tk.X, pady=pady)
        tk.Label(row, text=text, font=("Segoe UI", 8, "bold"),
                 fg=self.colors['muted'], bg=bg).pack(side=tk.LEFT)
        if hint:
            tk.Label(row, text=hint, font=("Segoe UI", 8),
                     fg='#64748B', bg=bg).pack(side=tk.RIGHT)
        return row

    def make_toggle_row(self, parent, text, variable, bg):
        """Một dòng: nhãn bên trái, công tắc bên phải; bấm cả dòng đều đổi được."""
        row = tk.Frame(parent, bg=bg, cursor='hand2')
        row.pack(fill=tk.X, pady=(3, 0))
        switch = ToggleSwitch(self, row, variable, bg)
        switch.canvas.pack(side=tk.RIGHT)
        label = tk.Label(row, text=text, font=("Segoe UI", 9), fg='#E2E8F0', bg=bg,
                         anchor='w', cursor='hand2')
        label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        for widget in (row, label):
            widget.bind('<Button-1>', lambda _event: switch.toggle())
        return switch

    def build_moves_tab(self, host):
        frame = tk.Frame(host, bg=self.colors['panel'])
        head = tk.Frame(frame, bg=self.colors['panel'])
        head.pack(fill=tk.X, pady=(0, 5))
        tk.Label(head, text="LỊCH SỬ NƯỚC ĐI", font=("Segoe UI", 8, "bold"),
                 fg=self.colors['muted'], bg=self.colors['panel']).pack(side=tk.LEFT)
        self.lbl_move_count = tk.Label(head, text="", font=("Segoe UI", 8),
                                       fg='#64748B', bg=self.colors['panel'])
        self.lbl_move_count.pack(side=tk.RIGHT)
        self.listbox_moves = tk.Listbox(
            frame, bg='#0F172A', fg=self.colors['text'],
            selectbackground=self.colors['accent_dark'], selectforeground='white',
            font=("Cascadia Mono", 10), bd=0, highlightthickness=1,
            highlightbackground='#334155', highlightcolor='#334155',
            activestyle='none', height=4, relief=tk.FLAT
        )
        self.listbox_moves.pack(fill=tk.BOTH, expand=True)
        self.update_move_count()
        return frame

    def build_engine_tab(self, host):
        bg = self.colors['card_alt']
        frame = tk.Frame(host, bg=bg, padx=12, pady=8)

        self.section_label(frame, "THỜI GIAN SUY NGHĨ", bg, hint="mỗi nước")
        time_options = [(label, search_limit_short(label))
                        for label, kind, _value in SEARCH_LIMITS if kind == 'movetime']
        depth_options = [(label, label)
                         for label, kind, _value in SEARCH_LIMITS if kind == 'depth']
        self.seg_time = SegmentedControl(
            self, frame, self.limit_var, time_options, bg, height=26
        ).pack(fill=tk.X, pady=(5, 4))
        self.seg_depth = SegmentedControl(
            self, frame, self.limit_var, depth_options, bg, height=26
        ).pack(fill=tk.X)

        self.section_label(frame, "KHAI CUỘC", bg, pady=(10, 0))
        self.seg_opening = SegmentedControl(
            self, frame, self.opening_mode_var,
            [(style, style) for style in OPENING_STYLES] + [(OPENING_MODE_NAMED, "Theo tên")],
            bg, command=self.select_opening_mode, height=26
        ).pack(fill=tk.X, pady=(5, 0))
        self.lbl_style_hint = tk.Label(
            frame, text="", font=("Segoe UI", 8), fg=self.colors['muted'], bg=bg,
            anchor='w', justify='left'
        )
        self.lbl_style_hint.pack(fill=tk.X, pady=(4, 4))
        self.cb_named = ttk.Combobox(
            frame, textvariable=self.named_opening_var, values=NAMED_OPENINGS,
            state='readonly', font=("Segoe UI", 9), style='YagoDim.TCombobox',
            height=len(NAMED_OPENINGS)
        )
        self.cb_named.pack(fill=tk.X)
        # Chọn một tên là tự chuyển sang chế độ "Theo tên".
        self.cb_named.bind('<<ComboboxSelected>>', lambda _event: (
            self.cb_named.selection_clear(), self.select_opening_mode(OPENING_MODE_NAMED)
        ))

        self.section_label(frame, "KHI CHƠI", bg, pady=(10, 0))
        self.make_toggle_row(frame, "Tự động đáp trả sau nước của bạn", self.auto_reply_var, bg)
        self.make_toggle_row(frame, "Nghĩ trước trong lượt của bạn", self.ponder_var, bg)
        self.make_toggle_row(frame, "Dùng sách khai cuộc", self.use_book_var, bg)
        return frame

    def build_game_tab(self, host):
        bg = self.colors['card_alt']
        frame = tk.Frame(host, bg=bg, padx=12, pady=10)
        self.section_label(frame, "THẾ CỜ", bg, hint="đổi ngay nếu chưa đi nước nào")
        self.mode_list = OptionList(
            self, frame, self.mode_var, [(mode, mode) for mode in BOARD_MODES], bg,
            command=self.select_board_mode
        ).pack(fill=tk.X, pady=(5, 0))
        self.section_label(frame, "HIỂN THỊ", bg, pady=(12, 0))
        self.make_toggle_row(frame, "Hiệu ứng động", self.animation_var, bg)
        self.make_toggle_row(frame, "Âm thanh", self.sound_var, bg)
        return frame

    def show_tab(self, name):
        self.tab_var.set(name)
        for key, frame in self.tabs.items():
            if key == name:
                frame.pack(fill=tk.BOTH, expand=True)
            else:
                frame.pack_forget()

    def select_opening_mode(self, mode):
        if mode == OPENING_MODE_NAMED:
            self.opening_style_var.set(NAMED_OPENING_PREFIX + self.named_opening_var.get())
        else:
            self.opening_style_var.set(mode)

    def sync_opening_controls(self):
        """Cập nhật thanh phong cách, ô tên khai cuộc và dòng mô tả theo opening_style_var."""
        style = self.opening_style_var.get()
        name = named_opening_from_style(style)
        mode = OPENING_MODE_NAMED if name else style
        if name and self.named_opening_var.get() != name:
            self.named_opening_var.set(name)
        if self.opening_mode_var.get() != mode:
            self.opening_mode_var.set(mode)
        self.lbl_style_hint.config(text=OPENING_STYLE_HINTS.get(mode, ""))
        self.cb_named.configure(style='Yago.TCombobox' if name else 'YagoDim.TCombobox')

    def select_board_mode(self, mode):
        if mode == self.mode_var.get():
            return
        self.mode_var.set(mode)
        if not self.move_list and not self.state_stack:
            # Chưa đi nước nào: dựng lại bàn theo thế cờ mới luôn.
            self.new_game()
            self.set_status(f"Thế cờ: {mode}")
        else:
            self.set_status("Thế cờ mới sẽ áp dụng khi bấm Ván mới", 'warning')

    def update_move_count(self):
        count = self.listbox_moves.size()
        self.lbl_move_count.config(text=f"{count} nước" if count else "chưa có nước nào")

    def update_depth_label_display(self):
        short = search_limit_short(self.limit_var.get())
        self.lbl_depth.config(text=f"DEPTH 0 • {short}")

    def init_engine(self, restarting=False):
        base_dir = Path(__file__).resolve().parent
        engine_path = base_dir / "engine.exe"
        try:
            if not engine_path.exists():
                raise FileNotFoundError(engine_path)
            self.engine_process = subprocess.Popen(
                [str(engine_path)],
                cwd=str(base_dir),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )
            self.engine_ready = False
            self.send_engine("uci")
            self.send_engine(f"setoption name Threads value {self.engine_threads}")
            self.send_engine(f"setoption name Hash value {self.hash_size}")
            self.send_engine("setoption name Ponder value true")
            self.send_engine("setoption name MultiPV value 1")
            self.current_multipv = 1
            self.send_engine("isready")
            threading.Thread(target=self.listen_engine_loop, daemon=True).start()
            if not restarting:
                self.set_status("Engine đang khởi động...", 'thinking')
        except (FileNotFoundError, OSError) as exc:
            self.engine_process = None
            messagebox.showerror("Lỗi", f"Không thể mở engine.exe:\n{exc}")

    def on_engine_ready(self):
        if self.engine_ready:
            return
        self.engine_ready = True
        if self.active_search_source == 'restart':
            # Engine vừa được mở lại giữa lúc đang tính: tính lại nước đó từ đầu.
            self.is_engine_thinking = False
            self.active_search_source = None
            self.set_go_button(text="⚙  MÁY ĐI", bg=self.colors['accent_dark'])
            if not self.game_over:
                self.trigger_engine()
                return
        if not self.is_engine_thinking and not self.game_over:
            self.update_game_status()

    def on_engine_exit(self, process=None):
        """Engine tắt bất ngờ (thiếu RAM cho Hash, thiếu file .nnue, crash...).

        Nếu engine đã chạy được (từng trả readyok) thì tự mở lại và, nếu nó chết
        giữa lúc tính nước, tính lại nước đó. Engine chết ngay khi khởi động hoặc
        crash dồn dập thì báo lỗi như cũ.
        """
        if self.engine_closing:
            return
        if (process is not None and self.engine_process is not None
                and process is not self.engine_process):
            return  # Tin thoát muộn của engine cũ, đã có engine mới thay.
        was_ready = self.engine_ready
        resume = ((self.is_engine_thinking
                   and self.active_search_source in ('engine', 'restart')
                   and not self.search_cancelled)
                  or self.search_after_drain)
        self.engine_process = None
        self.engine_ready = False
        self.is_engine_thinking = False
        self.engine_stopping = False
        self.search_cancelled = False
        self.search_after_drain = False
        self.is_pondering = False
        self.ponder_moves = None
        self.active_search_source = None
        self.set_go_button(text="⚙  MÁY ĐI", bg=self.colors['accent_dark'])

        now = time.monotonic()
        allowed, self.engine_crash_times = engine_restart_allowed(self.engine_crash_times, now)
        if was_ready and allowed:
            self.engine_crash_times.append(now)
            resume = resume and not self.game_over
            if resume:
                # Giữ khóa bàn cờ như đang tính, tới khi engine mới sẵn sàng.
                self.is_engine_thinking = True
                self.active_search_source = 'restart'
                self.set_go_button(text="ĐANG MỞ LẠI ENGINE...", bg=self.colors['gold'])
            self.init_engine(restarting=True)
            if self.engine_process is not None:
                self.set_status(
                    "Pikafish bị lỗi, đã tự mở lại" + (" — đang tính lại nước" if resume else ""),
                    'warning'
                )
                return
            self.is_engine_thinking = False
            self.active_search_source = None
            self.set_go_button(text="⚙  MÁY ĐI", bg=self.colors['accent_dark'])

        self.set_status("Engine đã dừng — hãy mở lại ứng dụng", 'error')
        detail = "\n".join(self.engine_output_tail)
        when = ("nhiều lần liên tiếp khi đang chơi" if was_ready
                else "khi khởi động")
        messagebox.showerror(
            "Lỗi engine",
            f"Pikafish đã dừng {when}.\n"
            f"Kiểm tra pikafish.nnue nằm cạnh engine.exe và máy còn đủ RAM.\n\n{detail}"
        )

    def set_multipv(self, count):
        """Chỉ gọi khi engine đang rảnh (giữa hai lượt tìm kiếm)."""
        if count != self.current_multipv:
            self.send_engine(f"setoption name MultiPV value {count}")
            self.current_multipv = count

    def send_engine(self, cmd):
        if self.engine_process and self.engine_process.poll() is None:
            try:
                self.engine_process.stdin.write(cmd + "\n")
                self.engine_process.stdin.flush()
            except (BrokenPipeError, OSError):
                self.engine_process = None

    def generate_fen(self):
        fen_rows = []
        for r in range(10):
            empty_count = 0
            row_str = ""
            for c in range(9):
                piece = self.board[r][c]
                if piece == '.':
                    empty_count += 1
                else:
                    if empty_count > 0:
                        row_str += str(empty_count)
                        empty_count = 0
                    row_str += piece
            if empty_count > 0:
                row_str += str(empty_count)
            fen_rows.append(row_str)
        return "/".join(fen_rows) + f" {self.turn} - - 0 1"

    def reset_game_history(self):
        """Ghi lại thế bắt đầu ván (kể cả thế chấp quân) để gửi kèm danh sách nước."""
        self.start_fen = self.generate_fen()
        self.move_list = []
        self.halfmove_clock = 0

    def position_command(self, moves=None):
        moves = self.move_list if moves is None else moves
        command = f"position fen {self.start_fen}"
        if moves:
            command += " moves " + " ".join(moves)
        return command

    def on_board_area_resize(self, event=None):
        """Co giãn bàn cờ theo vùng hiển thị nhưng luôn giữ đúng tỷ lệ.

        Sự kiện resize được gom lại (debounce) vì mỗi kích thước mới cần vẽ lại sprite.
        """
        if event is not None:
            if self.resize_job is not None:
                self.root.after_cancel(self.resize_job)
            self.resize_job = self.root.after(40, self.on_board_area_resize)
            return
        self.resize_job = None
        if self.is_animating:
            return
        width = self.board_area.winfo_width()
        height = self.board_area.winfo_height()
        if width <= 1 or height <= 1:
            return

        target_scale = max(0.65, min(width / 558, height / 684))
        if abs(target_scale - self.board_scale) < 0.005:
            return
        self.board_scale = target_scale
        s = self.board_scale
        if len(self.sprites) > 160:
            self.sprites.clear()

        frame_padding = max(4, round(8*s))
        self.board_frame.config(padx=frame_padding, pady=frame_padding)
        self.canvas.config(width=round(540*s), height=round(600*s))
        self.capture_bar.config(height=round(58*s))
        self.capture_bar.pack_configure(pady=(max(4, round(8*s)), 0))
        self.red_capture_frame.config(
            padx=max(4, round(7*s)), pady=max(2, round(3*s)),
            highlightthickness=max(1, round(1.5*s))
        )
        self.black_capture_frame.config(
            padx=max(4, round(7*s)), pady=max(2, round(3*s)),
            highlightthickness=max(1, round(1.5*s))
        )
        self.red_capture_frame.grid_configure(padx=(0, max(4, round(6*s))))
        self.black_capture_frame.grid_configure(padx=(max(4, round(6*s)), 0))
        self.capture_divider.config(width=max(2, round(2*s)))
        capture_height = max(24, round(34*s))
        self.red_capture_canvas.config(height=capture_height)
        self.black_capture_canvas.config(height=capture_height)
        title_font_size = max(7, round(7*s))
        self.lbl_red_capture_title.config(font=("Segoe UI", title_font_size, "bold"))
        self.lbl_black_capture_title.config(font=("Segoe UI", title_font_size, "bold"))

        self.draw_board()
        self.update_captured_display()

    # ------------------------------------------------------------------
    # Sprite
    # ------------------------------------------------------------------
    def sprite(self, key, builder):
        image = self.sprites.get(key)
        if image is None:
            image = tk.PhotoImage(
                master=self.root, format='png',
                data=base64.b64encode(builder()).decode('ascii')
            )
            self.sprites[key] = image
        return image

    @staticmethod
    def _q(value):
        """Lượng tử hóa kích thước để dùng lại sprite khi resize từng chút."""
        return max(1.0, round(value * 2) / 2)

    def piece_image(self, side, radius, lifted=False):
        r = self._q(radius)
        return self.sprite(('piece', side, r, lifted),
                           lambda: render_piece_png(r, side, lifted))

    def glow_image(self, radius, color, alpha, inner=0.0):
        r = self._q(radius)
        return self.sprite(('glow', r, color, alpha, inner),
                           lambda: render_glow_png(r, color, alpha, inner))

    def ring_image(self, radius, width, color, alpha, glow=0.0):
        r, w = self._q(radius), self._q(width)
        return self.sprite(('ring', r, w, color, alpha, glow),
                           lambda: render_ring_png(r, w, color, alpha, glow))

    def dot_image(self, radius, color, alpha):
        r = self._q(radius)
        return self.sprite(('dot', r, color, alpha),
                           lambda: render_dot_png(r, color, alpha))

    def panel_image(self, width, height, radius, fill, alpha, border=None,
                    border_alpha=1.0, border_width=1.0):
        key = ('panel', width, height, round(radius, 1), fill, alpha, border,
               border_alpha, round(border_width, 1))
        return self.sprite(key, lambda: render_panel_png(
            width, height, radius, fill, alpha, border, border_alpha, border_width))

    def check_glow_frames(self):
        s = self.board_scale
        return [
            self.glow_image(36*s + i*1.2*s, '#EF4444', 0.42 + i*0.07, 0.45)
            for i in range(6)
        ]

    # ------------------------------------------------------------------
    # Vẽ bàn cờ theo lớp: 'static' (gỗ, lưới) chỉ vẽ lại khi đổi kích thước
    # hoặc lật bàn; 'dyn' (đánh dấu, quân, banner) vẽ lại mỗi lần; 'moving' và
    # 'fx' (animation, hiệu ứng) không bị draw_board xóa và luôn nằm trên cùng.
    # ------------------------------------------------------------------
    def display_xy(self, row, col):
        return self.board_to_canvas((row, col))

    def draw_board(self):
        key = (round(self.board_scale, 4), self.is_flipped)
        if key != self.static_key:
            self.canvas.delete('static')
            self.draw_static_board()
            self.canvas.tag_lower('static')
            self.static_key = key

        self.canvas.delete('dyn')
        self.canvas.delete('hover')
        self.draw_markers()
        self.draw_pieces()
        if self.game_over and not self.banner_dismissed:
            self.draw_result_banner()
        self.draw_hover()
        self.canvas.tag_raise('moving')
        self.canvas.tag_raise('fx')
        self.update_turn_indicator()
        self.ensure_check_pulse()

    def draw_static_board(self):
        c = self.canvas
        s = self.board_scale
        tags = ('static',)
        W, H = 540*s, 600*s

        # Khung gỗ sẫm nhiều lớp tạo cảm giác vát cạnh.
        c.create_rectangle(0, 0, W, H, fill='#3F2412', outline='', tags=tags)
        for i, color in enumerate(('#55321A', '#6A4223', '#7C512C')):
            inset = (2 + i*3)*s
            c.create_rectangle(inset, inset, W - inset, H - inset, outline=color,
                               width=max(1, round(3*s)), tags=tags)

        # Mặt gỗ với vân gỗ (cố định nhờ seed).
        c.create_rectangle(12*s, 12*s, W - 12*s, H - 12*s,
                           fill=self.colors['board'], outline='', tags=tags)
        rng = random.Random(20240907)
        grains = ('#D8A55E', '#E9BF7C', '#D49D55', '#EDC687', '#DBA962', '#E6B873')
        for _ in range(60):
            y0 = rng.uniform(16, 584)
            amp = rng.uniform(1.0, 5.5)
            freq = rng.uniform(0.008, 0.022)
            phase = rng.uniform(0, 2*math.pi)
            drift = rng.uniform(-6, 6)
            points = []
            for k in range(14):
                x = 12 + k * (516 / 13)
                y = y0 + amp*math.sin(freq*x*3 + phase) + drift*(k/13)
                points += [x*s, min(587, max(13, y))*s]
            c.create_line(*points, fill=rng.choice(grains), smooth=True,
                          width=max(1, round(rng.choice((1, 1, 1, 2))*s)), tags=tags)
        for i, color in enumerate(('#B98443', '#C99550', '#D5A25D')):
            inset = (12 + i*2)*s
            c.create_rectangle(inset, inset, W - inset, H - inset, outline=color,
                               width=max(1, round(2*s)), tags=tags)

        line_color = self.colors['board_line']
        thin = max(1, round(1.2*s))
        thick = max(2, round(2.6*s))
        # Viền đôi quanh lưới.
        c.create_rectangle(24*s, 24*s, 516*s, 576*s, outline=line_color,
                           width=max(1, round(s)), tags=tags)
        for i in range(10):
            c.create_line(30*s, (30 + i*60)*s, 510*s, (30 + i*60)*s,
                          width=thick if i in (0, 9) else thin, fill=line_color, tags=tags)
        for j in range(9):
            x = (30 + j*60)*s
            if j in (0, 8):
                c.create_line(x, 30*s, x, 570*s, width=thick, fill=line_color, tags=tags)
            else:
                c.create_line(x, 30*s, x, 270*s, width=thin, fill=line_color, tags=tags)
                c.create_line(x, 330*s, x, 570*s, width=thin, fill=line_color, tags=tags)

        # Cửu cung.
        for (x1, y1, x2, y2) in ((210, 30, 330, 150), (330, 30, 210, 150),
                                 (210, 450, 330, 570), (330, 450, 210, 570)):
            c.create_line(x1*s, y1*s, x2*s, y2*s, width=thin, fill=line_color, tags=tags)

        # Sông: chữ khắc nổi (bóng sáng lệch xuống dưới phải).
        river_font = ("Segoe UI Semibold", max(9, round(15*s)))
        for x, text in ((150*s, "SỞ   HÀ"), (390*s, "HÁN   GIỚI")):
            c.create_text(x + max(1, round(s)), 300*s + max(1, round(s)), text=text,
                          font=river_font, fill='#F3D59C', tags=tags)
            c.create_text(x, 300*s, text=text, font=river_font, fill='#7A4520', tags=tags)

        # Tọa độ cột (đọc lịch sử nước đi) đặt sát mép dưới sông: không quân nào che.
        coordinate_font = ("Consolas", max(6, round(8*s)), "bold")
        for display_col in range(9):
            file_col = 8 - display_col if self.is_flipped else display_col
            label = chr(ord('a') + file_col)
            x = (30 + display_col*60)*s
            c.create_text(x + 6*s, 321*s, text=label, font=coordinate_font,
                          fill='#A8743C', tags=tags)

        # Dấu góc tại vị trí Pháo và Tốt.
        marked_points = [(2, 1), (2, 7), (7, 1), (7, 7)]
        marked_points += [(row, col) for row in (3, 6) for col in range(0, 9, 2)]
        for row, col in marked_points:
            x, y = self.display_xy(row, col)
            self.draw_position_mark(x, y, line_color, tags)

    def draw_markers(self):
        c = self.canvas
        s = self.board_scale
        tags = ('dyn',)

        if self.last_move:
            (r1, c1), (r2, c2) = self.last_move
            x, y = self.display_xy(r1, c1)
            c.create_image(x, y, image=self.ring_image(10*s, 2.6*s, '#F59E0B', 0.8),
                           tags=tags)
            x, y = self.display_xy(r2, c2)
            c.create_image(x, y, image=self.glow_image(36*s, '#FBBF24', 0.6, 0.62),
                           tags=tags)

        if not self.game_over and XiangqiRules.is_in_check(self.board, self.turn):
            king = XiangqiRules.find_king(self.board, self.turn)
            if king:
                x, y = self.display_xy(*king)
                c.create_image(x, y, image=self.check_glow_frames()[0],
                               tags=('dyn', 'check_glow'))

        if self.selected_piece:
            x, y = self.display_xy(*self.selected_piece)
            c.create_image(x, y - 4*s, image=self.glow_image(38*s, '#FDE047', 0.65, 0.55),
                           tags=tags)
            sr, sc = self.selected_piece
            dot = self.dot_image(7*s, '#0F3D2E', 0.5)
            target_ring = self.ring_image(27*s, 3.4*s, '#DC2626', 0.9, 0.22)
            for er in range(10):
                for ec in range(9):
                    if not XiangqiRules.is_legal_move(
                            self.board, (sr, sc), (er, ec), self.turn):
                        continue
                    x, y = self.display_xy(er, ec)
                    image = target_ring if self.board[er][ec] != '.' else dot
                    c.create_image(x, y, image=image, tags=tags)

    def draw_pieces(self):
        s = self.board_scale
        for r in range(10):
            for col in range(9):
                piece = self.board[r][col]
                if piece == '.' or (r, col) == self.animation_hidden_square:
                    continue
                x, y = self.display_xy(r, col)
                self.draw_piece_at(
                    x, y, piece, selected=self.selected_piece == (r, col),
                    tags=('dyn', 'piece'), scale=s
                )

    def draw_result_banner(self):
        c = self.canvas
        s = self.board_scale
        width, height = round(400*s), round(128*s)
        cx, cy = 270*s, 300*s
        if self.winner == 'w':
            title_color, border = '#F87171', '#EF4444'
        elif self.winner == 'b':
            title_color, border = '#E2E8F0', '#94A3B8'
        else:
            title_color, border = '#FCD34D', '#F59E0B'
        image = self.panel_image(width, height, 20*s, '#0B1120', 0.86,
                                 border, 0.9, max(1.5, 2*s))
        tags = ('dyn', 'banner')
        c.create_image(cx, cy, image=image, tags=tags)
        c.create_text(cx, cy - 30*s, text=self.result_title, fill=title_color,
                      font=("Segoe UI", max(14, round(28*s)), "bold"), tags=tags)
        c.create_text(cx, cy + 8*s, text=self.result_reason, fill='#E2E8F0',
                      font=("Segoe UI", max(8, round(11*s))), tags=tags)
        c.create_text(cx, cy + 38*s,
                      text="Bấm vào bàn cờ để xem thế cờ  •  VÁN MỚI để chơi tiếp",
                      fill='#94A3B8', font=("Segoe UI", max(7, round(8*s))), tags=tags)

    def draw_hover(self):
        square = self.hover_square
        if not square or not self.can_interact() or square == self.selected_piece:
            return
        piece = self.board[square[0]][square[1]]
        if XiangqiRules.side_of(piece) != self.turn:
            return
        s = self.board_scale
        x, y = self.display_xy(*square)
        self.canvas.create_image(
            x, y, image=self.ring_image(27*s, 2.2*s, '#FFFFFF', 0.7, 0.25), tags=('hover',)
        )

    def draw_position_mark(self, x, y, color, tags=()):
        scale = self.board_scale
        for sx in (-1, 1):
            for sy in (-1, 1):
                # Không vẽ dấu ra ngoài biên bàn.
                if ((abs(x - 30*scale) < 0.1 and sx == -1)
                        or (abs(x - 510*scale) < 0.1 and sx == 1)):
                    continue
                self.canvas.create_line(
                    x + sx*7*scale, y + sy*13*scale,
                    x + sx*7*scale, y + sy*7*scale,
                    x + sx*13*scale, y + sy*7*scale,
                    fill=color, width=max(1, round(scale)), tags=tags
                )

    def draw_piece_at(
            self, x, y, piece, selected=False, tags=(),
            target_canvas=None, scale=1.0, lifted=False):
        canvas = target_canvas or self.canvas
        side = 'w' if piece.isupper() else 'b'
        lifted = lifted or selected
        y -= 4*scale if lifted else 0
        canvas.create_image(x, y, image=self.piece_image(side, 25*scale, lifted), tags=tags)
        glyph = PIECE_GLYPHS.get(piece, piece)
        font = ("Microsoft YaHei", max(7, round(19*scale)), "bold")
        # Chữ khắc chìm: viền sáng lệch xuống dưới phải rồi nét mực đè lên.
        offset = max(1, round(scale))
        canvas.create_text(x + offset, y - scale + offset, text=glyph, fill='#FFFBF2',
                           font=font, tags=tags)
        canvas.create_text(x, y - scale, text=glyph, fill=PIECE_INK[side],
                           font=font, tags=tags)

    def update_captured_display(self):
        values = {'R': 9, 'N': 4, 'B': 2, 'A': 2, 'C': 4.5, 'P': 1, 'K': 0}

        def draw_captures(side, canvas, title_label, align_right=False):
            pieces = self.captured_by[side]
            canvas.delete('all')
            if not pieces:
                title_label.config(text=("ĐỎ ĐÃ ĂN" if side == 'w' else "ĐEN ĐÃ ĂN"))
                return

            score = sum(values[piece.upper()] for piece in pieces)
            title = "ĐỎ ĐÃ ĂN" if side == 'w' else "ĐEN ĐÃ ĂN"
            title_label.config(text=f"{title}   •   +{score:g}")

            canvas.update_idletasks()
            scale = self.board_scale
            width = max(220*scale, canvas.winfo_width())
            piece_diameter = 28*scale
            available = width - piece_diameter - 4*scale
            spacing = min(
                piece_diameter + 2*scale,
                available / max(1, len(pieces) - 1)
            )
            if align_right:
                start_x = (
                    width - piece_diameter/2 - 3*scale
                    - spacing*(len(pieces) - 1)
                )
            else:
                start_x = piece_diameter/2 + 3*scale

            for index, piece in enumerate(pieces):
                self.draw_piece_at(
                    start_x + index*spacing, 16*scale, piece,
                    target_canvas=canvas, scale=0.53*scale
                )

        draw_captures(
            'w', self.red_capture_canvas, self.lbl_red_capture_title
        )
        draw_captures(
            'b', self.black_capture_canvas, self.lbl_black_capture_title,
            align_right=True
        )

    def update_turn_indicator(self):
        """Khay quân ăn được của bên đang tới lượt sáng viền lên."""
        active = None if self.game_over else self.turn
        if active == self.turn_indicator_state:
            return
        self.turn_indicator_state = active
        self.red_capture_frame.config(
            highlightbackground='#F87171' if active == 'w' else '#5B1A1A',
            highlightcolor='#F87171' if active == 'w' else '#5B1A1A',
        )
        self.black_capture_frame.config(
            highlightbackground='#CBD5E1' if active == 'b' else '#2B3D2E',
            highlightcolor='#CBD5E1' if active == 'b' else '#2B3D2E',
        )
        self.lbl_red_capture_title.config(fg='#FECACA' if active == 'w' else '#B07A7A')
        self.lbl_black_capture_title.config(fg='#E2E8F0' if active == 'b' else '#7E9A82')

    # ------------------------------------------------------------------
    # Thanh ưu thế
    # ------------------------------------------------------------------
    def draw_eval_bar(self):
        bar = self.eval_bar
        bar.delete('all')
        width = bar.winfo_width()
        height = int(bar.cget('height'))
        if width <= 1:
            return
        split = round(width * self.eval_fraction)
        bar.create_rectangle(0, 0, width, height, fill='#475569', outline='')
        bar.create_rectangle(0, 0, split, height, fill='#EF4444', outline='')
        bar.create_rectangle(0, 0, split, max(1, height // 3), fill='#F87171', outline='')
        bar.create_line(width / 2, 0, width / 2, height, fill='#0B1120', width=2)
        self.draw_rail_eval_bar()

    def draw_rail_eval_bar(self):
        """Thanh ưu thế dọc khi thu gọn: phần đỏ nằm phía quân Đỏ trên bàn."""
        bar = getattr(self, 'rail_eval', None)
        if bar is None or not self.panel_collapsed:
            return
        bar.delete('all')
        width, height = bar.winfo_width(), bar.winfo_height()
        if width <= 1 or height <= 1:
            return
        red = round(height * self.eval_fraction)
        bar.create_rectangle(0, 0, width, height, fill='#475569', outline='')
        if self.is_flipped:
            bar.create_rectangle(0, 0, width, red, fill='#EF4444', outline='')
        else:
            bar.create_rectangle(0, height - red, width, height, fill='#EF4444', outline='')
        bar.create_line(0, height / 2, width, height / 2, fill='#0B1120', width=2)

    def set_eval_target(self, fraction):
        self.eval_target = max(0.0, min(1.0, fraction))
        if self.eval_tween_active:
            return
        self.eval_tween_active = True
        last = {'t': time.perf_counter()}

        def step(now):
            dt = now - last['t']
            last['t'] = now
            diff = self.eval_target - self.eval_fraction
            if abs(diff) < 0.002:
                self.eval_fraction = self.eval_target
                self.draw_eval_bar()
                self.eval_tween_active = False
                return False
            self.eval_fraction += diff * (1.0 - math.exp(-dt * 9.0))
            self.draw_eval_bar()
            return True

        self.add_effect(step)

    def reset_eval_display(self):
        self.set_eval_label("+0.00", self.colors['success'])
        self.update_depth_label_display()
        self.set_eval_target(0.5)

    # ------------------------------------------------------------------
    # Hiệu ứng: một vòng lặp ~60 FPS chạy các hàm step(now) -> còn sống?
    # ------------------------------------------------------------------
    def add_effect(self, step):
        self.effects.append(step)
        if self.fx_job is None:
            self.fx_job = self.root.after(0, self.fx_tick)

    def fx_tick(self):
        self.fx_job = None
        now = time.perf_counter()
        alive = []
        for step in self.effects:
            try:
                keep = step(now)
            except tk.TclError:
                keep = False
            if keep:
                alive.append(step)
        self.effects = alive
        if alive:
            self.fx_job = self.root.after(16, self.fx_tick)

    def clear_effects(self):
        if self.fx_job is not None:
            self.root.after_cancel(self.fx_job)
            self.fx_job = None
        self.effects = []
        self.canvas.delete('fx')
        self.check_pulse_active = False
        if self.eval_tween_active:
            self.eval_tween_active = False
            self.eval_fraction = self.eval_target
            self.draw_eval_bar()

    def effects_enabled(self):
        return self.animation_var.get()

    def ensure_check_pulse(self):
        if (self.check_pulse_active or not self.effects_enabled()
                or not self.canvas.find_withtag('check_glow')):
            return
        self.check_pulse_active = True
        frames = self.check_glow_frames()
        start = time.perf_counter()

        def step(now):
            if not self.canvas.find_withtag('check_glow'):
                self.check_pulse_active = False
                return False
            phase = (math.sin((now - start) * 2*math.pi * 1.2) + 1) / 2
            self.canvas.itemconfig('check_glow', image=frames[round(phase * (len(frames) - 1))])
            return True

        self.add_effect(step)

    def spawn_ripple(self, x, y, color):
        s = self.board_scale
        item = self.canvas.create_oval(x, y, x, y, outline=color,
                                       width=max(1, round(3*s)), tags=('fx',))
        start = time.perf_counter()
        duration = 0.45

        def step(now):
            t = (now - start) / duration
            if t >= 1.0:
                self.canvas.delete(item)
                return False
            r = (24 + 24*ease_out_cubic(t)) * s
            self.canvas.coords(item, x - r, y - r, x + r, y + r)
            self.canvas.itemconfig(item, outline=mix_hex(color, self.colors['board'], t),
                                   width=max(1, round(3*s*(1 - t) + 0.5)))
            return True

        self.add_effect(step)

    def spawn_capture_burst(self, x, y, captured_piece):
        s = self.board_scale
        if captured_piece.isupper():
            palette = ('#EF4444', '#F97316', '#FCD34D', '#FFF7ED')
        else:
            palette = ('#1E293B', '#475569', '#CBD5E1', '#F8FAFC')
        particles = []
        for i in range(18):
            angle = 2*math.pi*i/18 + random.uniform(-0.25, 0.25)
            speed = random.uniform(110, 240) * s
            size = random.uniform(2.2, 4.8) * s
            item = self.canvas.create_oval(x, y, x, y, fill=random.choice(palette),
                                           outline='', tags=('fx',))
            particles.append((item, math.cos(angle)*speed, math.sin(angle)*speed - 50*s, size))
        start = time.perf_counter()
        duration = 0.6
        gravity = 480 * s

        def step(now):
            elapsed = now - start
            t = elapsed / duration
            if t >= 1.0:
                for item, *_rest in particles:
                    self.canvas.delete(item)
                return False
            for item, vx, vy, size in particles:
                px = x + vx*elapsed*(1 - 0.4*t)
                py = y + vy*elapsed + 0.5*gravity*elapsed*elapsed
                r = size * (1 - t)
                self.canvas.coords(item, px - r, py - r, px + r, py + r)
            return True

        self.add_effect(step)

    def show_toast(self, text, color):
        """Thông báo nổi giữa bàn cờ (vd. CHIẾU TƯỚNG!), tự trượt vào rồi biến mất."""
        c = self.canvas
        s = self.board_scale
        c.delete('toast')
        font = tkfont.Font(root=self.root, family="Segoe UI",
                           size=max(10, round(16*s)), weight="bold")
        # Bề rộng theo độ dài chữ, làm tròn 8 px để dùng lại sprite.
        width = min(round(500*s), max(round(210*s), (font.measure(text) + round(56*s)) // 8 * 8))
        height = round(54*s)
        image = self.panel_image(width, height, height / 2, color, 0.93,
                                 '#FFFFFF', 0.35, max(1.0, 1.5*s))
        cx, cy = 270*s, 300*s
        animate = self.effects_enabled()
        offset = -16*s if animate else 0.0
        image_item = c.create_image(cx, cy + offset, image=image, tags=('fx', 'toast'))
        c.create_text(cx, cy + offset - s, text=text, fill='#FFFFFF',
                      font=font, tags=('fx', 'toast'))
        start = time.perf_counter()
        state = {'dy': offset}

        def step(now):
            elapsed = now - start
            if not c.find_withtag(image_item):
                return False
            if elapsed >= 1.15:
                c.delete('toast')
                return False
            if not animate:
                return True
            if elapsed < 0.2:
                target = offset * (1 - ease_out_cubic(elapsed / 0.2))
            elif elapsed < 0.95:
                target = 0.0
            else:
                target = -14*s * ease_in_out_cubic((elapsed - 0.95) / 0.2)
            c.move('toast', 0, target - state['dy'])
            state['dy'] = target
            return True

        self.add_effect(step)

    def spawn_confetti(self):
        c = self.canvas
        s = self.board_scale
        palette = ('#F59E0B', '#EF4444', '#38BDF8', '#22C55E', '#F472B6', '#FDE68A', '#A78BFA')
        pieces = []
        for _ in range(80):
            item = c.create_polygon(0, 0, 0, 0, 0, 0, 0, 0, fill=random.choice(palette),
                                    outline='', tags=('fx', 'confetti'))
            pieces.append({
                'item': item,
                'x': random.uniform(10, 530) * s,
                'y': random.uniform(-280, -10) * s,
                'vy': random.uniform(120, 250) * s,
                'sway': random.uniform(8, 34) * s,
                'freq': random.uniform(2.0, 5.0),
                'phase': random.uniform(0, 2*math.pi),
                'spin': random.uniform(-9, 9),
                'w': random.uniform(3, 5) * s,
                'h': random.uniform(6, 10) * s,
            })
        start = time.perf_counter()
        duration = 3.6

        def step(now):
            elapsed = now - start
            if elapsed >= duration:
                c.delete('confetti')
                return False
            for p in pieces:
                cx = p['x'] + p['sway'] * math.sin(p['freq']*elapsed + p['phase'])
                cy = p['y'] + p['vy'] * elapsed
                angle = p['spin'] * elapsed + p['phase']
                ca, sa = math.cos(angle), math.sin(angle)
                hw = p['w'] / 2
                hh = p['h'] / 2 * (0.25 + 0.75*abs(math.cos(angle*0.7)))
                points = []
                for dx, dy in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)):
                    points += [cx + dx*ca - dy*sa, cy + dx*sa + dy*ca]
                c.coords(p['item'], *points)
            return True

        self.add_effect(step)

    def play_landing_effects(self, end, captured_piece):
        if not self.effects_enabled():
            return
        x, y = self.board_to_canvas(end)
        if captured_piece != '.':
            self.spawn_ripple(x, y, '#F97316')
            self.spawn_capture_burst(x, y, captured_piece)
        else:
            self.spawn_ripple(x, y, '#FDE68A')

    # ------------------------------------------------------------------
    # Chuột
    # ------------------------------------------------------------------
    def can_interact(self):
        return not (self.is_engine_thinking or self.engine_stopping
                    or self.is_animating or self.game_over)

    def event_square(self, event):
        scale = self.board_scale
        c = round((event.x / scale - 30) / 60)
        r = round((event.y / scale - 30) / 60)
        if self.is_flipped:
            c = 8 - c
            r = 9 - r
        if 0 <= r < 10 and 0 <= c < 9:
            return r, c
        return None

    def on_canvas_motion(self, event):
        square = self.event_square(event)
        if square == self.hover_square:
            return
        self.hover_square = square
        self.canvas.delete('hover')
        self.draw_hover()
        self.canvas.tag_raise('moving')
        self.canvas.tag_raise('fx')

        clickable = False
        if square and self.can_interact():
            piece = self.board[square[0]][square[1]]
            clickable = XiangqiRules.side_of(piece) == self.turn or (
                self.selected_piece is not None and XiangqiRules.is_legal_move(
                    self.board, self.selected_piece, square, self.turn))
        self.canvas.config(cursor='hand2' if clickable else '')

    def on_canvas_leave(self, _event):
        self.hover_square = None
        self.canvas.delete('hover')

    def on_click(self, event):
        if self.game_over and not self.banner_dismissed and not self.is_animating:
            self.banner_dismissed = True
            self.draw_board()
            return
        if not self.can_interact():
            return

        square = self.event_square(event)
        if square is None:
            return
        r, c = square
        if self.selected_piece:
            sr, sc = self.selected_piece
            if (sr, sc) == (r, c):
                self.selected_piece = None
                self.draw_board()
                return

            # Bấm một quân cùng bên thì chuyển lựa chọn sang quân đó.
            if XiangqiRules.side_of(self.board[r][c]) == self.turn:
                self.selected_piece = (r, c)
                self.play_sound('select')
                self.draw_board()
                return

            if not XiangqiRules.is_legal_move(
                    self.board, (sr, sc), (r, c), self.turn):
                self.set_status("Nước đi không hợp lệ", 'error')
                self.play_sound('invalid')
                return

            self.apply_move(
                (sr, sc), (r, c), "Người", self.after_human_move
            )
        else:
            if XiangqiRules.side_of(self.board[r][c]) == self.turn:
                self.selected_piece = (r, c)
                self.play_sound('select')
                self.draw_board()
            elif self.board[r][c] != '.':
                side_name = "Đỏ" if self.turn == 'w' else "Đen"
                self.set_status(f"Đang tới lượt {side_name}", 'warning')
                self.play_sound('invalid')

    @staticmethod
    def move_to_text(start, end):
        sr, sc = start
        er, ec = end
        return f"{chr(sc + 97)}{9 - sr}{chr(ec + 97)}{9 - er}"

    @staticmethod
    def parse_move(move):
        if len(move) < 4:
            return None
        try:
            start = (9 - int(move[1]), ord(move[0]) - ord('a'))
            end = (9 - int(move[3]), ord(move[2]) - ord('a'))
        except (ValueError, IndexError):
            return None
        if not (0 <= start[0] < 10 and 0 <= end[0] < 10
                and 0 <= start[1] < 9 and 0 <= end[1] < 9):
            return None
        return start, end

    def board_to_canvas(self, position):
        row, col = position
        display_r = 9 - row if self.is_flipped else row
        display_c = 8 - col if self.is_flipped else col
        scale = self.board_scale
        return (30 + display_c * 60)*scale, (30 + display_r * 60)*scale

    def apply_move(self, start, end, actor, after_animation=None):
        self.save_state_for_undo()
        sr, sc = start
        er, ec = end
        piece = self.board[sr][sc]
        captured_piece = self.board[er][ec]
        captured = captured_piece != '.'
        if captured:
            self.captured_by[self.turn].append(captured_piece)
        self.board[er][ec] = self.board[sr][sc]
        self.board[sr][sc] = '.'
        self.last_move = (start, end)
        move_text = self.move_to_text(start, end)
        mover = self.turn
        self.add_history(len(self.move_list) + 1, mover, move_text, actor)
        self.turn = XiangqiRules.opponent(self.turn)
        self.selected_piece = None

        self.move_list.append(move_text)
        self.halfmove_clock = 0 if captured else self.halfmove_clock + 1
        self.update_opening_label()
        self.update_captured_display()

        def finish_move():
            result = self.current_game_result()
            if result:
                self.play_sound('victory' if result[1] else 'draw')
            elif XiangqiRules.is_in_check(self.board, self.turn):
                self.play_sound('check')
                self.show_toast("CHIẾU TƯỚNG!", '#DC2626')
            elif captured:
                self.play_sound('capture')
            else:
                self.play_sound('move')
            self.update_game_status()
            if after_animation:
                after_animation()

        self.animate_piece(piece, start, end, finish_move, captured_piece)

    def animate_piece(self, piece, start, end, on_complete, captured_piece='.'):
        """Quân nhấc lên, bay theo cung (ease-in-out), hạ xuống kèm gợn sóng/vỡ quân.

        Quân bị ăn vẫn hiện tại chỗ cho tới khi quân đi chạm tới.
        """
        if not self.animation_var.get():
            self.draw_board()
            on_complete()
            return

        self.cancel_animation(redraw=False)
        self.is_animating = True
        self.animation_hidden_square = end
        self.canvas.delete('hover')
        self.draw_board()

        s = self.board_scale
        start_x, start_y = self.board_to_canvas(start)
        end_x, end_y = self.board_to_canvas(end)
        if captured_piece != '.':
            self.draw_piece_at(end_x, end_y, captured_piece,
                               tags=('moving', 'moving_victim'), scale=s)
        self.draw_piece_at(start_x, start_y, piece,
                           tags=('moving', 'moving_piece'), scale=s, lifted=True)
        self.canvas.tag_raise('moving_piece')
        self.canvas.tag_raise('fx')

        distance = math.hypot(end_x - start_x, end_y - start_y) / (60 * s)
        duration = min(0.38, 0.18 + 0.035 * distance)
        lift_height = (4 + 2.4 * min(distance, 5)) * s
        start_time = time.perf_counter()
        state = {'x': start_x, 'y': start_y}

        def step():
            t = min(1.0, (time.perf_counter() - start_time) / duration)
            eased = ease_in_out_cubic(t)
            next_x = start_x + (end_x - start_x) * eased
            next_y = (start_y + (end_y - start_y) * eased
                      - math.sin(math.pi * t) * lift_height)
            self.canvas.move('moving_piece', next_x - state['x'], next_y - state['y'])
            state['x'], state['y'] = next_x, next_y

            if t < 1.0:
                self.animation_job = self.root.after(12, step)
                return

            self.animation_job = None
            self.is_animating = False
            self.animation_hidden_square = None
            self.canvas.delete('moving')
            # Áp dụng kích thước mới nếu cửa sổ được resize giữa animation.
            self.on_board_area_resize()
            self.draw_board()
            self.play_landing_effects(end, captured_piece)
            on_complete()

        self.animation_job = self.root.after(12, step)

    def cancel_animation(self, redraw=True):
        if self.animation_job is not None:
            try:
                self.root.after_cancel(self.animation_job)
            except tk.TclError:
                pass
        self.animation_job = None
        self.is_animating = False
        self.animation_hidden_square = None
        if hasattr(self, 'canvas'):
            self.canvas.delete('moving')
            if redraw:
                self.on_board_area_resize()
                self.draw_board()

    def after_human_move(self):
        # Người không đi đúng nước engine đoán: bỏ lượt ponder, tìm lại từ đầu.
        if self.is_pondering and (self.game_over or self.move_list != self.ponder_moves):
            self.stop_pondering()
        if not self.game_over and self.auto_reply_var.get():
            self.root.after(100, self.trigger_engine)

    def prepare_sounds(self):
        """Chạy ở luồng phụ: tạo file WAV một lần (lần sau dùng lại từ thư mục tạm)."""
        try:
            self.sound_files = ensure_sound_files(default_sound_dir())
        except OSError:
            self.sound_files = {}

    def play_sound(self, sound_name):
        if winsound is None or not self.sound_var.get():
            return
        path = self.sound_files.get(sound_name)
        if path is None:
            return
        try:
            winsound.PlaySound(
                str(path),
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
            )
        except RuntimeError:
            pass

    def set_status(self, text, tone='normal'):
        colors = {
            'normal': self.colors['success'],
            'thinking': self.colors['accent'],
            'warning': self.colors['gold'],
            'error': self.colors['danger'],
        }
        self.lbl_status.config(text=text)
        self.status_dot.config(fg=colors.get(tone, self.colors['success']))
        self.rail_dot.config(fg=colors.get(tone, self.colors['success']))
        self.status_tone = tone
        if tone == 'thinking' and self.status_pulse_job is None:
            self.pulse_status_dot()

    def pulse_status_dot(self):
        """Chấm trạng thái nhấp nháy nhẹ khi máy đang nghĩ."""
        if self.status_tone != 'thinking':
            self.status_pulse_job = None
            return
        phase = (math.sin(time.perf_counter() * 2*math.pi * 1.3) + 1) / 2
        pulse = mix_hex('#164E63', self.colors['accent'], phase)
        self.status_dot.config(fg=pulse)
        self.rail_dot.config(fg=pulse)
        self.status_pulse_job = self.root.after(50, self.pulse_status_dot)

    def current_game_result(self):
        return (XiangqiRules.game_result(self.board, self.turn)
                or XiangqiRules.rule60_result(self.halfmove_clock))

    def update_game_status(self):
        result = self.current_game_result()
        if result:
            was_over = self.game_over
            reason, self.winner = result
            self.game_over = True
            if self.winner is None:
                reason_text = {
                    'rule60': "60 nước không ăn quân",
                }.get(reason, reason)
                self.result_title = "HÒA CỜ"
                self.result_reason = f"Ván cờ hòa do {reason_text}"
                self.set_status(f"Hòa — {reason_text}", 'warning')
            else:
                winner_name = "Đỏ" if self.winner == 'w' else "Đen"
                reason_text = {
                    'checkmate': "chiếu bí",
                    'stalemate': "đối phương hết nước đi",
                }.get(reason, reason)
                self.result_title = f"{winner_name.upper()} THẮNG"
                self.result_reason = f"{winner_name} thắng do {reason_text}"
                self.set_status(f"{winner_name} thắng — {reason_text}", 'warning')
            if not was_over:
                self.banner_dismissed = False
                self.canvas.delete('toast')
                if self.winner and self.effects_enabled():
                    self.spawn_confetti()
            self.draw_board()
            return True

        self.game_over = False
        self.winner = None
        if XiangqiRules.is_in_check(self.board, self.turn):
            checked_name = "Đỏ" if self.turn == 'w' else "Đen"
            self.set_status(f"{checked_name} đang bị chiếu!", 'error')
        else:
            side_name = "Đỏ" if self.turn == 'w' else "Đen"
            self.set_status(f"Lượt {side_name}")
        return False

    def save_state_for_undo(self):
        self.state_stack.append({
            'board': copy.deepcopy(self.board),
            'turn': self.turn,
            'last_move': self.last_move,
            'game_over': self.game_over,
            'winner': self.winner,
            'captured_by': copy.deepcopy(self.captured_by),
            'move_list': list(self.move_list),
            'halfmove_clock': self.halfmove_clock,
        })

    def cancel_pending_action(self):
        """Hủy an toàn nước book, lượt tìm kiếm hoặc lượt ponder đang chạy."""
        self.search_after_drain = False
        self.pending_opening_toast = None
        self.cancel_animation(redraw=False)
        if self.pending_book_job is not None:
            try:
                self.root.after_cancel(self.pending_book_job)
            except tk.TclError:
                pass
            self.pending_book_job = None

        if self.is_pondering:
            self.stop_pondering()
        elif self.is_engine_thinking and self.active_search_source == 'engine':
            self.search_cancelled = True
            self.engine_stopping = True
            self.send_engine("stop")

        self.is_engine_thinking = False
        if not self.engine_stopping:
            self.active_search_source = None
        self.set_go_button(text="⚙  MÁY ĐI", bg=self.colors['accent_dark'])

    def undo_move(self):
        self.cancel_pending_action()

        if len(self.state_stack) > 0:
            last_state = self.state_stack.pop()
            self.board = last_state['board']
            self.turn = last_state['turn']
            self.last_move = last_state['last_move']
            self.game_over = last_state['game_over']
            self.winner = last_state['winner']
            self.captured_by = last_state['captured_by']
            self.move_list = last_state['move_list']
            self.halfmove_clock = last_state['halfmove_clock']
            self.selected_piece = None
            self.update_opening_label()

            if self.listbox_moves.size() > 0:
                self.listbox_moves.delete(tk.END)
            self.update_move_count()

            self.banner_dismissed = False
            self.canvas.delete('toast')
            self.canvas.delete('confetti')
            self.reset_eval_display()
            self.update_captured_display()
            self.draw_board()
            self.update_game_status()
            self.play_sound('move')

    def flip_board(self):
        self.root.after_idle(self.draw_rail_eval_bar)
        if self.is_animating:
            return
        self.is_flipped = not self.is_flipped
        self.draw_board()

    def new_game(self):
        self.cancel_pending_action()

        self.board = copy.deepcopy(self.initial_board)

        mode = self.mode_var.get()
        if mode == "Cả 2 bên Liệt Tốt 5":
            self.board[6][4] = '.'
            self.board[3][4] = '.'
        elif mode == "Cả 2 bên Liệt Tốt 1":
            self.board[6][8] = '.'
            self.board[3][0] = '.'
        elif mode == "Đỏ Chấp 1 Mã":
            self.board[9][1] = '.'

        self.turn = 'w'
        self.reset_game_history()
        self.update_opening_label()
        self.state_stack.clear()
        self.listbox_moves.delete(0, tk.END)
        self.update_move_count()
        self.selected_piece = None
        self.last_move = None
        self.is_flipped = False
        self.game_over = False
        self.winner = None
        self.captured_by = {'w': [], 'b': []}
        self.banner_dismissed = False

        self.clear_effects()
        self.reset_eval_display()
        self.send_engine("ucinewgame")
        self.update_captured_display()
        self.draw_board()
        self.set_status("Lượt Đỏ")
        self.play_sound('start')

    def trigger_engine(self):
        if self.game_over or self.is_engine_thinking or self.is_animating:
            return
        if not self.engine_process or self.engine_process.poll() is not None:
            self.set_status("Engine chưa sẵn sàng", 'error')
            return
        if not self.engine_ready:
            self.set_status("Engine đang khởi động, thử lại sau giây lát", 'warning')
            return

        if self.is_pondering:
            if self.move_list == self.ponder_moves:
                self.ponderhit()
                return
            self.stop_pondering()

        if self.engine_stopping:
            # Chờ engine trả bestmove của lượt cũ rồi tự tìm lại.
            self.search_after_drain = True
            self.set_status("Đang chờ engine dừng lượt cũ", 'warning')
            return

        current_fen = self.generate_fen()

        # --- LOGIC TRA CỨU BOOK KHAI CUỘC ---
        # Phong cách Lạ/Rất lạ và khai cuộc chọn đích danh được ưu tiên hơn sách.
        if (self.use_book_var.get()
                and self.search_mode_for_ply(len(self.move_list)) not in ('style', 'named')):
            if current_fen in self.opening_book:
                # Không tin dữ liệu book tuyệt đối: luôn lọc lại bằng luật hiện tại.
                legal_book_moves = []
                for move in self.opening_book[current_fen]:
                    parsed = self.parse_move(move)
                    if parsed and XiangqiRules.is_legal_move(
                            self.board, parsed[0], parsed[1], self.turn):
                        legal_book_moves.append(move)

                if legal_book_moves:
                    self.is_engine_thinking = True
                    self.active_search_source = 'book'
                    self.set_go_button(text="ĐANG ĐỌC SÁCH...", bg=self.colors['gold'])
                    self.set_status("Đang đọc sách khai cuộc", 'thinking')
                    chosen_move = random.choice(legal_book_moves)
                    self.pending_book_job = self.root.after(
                        300, self.apply_engine_move, chosen_move, True
                    )
                    return

        # --- NẾU HẾT BOOK HOẶC KHÔNG BẬT BOOK -> GỌI ENGINE TÍNH TOÁN ---
        self.start_search()

    def search_mode_for_ply(self, ply):
        """'named' (khai cuộc chọn đích danh) / 'style' (Lạ, Rất lạ) cho nước đầu
        mỗi bên, 'varied' (Đa dạng) hoặc 'normal'."""
        style = self.opening_style_var.get()
        if ply <= 1 and named_opening_from_style(style):
            return 'named'
        if style in (STYLE_ODD, STYLE_VERY_ODD) and ply <= 1:
            return 'style'
        if style == STYLE_VARIED and ply < VARIETY_PLIES:
            return 'varied'
        return 'normal'

    def legal_catalogue_moves(self):
        moves = []
        for move in catalogue_moves(self.turn):
            parsed = self.parse_move(move)
            if parsed and XiangqiRules.is_legal_move(
                    self.board, parsed[0], parsed[1], self.turn):
                moves.append(move)
        return moves

    def start_search(self):
        limit = self.limit_var.get()
        mode = self.search_mode_for_ply(len(self.move_list))
        named_opening = named_opening_from_style(self.opening_style_var.get())
        unavailable = None
        go_command = build_go_command(limit)
        multipv = 1
        if mode == 'style':
            # Chấm điểm riêng từng nước đầu trong danh mục (searchmoves + MultiPV)
            # rồi mới chọn nước lạ đủ an toàn ở handle_engine_bestmove.
            candidates = self.legal_catalogue_moves()
            if len(candidates) >= 2:
                multipv = len(candidates)
                go_command = (build_opening_go_command(limit)
                              + " searchmoves " + " ".join(candidates))
            else:
                mode = 'normal'
        elif mode == 'named':
            # Chỉ cho engine chọn trong các nước tạo ra khai cuộc đã chọn
            # (thường là hai bản đối xứng trái/phải); engine chọn bản tốt hơn.
            candidates = named_opening_candidates(
                self.move_list, self.legal_catalogue_moves(), named_opening)
            if candidates:
                go_command += " searchmoves " + " ".join(candidates)
            else:
                mode = 'normal'
                unavailable = named_opening
        elif mode == 'varied':
            multipv = VARIETY_MULTIPV
        self.search_mode = mode
        self.set_multipv(multipv)
        self.pv_candidates = {}
        self.is_engine_thinking = True
        self.active_search_source = 'engine'
        self.search_cancelled = False
        self.set_go_button(text="ĐANG TÍNH...", bg=self.colors['gold'])
        if mode == 'style':
            self.set_status(f"Pikafish đang chọn khai cuộc {self.opening_style_var.get().lower()}",
                            'thinking')
        elif mode == 'named':
            self.set_status(f"Pikafish khai cuộc {named_opening} • {limit}", 'thinking')
        elif unavailable:
            self.set_status(f"Không đi được {unavailable} ở thế này — máy chơi bình thường",
                            'warning')
        else:
            self.set_status(f"Pikafish đang nghĩ • {limit}", 'thinking')
        self.update_depth_label_display()

        # Gửi cả chuỗi nước từ đầu ván để engine nhận biết lặp nước/luật 60 nước.
        self.send_engine(self.position_command())
        self.send_engine(go_command)

    def start_ponder(self, ponder_move):
        """Cho engine nghĩ tiếp trên nước người chơi nhiều khả năng sẽ đi."""
        if (not ponder_move or not self.ponder_var.get()
                or not self.auto_reply_var.get() or self.game_over
                or not self.engine_ready or self.engine_stopping
                or self.is_engine_thinking or self.is_pondering):
            return
        # Lượt Đa dạng / Lạ cần MultiPV nên không ponder được.
        if self.search_mode_for_ply(len(self.move_list) + 1) != 'normal':
            return
        parsed = self.parse_move(ponder_move)
        if not parsed or not XiangqiRules.is_legal_move(
                self.board, parsed[0], parsed[1], self.turn):
            return

        self.ponder_moves = self.move_list + [ponder_move]
        self.is_pondering = True
        self.search_cancelled = False
        self.set_multipv(1)
        self.send_engine(self.position_command(self.ponder_moves))
        self.send_engine(build_go_command(self.limit_var.get(), ponder=True))

    def ponderhit(self):
        """Người đi đúng nước engine đoán: dùng tiếp kết quả đang tính."""
        self.is_pondering = False
        self.ponder_moves = None
        self.search_mode = 'normal'
        self.pv_candidates = {}
        self.is_engine_thinking = True
        self.active_search_source = 'engine'
        self.search_cancelled = False
        self.set_go_button(text="ĐANG TÍNH...", bg=self.colors['gold'])
        self.set_status(
            f"Pikafish đoán trúng nước, tính tiếp • {self.limit_var.get()}", 'thinking'
        )
        self.send_engine("ponderhit")

    def stop_pondering(self):
        if not self.is_pondering:
            return
        self.is_pondering = False
        self.ponder_moves = None
        # bestmove của lượt ponder sẽ bị bỏ qua trong on_cancelled_search_drained.
        self.search_cancelled = True
        self.engine_stopping = True
        self.send_engine("stop")

    def post_to_ui(self, callback, *args):
        """Gọi từ luồng đọc engine. Không chạm Tk ở đây: Tk không an toàn đa luồng."""
        self.ui_queue.put((callback, args))

    def poll_ui_queue(self):
        if self.engine_closing:
            return
        while True:
            try:
                callback, args = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            callback(*args)
            if self.engine_closing:
                return
        self.root.after(15, self.poll_ui_queue)

    def listen_engine_loop(self):
        process = self.engine_process
        while process:
            try:
                line = process.stdout.readline()
            except (OSError, ValueError):
                break
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            if not line.startswith("info") or line.startswith("info string"):
                self.engine_output_tail.append(line)

            if line == "readyok":
                self.post_to_ui(self.on_engine_ready)
            elif line.startswith("info"):
                info = parse_uci_info(line)
                if info:
                    self.post_to_ui(self.on_engine_info, info)
            elif line.startswith("bestmove"):
                parts = line.split()
                move = parts[1] if len(parts) >= 2 and parts[1] != "(none)" else None
                ponder = parts[3] if len(parts) >= 4 and parts[2] == "ponder" else None
                if move:
                    self.post_to_ui(self.handle_engine_bestmove, move, ponder)
                else:
                    self.post_to_ui(self.handle_engine_no_move)
        self.post_to_ui(self.on_engine_exit, process)

    def on_engine_info(self, info):
        if not self.is_engine_thinking or self.active_search_source != 'engine':
            return
        if info['bound'] is None and info['pv']:
            self.pv_candidates[info['multipv']] = info
        if info['multipv'] == 1:
            self.update_eval(info['score'], info['depth'])

    def on_cancelled_search_drained(self):
        self.engine_stopping = False
        self.search_cancelled = False
        self.active_search_source = None
        self.set_go_button(text="⚙  MÁY ĐI", bg=self.colors['accent_dark'])
        if self.search_after_drain:
            self.search_after_drain = False
            self.root.after(0, self.trigger_engine)

    def handle_engine_bestmove(self, move, ponder_move=None):
        if self.search_cancelled or self.engine_stopping:
            self.on_cancelled_search_drained()
            return
        if not self.is_engine_thinking or self.active_search_source != 'engine':
            return
        pv = None
        if self.search_mode == 'varied':
            pv = choose_varied_move(self.pv_candidates, VARIETY_THRESHOLD_CP)
        elif self.search_mode == 'style':
            pv = choose_style_move(self.pv_candidates, self.turn,
                                   self.opening_style_var.get())
            if pv and not is_mainstream_opening(pv[0], self.turn):
                self.pending_opening_toast = opening_name(
                    self.move_list + [pv[0]], len(self.move_list))
        elif self.search_mode == 'named':
            self.pending_opening_toast = opening_name(
                self.move_list + [move], len(self.move_list))
        if pv:
            move = pv[0]
            ponder_move = pv[1] if len(pv) > 1 else None
            # Điểm hiển thị phải là điểm của nước được chọn, không phải dòng tốt nhất.
            chosen = next((info for info in self.pv_candidates.values()
                           if info['pv'] and info['pv'][0] == move), None)
            if chosen:
                self.update_eval(chosen['score'], chosen['depth'])
        self.apply_engine_move(move, False, ponder_move)

    def handle_engine_no_move(self):
        if self.search_cancelled or self.engine_stopping:
            self.on_cancelled_search_drained()
            return
        if not self.is_engine_thinking or self.active_search_source != 'engine':
            return
        if not self.update_game_status():
            self.set_status("Engine không tìm thấy nước đi", 'error')
        self.on_engine_finish(preserve_status=True)

    def update_eval(self, score, depth):
        """score là ('cp' | 'mate', giá trị) theo góc nhìn bên đang đi."""
        text = format_score(score, flip=(self.turn == 'b'))
        color = self.colors['danger'] if text.startswith('-') else self.colors['success']
        self.set_eval_label(text, color)
        self.set_eval_target(eval_fraction(score, flip=(self.turn == 'b')))
        short = search_limit_short(self.limit_var.get())
        self.lbl_depth.config(text=f"DEPTH {depth} • {short}")

    def apply_engine_move(self, move, is_from_book=False, ponder_move=None):
        if is_from_book:
            self.pending_book_job = None
            if not self.is_engine_thinking or self.active_search_source != 'book':
                return

        parsed = self.parse_move(move)
        if not parsed or not XiangqiRules.is_legal_move(
                self.board, parsed[0], parsed[1], self.turn):
            self.on_engine_finish(preserve_status=True)
            self.set_status(f"Engine/Book trả về nước sai ({move})", 'error')
            return

        prefix = "Book" if is_from_book else "Máy"
        self.active_search_source = 'animation'
        self.apply_move(
            parsed[0], parsed[1], prefix,
            lambda: self.after_engine_move(ponder_move)
        )

    def after_engine_move(self, ponder_move):
        self.on_engine_finish(preserve_status=True)
        if self.pending_opening_toast:
            self.show_toast(f"Khai cuộc: {self.pending_opening_toast}", '#0369A1')
            self.pending_opening_toast = None
        self.start_ponder(ponder_move)

    def update_opening_label(self):
        red = opening_name(self.move_list, 0)
        black = opening_name(self.move_list, 1)
        if not red:
            self.lbl_opening.config(text="Khai cuộc: chưa bắt đầu", fg=self.colors['muted'])
            return
        text = f"Khai cuộc:  Đỏ {red}"
        if black:
            text += f"   ·   Đen {black}"
        unusual = (not is_mainstream_opening(self.move_list[0], 'w')
                   or (len(self.move_list) > 1
                       and not is_mainstream_opening(self.move_list[1], 'b')))
        self.lbl_opening.config(text=text, fg='#7DD3FC' if unusual else self.colors['muted'])

    def add_history(self, ply, mover, move_text, actor):
        number = (ply + 1) // 2
        side_name = "Đỏ" if mover == 'w' else "Đen"
        self.listbox_moves.insert(
            tk.END, f"{number:>3}.  {side_name:<3}  {move_text}   · {actor}"
        )
        index = self.listbox_moves.size() - 1
        self.listbox_moves.itemconfig(
            index,
            fg='#FCA5A5' if mover == 'w' else '#E2E8F0',
            bg='#0F172A' if number % 2 else '#131C2E',
        )
        self.listbox_moves.yview(tk.END)
        self.update_move_count()

    def on_engine_finish(self, preserve_status=False):
        self.is_engine_thinking = False
        self.active_search_source = None
        self.pending_book_job = None
        self.set_go_button(text="⚙  MÁY ĐI", bg=self.colors['accent_dark'])
        if not preserve_status and not self.game_over:
            self.update_game_status()
        self.draw_board()

    def close_app(self):
        self.cancel_pending_action()
        self.engine_closing = True
        for job in (self.fx_job, self.resize_job, self.status_pulse_job):
            if job is not None:
                try:
                    self.root.after_cancel(job)
                except tk.TclError:
                    pass
        self.fx_job = self.resize_job = self.status_pulse_job = None
        self.status_tone = 'normal'
        if self.engine_process and self.engine_process.poll() is None:
            try:
                self.send_engine("quit")
                self.engine_process.wait(timeout=1)
            except (subprocess.TimeoutExpired, OSError):
                self.engine_process.terminate()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    gui = YagoLiteGUI(root)
    root.mainloop()
