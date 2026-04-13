"""One-time script to generate green square placeholder icons for the extension.
Delete this file after running.
"""
import struct
import zlib
from pathlib import Path

def make_png(size):
    """Return minimal valid PNG bytes for a solid green square."""
    def chunk(name, data):
        c = struct.pack('>I', len(data)) + name + data
        return c + struct.pack('>I', zlib.crc32(c[4:]) & 0xffffffff)

    raw = (b'\x00' + bytes([0x22, 0xc5, 0x5e] * size)) * size  # green #22c55e; one filter byte per row
    compressed = zlib.compress(raw)
    ihdr = struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0)
    return (
        b'\x89PNG\r\n\x1a\n'
        + chunk(b'IHDR', ihdr)
        + chunk(b'IDAT', compressed)
        + chunk(b'IEND', b'')
    )

out = Path('extension/icons')
out.mkdir(parents=True, exist_ok=True)
for size in [16, 48, 128]:
    (out / f'icon{size}.png').write_bytes(make_png(size))
    print(f'Created icon{size}.png')
