"""Downloadable ZIP with ordered PNG cards, full text and a checksummed manifest."""
import hashlib
import json
from pathlib import Path
import zipfile

MAX_HEADER = 8 * 1024**2
MAX_PACKAGE = 300 * 1024**2


def build_package(result: dict, session_path: Path, created_at: float, *, demo: bool = False) -> Path:
    entries = []
    for card in result["cards"]:
        filename = card["file"]
        if Path(filename).name != filename or not filename.endswith(".png") or "\\" in filename:
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
    if len({c['file'] for c in entries}) != len(entries):
        raise ValueError("Duplicate card filenames")
    header = {"schema_version": 2, "session_id": result["session_id"], "created_at": created_at,
              "detected_language": result["detected_language"], "plain_text_answer": result["plain_text_answer"],
              "demo": demo, "cards": entries}
    encoded = json.dumps(header, ensure_ascii=False, indent=2).encode("utf-8")
    structured = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
    text = result["plain_text_answer"].encode("utf-8")
    if len(encoded) > MAX_HEADER or len(encoded) + len(structured) + len(text) + sum(c["byte_count"] for c in entries) > MAX_PACKAGE:
        raise ValueError("Result package exceeds download limit")
    destination = session_path / "result.zip"
    temporary = session_path / "result.zip.tmp"
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", encoded)
            archive.writestr("answer.txt", text)
            archive.writestr("result.json", structured)
            for entry in entries:
                archive.write(session_path / "cards" / entry["file"], entry["file"])
        if temporary.stat().st_size > MAX_PACKAGE:
            raise ValueError("Result package exceeds download limit")
        inspect_package(temporary)
        (session_path / "answer.txt").write_bytes(text)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def inspect_package(path: Path) -> dict:
    if path.stat().st_size > MAX_PACKAGE:
        raise ValueError("Package too large")
    try:
        with zipfile.ZipFile(path) as archive:
            if len(archive.namelist()) != len(set(archive.namelist())):
                raise ValueError("Duplicated ZIP member")
            if sum(i.file_size for i in archive.infolist()) > MAX_PACKAGE:
                raise ValueError("Uncompressed package too large")
            if archive.getinfo("manifest.json").file_size > MAX_HEADER:
                raise ValueError("Manifest too large")
            header = json.loads(archive.read("manifest.json"))
            if header["schema_version"] != 2 or not header["cards"]:
                raise ValueError("Unsupported or empty result package")
            if (not isinstance(header['plain_text_answer'], str) or not isinstance(header['demo'], bool)
                    or not isinstance(header['created_at'], (int, float))
                    or header['detected_language'] not in {'ru','en','kk'}):
                raise ValueError("Invalid manifest field types")
            from uuid import UUID
            UUID(header['session_id'])
            expected = ["manifest.json", "answer.txt", "result.json"]
            for index, card in enumerate(header["cards"], 1):
                name = card["file"]
                if card["index"] != index or Path(name).name != name or "\\" in name or not name.endswith(".png"):
                    raise ValueError("Invalid card sequence or filename")
                data = archive.read(name)
                if (type(card['index']) is not int or type(card['byte_count']) is not int
                        or type(card['width']) is not int or type(card['height']) is not int
                        or card['width'] <= 0 or card['height'] <= 0):
                    raise ValueError("Invalid card field types")
                from PIL import Image
                from io import BytesIO
                with Image.open(BytesIO(data)) as image:
                    if image.format != 'PNG' or image.size != (card['width'],card['height']):
                        raise ValueError("Card dimensions mismatch")
                    image.verify()
                if len(data) != card["byte_count"] or hashlib.sha256(data).hexdigest() != card["sha256"]:
                    raise ValueError("Card integrity mismatch")
                expected.append(name)
            if sorted(archive.namelist()) != sorted(expected):
                raise ValueError("Unexpected or duplicated ZIP member")
            if archive.read("answer.txt").decode("utf-8") != header["plain_text_answer"]:
                raise ValueError("Answer text mismatch")
            structured = json.loads(archive.read("result.json"))
            if structured["session_id"] != header["session_id"]:
                raise ValueError("Session mismatch")
            if (structured['plain_text_answer'] != header['plain_text_answer']
                    or structured['detected_language'] != header['detected_language']
                    or structured.get('demo',False) != header['demo']
                    or [(c['index'],c['file'],c['width'],c['height']) for c in structured['cards']]
                       != [(c['index'],c['file'],c['width'],c['height']) for c in header['cards']]):
                raise ValueError("Structured result mismatch")
            return header
    except (zipfile.BadZipFile, KeyError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid result ZIP integrity") from exc
