"""ตัวสร้าง QR Code แบบ Python ล้วน (ไม่ต้องติดตั้งไลบรารีเพิ่ม)
รองรับโหมด byte, ระดับแก้ไขข้อผิดพลาด M, เวอร์ชัน 1-10 (พอสำหรับ PromptPay)
ใช้: svg = qr_svg("ข้อความ")
"""

_ECC_M = {
    1: (10, 1), 2: (16, 1), 3: (26, 1), 4: (18, 2), 5: (24, 2),
    6: (16, 4), 7: (18, 4), 8: (22, 4), 9: (22, 5), 10: (26, 5),
}
_TOTAL_CW = {1: 26, 2: 44, 3: 70, 4: 100, 5: 134, 6: 172, 7: 196, 8: 242, 9: 292, 10: 346}
_ALIGN = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34],
          7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50]}


# ---------- Reed-Solomon บน GF(256) ----------
def _gf_mul(x, y):
    z = 0
    for i in range(7, -1, -1):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree):
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_mul(root, 2)
    return result


def _rs_remainder(data, divisor):
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, c in enumerate(divisor):
            result[i] ^= _gf_mul(c, factor)
    return result


# ---------- สร้าง codewords ----------
def _data_capacity(ver):
    ecc, blocks = _ECC_M[ver]
    return _TOTAL_CW[ver] - ecc * blocks


def _encode_data(data, ver):
    bits = []

    def put(val, n):
        bits.extend((val >> i) & 1 for i in range(n - 1, -1, -1))

    put(0b0100, 4)
    put(len(data), 8 if ver < 10 else 16)
    for b in data:
        put(b, 8)
    cap_bits = _data_capacity(ver) * 8
    bits.extend([0] * min(4, cap_bits - len(bits)))
    bits.extend([0] * (-len(bits) % 8))
    pad = 0xEC
    while len(bits) < cap_bits:
        put(pad, 8)
        pad ^= 0xEC ^ 0x11
    return [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]


def _add_ecc_and_interleave(data_cw, ver):
    ecc_len, nblocks = _ECC_M[ver]
    total = _TOTAL_CW[ver]
    nshort = nblocks - total % nblocks
    short_len = total // nblocks
    divisor = _rs_divisor(ecc_len)
    blocks, k = [], 0
    for i in range(nblocks):
        n = short_len - ecc_len + (0 if i < nshort else 1)
        dat = data_cw[k:k + n]
        k += n
        blocks.append((dat, _rs_remainder(dat, divisor)))
    out = []
    for i in range(short_len - ecc_len + 1):
        for dat, _ in blocks:
            if i < len(dat):
                out.append(dat[i])
    for i in range(ecc_len):
        for _, ecc in blocks:
            out.append(ecc[i])
    return out


