from pathlib import Path
import hashlib
import json
import struct

ROOT = Path(__file__).resolve().parents[1]

if __name__ == "__main__":
    card = ROOT / "examples" / "rendered_math_checked" / "answer_01.png"
    # Reuse raster bytes solely to test framing; fixture metadata is explicitly DEMO.
    data = card.read_bytes()
    header = {"schema_version": 1, "session_id": "11111111-1111-4111-8111-111111111111",
              "created_at": 1791244800.0, "detected_language": "en", "plain_text_answer": "TRANSPORT DEMO fixture",
              "demo": True, "cards": [{"index": 1, "file": "answer_01.png", "byte_count": len(data),
                                      "sha256": hashlib.sha256(data).hexdigest(), "width": 832, "height": 992}]}
    encoded = json.dumps(header, separators=(",", ":")).encode()
    directory = ROOT / "apple" / "Tests" / "Fixtures"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "transport.lvsp").write_bytes(b"LVSPKG01" + struct.pack(">I", len(encoded)) + encoded + data)

