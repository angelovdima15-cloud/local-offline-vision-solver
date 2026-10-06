"""One atomic WatchConnectivity file; no ZIP library needed on Apple devices."""
import hashlib
import json
from pathlib import Path
import struct

MAGIC = b"LVSPKG01"
MAX_HEADER = 8 * 1024**2
MAX_PACKAGE = 300 * 1024**2


def build_package(result: dict, session_path: Path, created_at: float, *, demo: bool = False) -> Path:
    entries = []
    for card in result["cards"]:
        filename = card["file"]
        if Path(filename).name != filename or not filename.endswith(".png"):
            raise ValueError("Unsafe card filename")
        path = session_path / "cards" / filename
        if not path.is_file():
            raise ValueError("Missing rendered card")
        data = path.read_bytes()
        entries.append({"index": card["index"], "file": filename, "byte_count": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "width": card["width"], "height": card["height"]})
    if not entries or [c["index"] for c in entries] != list(range(1, len(entries) + 1)):
        raise ValueError("Package must contain consecutive ordered cards")
    header = {"schema_version": 1, "session_id": result["session_id"], "created_at": created_at,
              "detected_language": result["detected_language"], "plain_text_answer": result["plain_text_answer"],
              "demo": demo, "cards": entries}
    encoded = json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_HEADER or len(encoded) + sum(c["byte_count"] for c in entries) + 12 > MAX_PACKAGE:
        raise ValueError("Watch result package exceeds transport limits")
    destination = session_path / "result.lvsp"
    temporary = destination.with_suffix(".lvsp.tmp")
    with temporary.open("wb") as output:
        output.write(MAGIC)
        output.write(struct.pack(">I", len(encoded)))
        output.write(encoded)
        for entry in entries:
            with (session_path / "cards" / entry["file"]).open("rb") as card:
                while chunk := card.read(1024**2):
                    output.write(chunk)
    temporary.replace(destination)
    return destination


def inspect_package(path: Path) -> dict:
    """Used by interoperability tests and offline inspection; validates every byte."""
    if path.stat().st_size > MAX_PACKAGE:
        raise ValueError("Package too large")
    with path.open("rb") as stream:
        if stream.read(8) != MAGIC:
            raise ValueError("Invalid package magic")
        length_bytes = stream.read(4)
        if len(length_bytes) != 4:
            raise ValueError("Truncated header")
        size = struct.unpack(">I", length_bytes)[0]
        if size > MAX_HEADER:
            raise ValueError("Header too large")
        header = json.loads(stream.read(size))
        if header["schema_version"] != 1 or not header["cards"]:
            raise ValueError("Unsupported or empty result package")
        for index, card in enumerate(header["cards"], 1):
            if card["index"] != index or Path(card["file"]).name != card["file"]:
                raise ValueError("Invalid card sequence or filename")
            count = card["byte_count"]
            if not isinstance(count, int) or count <= 0 or count > MAX_PACKAGE:
                raise ValueError("Invalid card length")
            data = stream.read(count)
            if len(data) != count or hashlib.sha256(data).hexdigest() != card["sha256"]:
                raise ValueError("Card integrity mismatch")
        if stream.read(1):
            raise ValueError("Trailing package bytes")
    return header

