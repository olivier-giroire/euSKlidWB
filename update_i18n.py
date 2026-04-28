#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: LGPL-2.1-or-later
#
# euSKlidWB - FreeCAD Workbench
# Copyright (C) 2026 Olivier Giroire
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.

"""
euSKlidWB i18n synchronizer.

Usage:
    python3 update_i18n.py

Expected layout:
    euSKlidWB/
      update_i18n.py
      resources/i18n/fr.po
      resources/i18n/es.po
      resources/i18n/it.po
      resources/i18n/de.po

What it does:
    - scans Python files for translation strings
    - keeps only msgids that are still used
    - preserves existing msgstr translations
    - writes aligned fr/es/it/de .po files
    - does not auto-translate missing strings
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Dict, Iterable, List

ROOT = Path(__file__).resolve().parent
I18N_DIR = ROOT / "resources" / "i18n"

LANGS = ("fr", "es", "it", "de")

SCAN_DIRS = [
    ROOT / "InitGui.py",
    ROOT / "eusklid",
]

PO_HEADER_TEMPLATE = '''msgid ""
msgstr ""
"Language: {lang}\\n"
"Content-Type: text/plain; charset=UTF-8\\n"

'''


def iter_python_files() -> Iterable[Path]:
    for item in SCAN_DIRS:
        if item.is_file() and item.suffix == ".py":
            yield item
        elif item.is_dir():
            for path in item.rglob("*.py"):
                if "__pycache__" not in path.parts:
                    yield path


def is_translation_call(node: ast.Call) -> bool:
    func = node.func

    if isinstance(func, ast.Name) and func.id in {"_", "tr"}:
        return True

    if isinstance(func, ast.Name) and func.id == "translate":
        return True

    if isinstance(func, ast.Attribute) and func.attr in {"translate", "tr"}:
        return True

    return False


def extract_msgid_from_call(node: ast.Call) -> str | None:
    if not is_translation_call(node):
        return None

    args = node.args
    if not args:
        return None

    # _("Text") / tr("Text")
    if isinstance(node.func, ast.Name) and node.func.id in {"_", "tr"}:
        candidate = args[0]
        if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str):
            return candidate.value
        return None

    # translate("Context", "Text")
    if len(args) >= 2:
        candidate = args[1]
        if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str):
            return candidate.value

    return None


def extract_msgids() -> List[str]:
    seen = set()
    msgids: List[str] = []

    for path in iter_python_files():
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except Exception as exc:
            print(f"WARNING: cannot parse {path}: {exc}")
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                msgid = extract_msgid_from_call(node)
                if msgid and msgid not in seen:
                    seen.add(msgid)
                    msgids.append(msgid)

    return msgids


_PO_ENTRY_RE = re.compile(
    r'msgid\s+"((?:[^"\\]|\\.)*)"\s*\nmsgstr\s+"((?:[^"\\]|\\.)*)"',
    re.S,
)


def po_unescape(value: str) -> str:
    return bytes(value, "utf-8").decode("unicode_escape")


def po_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )


def read_po(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}

    text = path.read_text(encoding="utf-8")
    entries: Dict[str, str] = {}

    for msgid_raw, msgstr_raw in _PO_ENTRY_RE.findall(text):
        msgid = po_unescape(msgid_raw)
        msgstr = po_unescape(msgstr_raw)
        if msgid:
            entries[msgid] = msgstr

    return entries


def write_po(path: Path, lang: str, msgids: List[str], translations: Dict[str, str]) -> None:
    lines = [PO_HEADER_TEMPLATE.format(lang=lang).rstrip(), ""]

    for msgid in msgids:
        msgstr = translations.get(msgid, "")
        lines.append(f'msgid "{po_escape(msgid)}"')
        lines.append(f'msgstr "{po_escape(msgstr)}"')
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    I18N_DIR.mkdir(parents=True, exist_ok=True)

    msgids = extract_msgids()

    if not msgids:
        print("ERROR: no translation strings found.")
        return 1

    print(f"Found {len(msgids)} active msgid(s).")

    for lang in LANGS:
        path = I18N_DIR / f"{lang}.po"
        old = read_po(path)
        old_count = len(old)

        write_po(path, lang, msgids, old)

        missing = sum(1 for msgid in msgids if not old.get(msgid))
        removed = max(0, old_count - sum(1 for msgid in msgids if msgid in old))

        print(
            f"{path.relative_to(ROOT)}: "
            f"{len(msgids)} msgid(s), "
            f"{missing} missing translation(s), "
            f"{removed} removed obsolete entry/entries"
        )

    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
