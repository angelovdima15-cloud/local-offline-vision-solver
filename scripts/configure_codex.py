"""Back up and customize user Codex settings; install this project's scoped skills."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import tomllib
import uuid

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "tools" / "codex"
SETTINGS = {
    "": {
        "model": "gpt-6.1-sol",
        "model_reasoning_effort": "medium",
        "service_tier": "default",
        "tool_output_token_limit": 6000,
    },
    "agents": {
        "max_concurrent_threads_per_session": 2,
        "default_subagent_model": "gpt-6-luna",
        "default_subagent_reasoning_effort": "high",
    },
}


def patch_settings(text: str) -> str:
    original = tomllib.loads(text)
    lines = text.splitlines()
    for section, values in SETTINGS.items():
        for key, value in values.items():
            headers = [i for i, line in enumerate(lines) if re.match(r"^\s*\[", line)]
            if section:
                matches = [i for i in headers if re.fullmatch(r"\s*\[" + re.escape(section) + r"\]\s*(?:#.*)?", lines[i])]
                if not matches:
                    lines.extend(["", f"[{section}]"])
                    start = len(lines)
                    end = len(lines)
                else:
                    start = matches[0] + 1
                    end = next((i for i in headers if i >= start), len(lines))
            else:
                start, end = 0, (headers[0] if headers else len(lines))
            existing = [i for i in range(start, end) if re.match(r"^\s*" + re.escape(key) + r"\s*=", lines[i])]
            rendered = f"{key} = {json.dumps(value)}"
            if len(existing) > 1:
                raise ValueError(f"Duplicate setting: {section}.{key}")
            if existing:
                lines[existing[0]] = rendered
            else:
                lines.insert(end, rendered)
    result = "\n".join(lines) + "\n"
    revised = tomllib.loads(result)
    for section, values in SETTINGS.items():
        actual = revised[section] if section else revised
        for key, value in values.items():
            if actual.get(key) != value:
                raise ValueError(f"Setting was not applied: {section}.{key}")

    def unchanged(data: dict) -> dict:
        data = deepcopy(data)
        for section, values in SETTINGS.items():
            table = data.get(section, {}) if section else data
            for key in values:
                table.pop(key, None)
            if section and not table:
                data.pop(section, None)
        return data

    if unchanged(original) != unchanged(revised):
        raise ValueError("Refusing to alter unrelated Codex settings")
    return result


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as file:
            file.write(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write settings; default is a dry run")
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))))
    args = parser.parse_args()
    config_home = args.codex_home.resolve()
    config_path = config_home / "config.toml"
    original = config_path.read_text(encoding="utf-8-sig") if config_path.exists() else ""
    writes = {config_path: patch_settings(original)}
    for template in sorted(TEMPLATES.glob("*.config.toml")):
        content = template.read_text(encoding="utf-8")
        tomllib.loads(content)
        writes[config_home / template.name] = content
    instructions = config_home / "AGENTS.md"
    old_instructions = instructions.read_text(encoding="utf-8-sig") if instructions.exists() else ""
    block = (TEMPLATES / "global-instructions.md").read_text(encoding="utf-8").strip()
    pattern = r"<!-- codex-efficiency:start -->.*?<!-- codex-efficiency:end -->"
    if "<!-- codex-efficiency:start -->" in old_instructions:
        if not re.search(pattern, old_instructions, flags=re.DOTALL):
            raise ValueError("Existing efficiency instructions have incomplete markers")
        merged = re.sub(pattern, lambda _: block, old_instructions, flags=re.DOTALL)
    else:
        merged = old_instructions.rstrip() + ("\n\n" if old_instructions.strip() else "") + block
    writes[instructions] = merged.rstrip() + "\n"
    for skill in sorted((TEMPLATES / "skills").glob("*/SKILL.md")):
        writes[ROOT / ".agents" / "skills" / skill.parent.name / "SKILL.md"] = skill.read_text(encoding="utf-8")

    changed = {path: content for path, content in writes.items() if not path.exists() or path.read_text(encoding="utf-8-sig") != content}
    summary = {"applied": args.apply, "settings": SETTINGS, "changed_files": [str(p) for p in changed]}
    if args.apply and changed:
        backup_dir = config_home / "backups" / ("efficiency-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6])
        backup_dir.mkdir(parents=True)
        manifest = []
        for index, path in enumerate(changed):
            backup = backup_dir / f"{index:02d}-{path.name}"
            existed = path.exists()
            if existed:
                shutil.copy2(path, backup)
            manifest.append({"destination": str(path), "existed": existed, "backup": str(backup) if existed else None})
        atomic_write(backup_dir / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        for path, content in changed.items():
            atomic_write(path, content)
        summary["backup_directory"] = str(backup_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
