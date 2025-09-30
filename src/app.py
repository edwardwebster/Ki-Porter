r"""!\file app.py
\brief Cocoa front-end that routes KiCad library imports.

This module boots a small PyObjC application that presents KiCad symbol and
footprint libraries inside a table, lets the user pick a destination, and
invokes placeholder import hooks. The window is designed to be resizable and
keeps recent status messages visible for debugging purposes.
"""


import sexpdata

import os
import sys

import utils

from ui import *
from typing import Dict, List, Optional

VERSION = "0.0.1"

KICAD_APP_PATH = utils.find('/Applications', 'KiCad.app')
KICAD_PREFS_PATH = os.path.expanduser('~/Library/Preferences/kicad/9.0')

KICAD_SYMBOLS_PATH = KICAD_APP_PATH + '/Contents/SharedSupport/symbols'
KICAD_FOOTPRINTS_PATH = KICAD_APP_PATH + '/Contents/SharedSupport/footprints'
KICAD_3D_PATH = KICAD_APP_PATH + '/Contents/SharedSupport/3dmodels'

SYMBOL_LIBRARIES: List[Dict[str, str]] = []
FOOTPRINT_LIBRARIES: List[Dict[str, str]] = []
MODEL_LIBRARIES: List[Dict[str, str]] = []

sym_lib_table = os.path.join(KICAD_PREFS_PATH, 'sym-lib-table')
footprint_lib_table = os.path.join(KICAD_PREFS_PATH, 'fp-lib-table')


def _symbol_name(token: object) -> str:
    r"""! \brief Convert a parsed S-expression name token into plain text."""
    if isinstance(token, sexpdata.Symbol):
        return token.value()
    return str(token)


def _value_to_str(token: object) -> str:
    r"""! \brief Convert a parsed S-expression value token into plain text."""
    if isinstance(token, sexpdata.Symbol):
        return token.value()
    return str(token)


def parse_lib_table(path: str) -> List[Dict[str, str]]:
    r"""! \brief Parse a KiCad ``*.lib-table`` into dictionaries.

    \param path File system path to the table.
    \return List of dictionaries containing key/value metadata for each
        library entry.
    """
    if not os.path.exists(path):
        return []

    try:
        with open(path, 'r', encoding='utf-8') as handle:
            parsed = sexpdata.loads(handle.read())
    except Exception as exc:  # noqa: BLE001 - surface in console for now
        print(f'Unable to parse {path}: {exc}')
        return []

    libraries: List[Dict[str, str]] = []
    for node in parsed:
        if not isinstance(node, list) or not node:
            continue

        head = node[0]
        if isinstance(head, sexpdata.Symbol) and head.value() == 'lib':
            record: Dict[str, str] = {}
            for pair in node[1:]:
                if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                    continue
                key = _symbol_name(pair[0])
                record[key] = _value_to_str(pair[1])
            if record:
                libraries.append(record)

    return libraries


def load_library_tables() -> None:
    """! \brief Refresh cached KiCad library definitions from disk."""
    global SYMBOL_LIBRARIES, FOOTPRINT_LIBRARIES
    SYMBOL_LIBRARIES = parse_lib_table(sym_lib_table)
    FOOTPRINT_LIBRARIES = parse_lib_table(footprint_lib_table)

