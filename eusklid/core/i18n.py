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

import os
import re

try:
    import FreeCAD as App
except Exception:
    App = None

try:
    from ..qt_compat import QtCore
except Exception:
    QtCore = None


_TRANSLATIONS = None
_LANG = None


def _plugin_root():
    return os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _po_path(lang):
    return os.path.join(_plugin_root(), "resources", "i18n", "%s.po" % lang)


def _normalize_language(value):
    lang = (value or "").strip().lower()
    if not lang:
        return ""

    aliases = {
        "french": "fr",
        "français": "fr",
        "francais": "fr",
        "fr": "fr",
        "fr_fr": "fr",
        "fr-fr": "fr",
        "spanish": "es",
        "español": "es",
        "espanol": "es",
        "es": "es",
        "es_es": "es",
        "es-es": "es",
        "italian": "it",
        "italiano": "it",
        "it": "it",
        "it_it": "it",
        "it-it": "it",
        "english": "en",
        "en": "en",
        "en_us": "en",
        "en-us": "en",
        "en_gb": "en",
        "en-gb": "en",
        "system": "",
        "auto": "",
        "automatic": "",
        "default": "",
    }
    if lang in aliases:
        return aliases[lang]

    return lang.split("_")[0].split("-")[0]


def _freecad_language():
    if App is None:
        return ""

    try:
        pg = App.ParamGet("User parameter:BaseApp/Preferences/General")
    except Exception:
        return ""

    # FreeCAD versions/preferences have used several keys over time.
    for key in ("Language", "LanguageCode", "Locale", "UserLanguage"):
        try:
            val = pg.GetString(key, "")
            lang = _normalize_language(val)
            if lang:
                return lang
        except Exception:
            pass

    return ""


def _qt_language():
    if QtCore is None:
        return ""

    try:
        loc = QtCore.QLocale()
        lang = _normalize_language(loc.name())
        if lang:
            return lang
    except Exception:
        pass

    try:
        loc = QtCore.QLocale.system()
        lang = _normalize_language(loc.name())
        if lang:
            return lang
    except Exception:
        pass

    return ""


def _detect_language():
    # Priority:
    # 1. Explicit FreeCAD language preference, when it is not "system/auto".
    # 2. Qt current/system locale, which covers FreeCAD "automatic by OS".
    # 3. English fallback.
    return _freecad_language() or _qt_language() or "en"


def _unquote_po(s):
    """Decode only PO string escapes, preserving UTF-8 accents.

    The previous implementation used unicode_escape on UTF-8 bytes, which
    produced mojibake such as 'ParamÃ¨tres'. FreeCAD/Qt expects normal Python
    unicode strings here.
    """
    out = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == "n":
                out.append("\n")
            elif nxt == "t":
                out.append("\t")
            elif nxt == "r":
                out.append("\r")
            elif nxt == '"':
                out.append('"')
            elif nxt == "\\":
                out.append("\\")
            else:
                out.append(nxt)
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _load_po(lang):
    path = _po_path(lang)
    if not os.path.exists(path):
        return {}

    translations = {}
    msgid = None
    msgstr = None
    current = None

    def flush():
        nonlocal msgid, msgstr
        if msgid is not None and msgstr is not None and msgid:
            translations[msgid] = msgstr
        msgid = None
        msgstr = None

    rx = re.compile(r'^(msgid|msgstr)\s+"(.*)"\s*$')
    cx = re.compile(r'^"(.*)"\s*$')

    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            m = rx.match(line)
            if m:
                key, value = m.group(1), _unquote_po(m.group(2))
                if key == "msgid":
                    flush()
                    msgid = value
                    current = "msgid"
                else:
                    msgstr = value
                    current = "msgstr"
                continue
            m = cx.match(line)
            if m and current:
                value = _unquote_po(m.group(1))
                if current == "msgid" and msgid is not None:
                    msgid += value
                elif current == "msgstr" and msgstr is not None:
                    msgstr += value

    flush()
    return translations


def language():
    global _LANG
    if _LANG is None:
        _LANG = _detect_language()
    return _LANG


def reset():
    global _TRANSLATIONS, _LANG
    _TRANSLATIONS = None
    _LANG = None


def tr(text):
    global _TRANSLATIONS
    if _TRANSLATIONS is None:
        lang = language()
        _TRANSLATIONS = {} if lang == "en" else _load_po(lang)
    return _TRANSLATIONS.get(text, text)


def debug_info():
    """Small helper for manual diagnosis from the FreeCAD Python console."""
    return {
        "language": language(),
        "po_path": _po_path(language()),
        "po_exists": os.path.exists(_po_path(language())),
        "translation_count": len(_TRANSLATIONS or {}),
    }