# ---------- วาดโมดูล ----------
def _mask_fn(m):
    return [
        lambda x, y: (x + y) % 2 == 0,
        lambda x, y: y % 2 == 0,
        lambda x, y: x % 3 == 0,
        lambda x, y: (x + y) % 3 == 0,
        lambda x, y: (x // 3 + y // 2) % 2 == 0,
        lambda x, y: x * y % 2 + x * y % 3 == 0,
        lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
        lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
    ][m]


def _format_bits(mask):
    data = (0b00 << 3) | mask
    rem = data
    for _ in range(10):
        rem = (rem << 1) ^ ((rem >> 9) * 0x537)
    return ((data << 10) | rem) ^ 0x5412


def _version_bits(ver):
    rem = ver
    for _ in range(12):
        rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
    return (ver << 12) | rem


def _build(ver, codewords, mask):
    size = ver * 4 + 17
    mod = [[False] * size for _ in range(size)]
    func = [[False] * size for _ in range(size)]

    def setf(x, y, dark):
        mod[y][x] = dark
        func[y][x] = True

    for i in range(size):
        setf(6, i, i % 2 == 0)
        setf(i, 6, i % 2 == 0)

    def finder(cx, cy):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < size and 0 <= y < size:
                    d = max(abs(dx), abs(dy))
                    setf(x, y, d not in (2, 4))

    finder(3, 3)
    finder(size - 4, 3)
    finder(3, size - 4)

    pos = _ALIGN[ver]
    for i, ax in enumerate(pos):
        for j, ay in enumerate(pos):
            if (i == 0 and j == 0) or (i == 0 and j == len(pos) - 1) or (i == len(pos) - 1 and j == 0):
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    setf(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)

    def draw_format(m):
        bits = _format_bits(m)
        for i in range(6):
            setf(8, i, (bits >> i) & 1)
        setf(8, 7, (bits >> 6) & 1)
        setf(8, 8, (bits >> 7) & 1)
        setf(7, 8, (bits >> 8) & 1)
        for i in range(9, 15):
            setf(14 - i, 8, (bits >> i) & 1)
        for i in range(8):
            setf(size - 1 - i, 8, (bits >> i) & 1)
        for i in range(8, 15):
            setf(8, size - 15 + i, (bits >> i) & 1)
        setf(8, size - 8, True)

    draw_format(0)
    if ver >= 7:
        vb = _version_bits(ver)
        for i in range(18):
            a, b = size - 11 + i % 3, i // 3
            setf(a, b, (vb >> i) & 1)
            setf(b, a, (vb >> i) & 1)

    bits = []
    for cw in codewords:
        bits.extend((cw >> i) & 1 for i in range(7, -1, -1))
    i = 0
    fn = _mask_fn(mask)
    for right in range(size - 1, 0, -2):
        if right == 6:
            right = 5
        for vert in range(size):
            for j in range(2):
                x = right - j
                upward = ((right + 1) & 2) == 0
                y = size - 1 - vert if upward else vert
                if not func[y][x] and i < len(bits):
                    mod[y][x] = bool(bits[i])
                    i += 1
                if not func[y][x]:
                    mod[y][x] ^= fn(x, y)
    draw_format(mask)
    return mod


def _penalty(mod):
    size = len(mod)
    score = 0
    for grid in (mod, [list(r) for r in zip(*mod)]):
        for row in grid:
            run, prev = 1, row[0]
            for c in row[1:]:
                if c == prev:
                    run += 1
                else:
                    if run >= 5:
                        score += run - 2
                    run, prev = 1, c
            if run >= 5:
                score += run - 2
    for y in range(size - 1):
        for x in range(size - 1):
            if mod[y][x] == mod[y][x + 1] == mod[y + 1][x] == mod[y + 1][x + 1]:
                score += 3
    dark = sum(map(sum, mod))
    score += (abs(dark * 20 - size * size * 10) // (size * size)) * 10
    return score


def make_matrix(text):
    data = text.encode("utf-8")
    for ver in range(1, 11):
        if len(data) + (2 if ver < 10 else 3) <= _data_capacity(ver):
            break
    else:
        raise ValueError("ข้อความยาวเกินไปสำหรับ QR")
    cw = _add_ecc_and_interleave(_encode_data(data, ver), ver)
    best = min((_build(ver, cw, m) for m in range(8)), key=_penalty)
    return best


def qr_svg(text, fg="#12324a", bg="#ffffff", border=4):
    """คืนค่า SVG (string) ของ QR; เรนเดอร์คมชัดทุกขนาด"""
    m = make_matrix(text)
    n = len(m)
    d = []
    for y, row in enumerate(m):
        x = 0
        while x < n:
            if row[x]:
                s = x
                while x < n and row[x]:
                    x += 1
                d.append(f"M{s + border} {y + border}h{x - s}v1h-{x - s}z")
            else:
                x += 1
    total = n + border * 2
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} {total}" '
            f'shape-rendering="crispEdges" role="img" aria-label="QR Code สำหรับชำระเงิน">'
            f'<rect width="{total}" height="{total}" fill="{bg}"/>'
            f'<path d="{"".join(d)}" fill="{fg}"/></svg>')
