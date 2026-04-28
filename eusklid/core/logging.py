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

import FreeCAD as App

from .config import get_config
from .i18n import tr


def console_messages_enabled():
    try:
        return bool(get_config().get("feeling", {}).get("console_messages", False))
    except Exception:
        return False


def help_messages_enabled():
    try:
        return bool(get_config().get("feeling", {}).get("help_messages", False))
    except Exception:
        return False


def info(message):
    if not console_messages_enabled():
        return
    try:
        App.Console.PrintMessage("euSKlid: %s\n" % str(message))
    except Exception:
        pass


def warn(message):
    if not console_messages_enabled():
        return
    try:
        App.Console.PrintWarning("euSKlid: %s\n" % str(message))
    except Exception:
        pass


def error(message):
    try:
        App.Console.PrintError("euSKlid: %s\n" % str(message))
    except Exception:
        pass


def help(message):
    if not help_messages_enabled():
        return
    try:
        App.Console.PrintMessage("euSKlid help: %s\n" % tr(str(message)))
    except Exception:
        pass


def invalid_selection(message="You can't touch this !"):
    if not help_messages_enabled():
        return
    try:
        App.Console.PrintWarning("euSKlid help: %s\n" % tr(str(message)))
    except Exception:
        pass
