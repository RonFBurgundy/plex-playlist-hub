import math
import struct
import zlib

S, SS = 256, 4
W = S * SS

BG = (0x0f, 0x17, 0x2a)      # Slate 950/900 background
PLEX_AMBER = (0xe5, 0xa0, 0x0d) # Plex amber
SPOTIFY_GREEN = (0x1d, 0xb9, 0x54) # Spotify green
TEXT_WHITE = (0xf8, 0xfa, 0xfc)    # White accent
DEEZER_PURPLE = (0xa2, 0x59, 0xff) # Deezer/accent purple


def seg_d(px, py, a, b):
    ax, ay = a
    bx, by = b
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, by - ay
    L2 = vx * vx + vy * vy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, (wx * vx + wy * vy) / L2))
    return math.hypot(wx - t * vx, wy - t * vy)


def rrect(px, py, size, r):
    qx = abs(px - size / 2) - (size / 2 - r)
    qy = abs(py - size / 2) - (size / 2 - r)
    return math.hypot(max(qx, 0), max(qy, 0)) - r


def in_tri(p, a, b, c):
    def sg(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])

    d1, d2, d3 = sg(p, a, b), sg(p, b, c), sg(p, c, a)
    return not (((d1 < 0) or (d2 < 0) or (d3 < 0)) and ((d1 > 0) or (d2 > 0) or (d3 > 0)))


def render(path, segs=(), dots=(), tris=()):
    rows = []
    for y in range(W):
        row = bytearray()
        py = (y + 0.5) / SS
        for x in range(W):
            px = (x + 0.5) / SS
            if rrect(px, py, S, 52) > 0:
                row += bytes((0, 0, 0, 0))
                continue
            col = BG
            # Render elements in layer order
            for c, a, b, w in segs:
                if seg_d(px, py, a, b) <= w:
                    col = c
            for c, ctr, r in dots:
                if math.hypot(px - ctr[0], py - ctr[1]) <= r:
                    col = c
            for c, t in tris:
                if in_tri((px, py), *t):
                    col = c
            row += bytes(col + (255,))
        rows.append(row)

    out = bytearray()
    for y in range(S):
        out.append(0)
        for x in range(S):
            acc = [0, 0, 0, 0]
            for dy in range(SS):
                r = rows[y * SS + dy]
                for dx in range(SS):
                    i = (x * SS + dx) * 4
                    for k in range(4):
                        acc[k] += r[i + k]
            out += bytes(v // (SS * SS) for v in acc)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", S, S, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(out), 9))
        + chunk(b"IEND", b"")
    )
    with open(path, "wb") as f:
        f.write(png_bytes)
    print("Wrote", path)


def generate_plex_playlist_hub_icon():
    # Design:
    # 1. Three playlist bars on the left in Plex Amber (with rounded pill ends via segs)
    # 2. A circular badge on bottom right with Spotify green & Deezer purple sync dots / music note
    # 3. Plex amber chevron/play shape

    segs = [
        # Playlist Bar 1 (Plex Amber)
        (PLEX_AMBER, (60, 68), (145, 68), 12),
        # Playlist Bar 2 (Plex Amber)
        (PLEX_AMBER, (60, 108), (175, 108), 12),
        # Playlist Bar 3 (Plex Amber)
        (PLEX_AMBER, (60, 148), (130, 148), 12),
        # Sync flow arc from Playlist to Badge
        (SPOTIFY_GREEN, (60, 188), (115, 188), 12),

        # Musical beamed note stem 1
        (TEXT_WHITE, (168, 198), (168, 140), 5),
        # Musical note stem 2
        (TEXT_WHITE, (200, 190), (200, 130), 5),
        # Note beam
        (TEXT_WHITE, (168, 140), (200, 130), 7),
    ]

    dots = [
        # Note head 1
        (TEXT_WHITE, (158, 202), 14),
        # Note head 2
        (TEXT_WHITE, (190, 194), 14),
        # Service accent dots
        (SPOTIFY_GREEN, (196, 68), 12),
        (DEEZER_PURPLE, (196, 100), 8),
    ]

    # Plex arrow/play triangle accent
    play_triangle = (
        (PLEX_AMBER, ((178, 60), (178, 76), (190, 68)))
    )

    render("unraid/plex-playlist-hub.png", segs=segs, dots=dots)


if __name__ == "__main__":
    generate_plex_playlist_hub_icon()