def import_to_kicad(path: str, target_library: Dict[str, str]):
    r"""! \brief Placeholder import routine that reports the destination.

    \param path Source file supplied by the user.
    \param target_library Metadata describing the chosen KiCad library.
    """
    library_name = target_library.get('name', 'unknown')
    print(f"Selected library '{library_name}' for {os.path.basename(path)}")

    if path.endswith('.kicad_sym'):
        # dest = os.path.join(KICAD_PREFS_PATH, 'symbols', os.path.basename(file))
        # os.makedirs(os.path.dirname(dest), exist_ok=True)
        # os.rename(file, dest)
        # print(f'Imported symbol to {dest}')
        print(
            f"Import symbol {path} into {library_name} - feature not yet implemented"
        )
        os.system(
            f"say 'Import symbol {os.path.basename(path)} into {library_name}'"
        )
    elif path.endswith('.kicad_mod'):
        # dest = os.path.join(KICAD_PREFS_PATH, 'footprints', os.path.basename(file))
        # os.makedirs(os.path.dirname(dest), exist_ok=True)
        # os.rename(file, dest)
        # print(f'Imported footprint to {dest}')
        print(
            f"Import footprint {path} into {library_name} - feature not yet implemented"
        )
        os.system(
            f"say 'Import footprint {os.path.basename(path)} into {library_name}'"
        )
    elif path.endswith('.step') or path.endswith('.wrl'):
        # dest = os.path.join(KICAD_PREFS_PATH, '3dmodels', os.path.basename(file))
        # os.makedirs(os.path.dirname(dest), exist_ok=True)
        # os.rename(file, dest)
        # print(f'Imported 3D model to {dest}')
        print(
            f"Import 3D model {path} into {library_name} - feature not yet implemented"
        )
        os.system(
            f"say 'Import 3D model {os.path.basename(path)} into {library_name}'"
        )
    else:
        print('Unsupported file type')


if __name__ == '__main__':
    
    app = NSApplication.sharedApplication()
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)

    mask = (
        NSTitledWindowMask
        | NSClosableWindowMask
        | NSMiniaturizableWindowMask
        | NSResizableWindowMask
    )
    win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(500, 500, 600, 420), mask, 2, False
    )
    win.setTitle_(f"Ki-Porter v{VERSION}")
    win.setContentMinSize_((600, 420))

    library_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(20, 140, 380, 90))
    library_scroll.setHasVerticalScroller_(True)
    library_scroll.setHasHorizontalScroller_(True)
    library_scroll.setDrawsBackground_(False)
    library_scroll.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)

    library_table = NSTableView.alloc().initWithFrame_(NSMakeRect(0, 0, 380, 90))
    library_table.setAllowsMultipleSelection_(False)
    library_table.setUsesAlternatingRowBackgroundColors_(True)
    library_table.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)

    columns = [
        ('name', 'Name', 120.0),
        ('type', 'Type', 80.0),
        ('uri', 'URI', 180.0),
    ]
    for identifier, title, width in columns:
        column = NSTableColumn.alloc().initWithIdentifier_(identifier)
        column.setWidth_(width)
        column.setEditable_(False)
        header = column.headerCell()
        header.setStringValue_(title)
        library_table.addTableColumn_(column)

    library_table.setDelegate_(delegate)
    library_table.setDataSource_(delegate)
    library_table.reloadData()

    library_scroll.setDocumentView_(library_table)
    win.contentView().addSubview_(library_scroll)

    import_button = NSButton.alloc().initWithFrame_(NSMakeRect(300, 110, 100, 26))
    import_button.setTitle_('Import')
    import_button.setTarget_(delegate)
    import_button.setAction_('handleImportButton:')
    import_button.setEnabled_(False)
    import_button.setAutoresizingMask_(NSViewMinXMargin | NSViewMinYMargin)
    win.contentView().addSubview_(import_button)

    status_field = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 20, 380, 80))
    status_field.setEditable_(False)
    status_field.setBezeled_(False)
    status_field.setDrawsBackground_(False)
    status_field.setUsesSingleLineMode_(False)
    status_field.setLineBreakMode_(NSLineBreakByWordWrapping)
    status_field.setSelectable_(True)
    status_field.cell().setWraps_(True)
    status_field.cell().setScrollable_(True)
    status_field.setStringValue_('Waiting for file...')
    status_field.setAutoresizingMask_(NSViewWidthSizable | NSViewMaxYMargin)
    win.contentView().addSubview_(status_field)

    delegate.setStatusField_(status_field)
    delegate.setLibraryTable_(library_table)
    delegate.setImportButton_(import_button)
    win.makeKeyAndOrderFront_(None)

    # bring to front when launched by double-click
    NSRunningApplication.currentApplication().activateWithOptions_(NSApplicationActivateIgnoringOtherApps)

    app.run()
    sys.exit(0)
