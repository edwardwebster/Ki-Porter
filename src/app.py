r"""!\file app.py
\brief Cocoa front-end that routes KiCad library imports.

This module boots a small PyObjC application that presents KiCad symbol and
footprint libraries inside a table, lets the user pick a destination, and
invokes placeholder import hooks. The window is designed to be resizable and
keeps recent status messages visible for debugging purposes.
"""


import os
import sys
import shutil
from typing import Any, Dict, List, Optional, Tuple

from urllib.parse import urlparse, unquote

import sexpdata

from Cocoa import (
    NSApplication,
    NSApplicationActivateIgnoringOtherApps,
    NSRunningApplication,
)

import utils
from ui import AppDelegate, UiContext

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
    # Placeholder for potential 3D model imports.
    # MODEL_LIBRARIES remains an empty list until a catalog is defined.


def get_libraries_for_type(library_type: str) -> List[Dict[str, str]]:
    """! \brief Return cached libraries matching the requested type."""
    if library_type == 'symbol':
        return SYMBOL_LIBRARIES
    if library_type == 'footprint':
        return FOOTPRINT_LIBRARIES
    if library_type == 'model':
        return MODEL_LIBRARIES
    return []


def resolve_library_uri(uri: str) -> str:
    """! \brief Expand KiCad URI tokens into an absolute filesystem path."""

    if not uri:
        raise ValueError('Target library is missing a URI entry.')

    resolved = uri
    replacements = {
        '${KICAD9_SYMBOL_DIR}': KICAD_SYMBOLS_PATH,
        '${KICAD9_FOOTPRINT_DIR}': KICAD_FOOTPRINTS_PATH,
        '${KICAD9_3DMODEL_DIR}': KICAD_3D_PATH,
    }

    for token, real_path in replacements.items():
        if real_path and token in resolved:
            resolved = resolved.replace(token, real_path)

    if resolved.startswith('file://'):
        parsed = urlparse(resolved)
        path = unquote(parsed.path or '')
        if parsed.netloc and not path:
            path = f'/{parsed.netloc}'
        elif parsed.netloc:
            path = f'/{parsed.netloc}{path}'
        resolved = path

    resolved = os.path.expandvars(os.path.expanduser(resolved))
    if not os.path.isabs(resolved):
        resolved = os.path.abspath(resolved)

    return resolved


def _ensure_not_system_symbol(source_path: str) -> None:
    """! \brief Guard against importing from KiCad's bundled symbol directory."""

    if not KICAD_SYMBOLS_PATH:
        return

    root = os.path.abspath(KICAD_SYMBOLS_PATH)
    candidate = os.path.abspath(source_path)

    try:
        common = os.path.commonpath([candidate, root])
    except ValueError:
        # Paths on different drives (Windows). Safe to proceed.
        return

    if common == root:
        raise AssertionError(
            'Refusing to import from KiCad\'s built-in symbols directory.'
        )


def _load_symbol_library(path: str) -> List[Any]:
    """! \brief Parse a KiCad symbol library from disk into S-expression form."""

    with open(path, 'r', encoding='utf-8') as handle:
        return sexpdata.loads(handle.read())


def _split_symbol_library(ast: List[Any]) -> Tuple[List[Any], List[Any], List[List[Any]]]:
    """! \brief Separate header/metadata/symbols from a symbol library AST."""

    if (
        not isinstance(ast, list)
        or not ast
        or not isinstance(ast[0], sexpdata.Symbol)
        or ast[0].value() != 'kicad_symbol_lib'
    ):
        raise ValueError('Invalid KiCad symbol library structure.')

    header = ast[0]
    metadata: List[Any] = []
    symbols: List[List[Any]] = []

    for node in ast[1:]:
        if (
            isinstance(node, list)
            and node
            and isinstance(node[0], sexpdata.Symbol)
            and node[0].value() == 'symbol'
        ):
            symbols.append(node)
        else:
            metadata.append(node)

    return header, metadata, symbols


def _symbol_entry_name(entry: List[Any]) -> str:
    """! \brief Extract the symbol name from a symbol S-expression."""

    if len(entry) < 2:
        raise ValueError('Symbol entry missing name field.')

    name_token = entry[1]
    if isinstance(name_token, sexpdata.Symbol):
        return name_token.value()
    return str(name_token)


def _merge_symbol_libraries(
    existing_ast: Optional[List[Any]],
    incoming_ast: List[Any],
) -> Tuple[List[Any], int, int]:
    """! \brief Merge symbol entries, returning the merged AST and stats."""

    header_in, meta_in, symbols_in = _split_symbol_library(incoming_ast)

    if existing_ast is None:
        header_out = header_in
        meta_out = list(meta_in)
        symbols_out: List[List[Any]] = []
    else:
        header_out, meta_out, symbols_out = _split_symbol_library(existing_ast)
        # Merge metadata by content to avoid duplicates.
        seen_meta = {sexpdata.dumps(item) for item in meta_out}
        for item in meta_in:
            key = sexpdata.dumps(item)
            if key not in seen_meta:
                meta_out.append(item)
                seen_meta.add(key)

    name_to_index = { _symbol_entry_name(entry): idx for idx, entry in enumerate(symbols_out) }

    added = 0
    updated = 0

    for symbol in symbols_in:
        name = _symbol_entry_name(symbol)
        if name in name_to_index:
            symbols_out[name_to_index[name]] = symbol
            updated += 1
        else:
            symbols_out.append(symbol)
            name_to_index[name] = len(symbols_out) - 1
            added += 1

    merged_ast: List[Any] = [header_out, *meta_out, *symbols_out]
    return merged_ast, added, updated


def _serialise_symbol_library(ast: List[Any]) -> str:
    """! \brief Convert a symbol library AST back to text."""

    text = sexpdata.dumps(ast)
    if not text.endswith('\n'):
        text += '\n'
    return text


def import_symbol_library(source_path: str, target_library: Dict[str, str]) -> str:
    """! \brief Merge the symbols from ``source_path`` into ``target_library``."""

    _ensure_not_system_symbol(source_path)

    dest_uri = target_library.get('uri', '')
    dest_path = resolve_library_uri(dest_uri)

    # If the URI points to a directory, drop the incoming file inside it.
    if os.path.isdir(dest_path):
        dest_path = os.path.join(dest_path, os.path.basename(source_path))

    source_abs = os.path.abspath(source_path)
    dest_abs = os.path.abspath(dest_path)

    if source_abs == dest_abs:
        raise AssertionError('Source and destination symbol libraries are identical.')

    os.makedirs(os.path.dirname(dest_abs), exist_ok=True)

    incoming_ast = _load_symbol_library(source_abs)
    existing_ast = _load_symbol_library(dest_abs) if os.path.exists(dest_abs) else None

    merged_ast, added, updated = _merge_symbol_libraries(existing_ast, incoming_ast)

    with open(dest_abs, 'w', encoding='utf-8') as handle:
        handle.write(_serialise_symbol_library(merged_ast))

    added_msg = f"added {added} new" if added else "added 0 new"
    updated_msg = f"updated {updated}" if updated else "updated 0"
    return (
        f"Merged symbols from {os.path.basename(source_path)} into "
        f"{target_library.get('name', 'unknown')} ({dest_abs}); {added_msg}, {updated_msg}"
    )

def import_to_kicad(path: str, target_library: Dict[str, str]) -> str:
    r"""! \brief Import a KiCad asset into the selected library."""

    extension = os.path.splitext(path)[1].lower()
    library_name = target_library.get('name', 'unknown')
    uri = target_library.get('uri', '')

    if extension == '.kicad_sym':
        message = import_symbol_library(path, target_library)
    elif extension == '.kicad_mod':
        destination = resolve_library_uri(uri)
        if os.path.isdir(destination):
            destination = os.path.join(destination, os.path.basename(path))
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copy(path, destination)
        message = f"Copied footprint {os.path.basename(path)} into {library_name}"
    elif extension in {'.step', '.wrl'}:
        destination = resolve_library_uri(uri)
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copy(path, destination)
        message = f"Copied 3D model {os.path.basename(path)} into {library_name}"
    else:
        message = 'Unsupported file type'

    print(message)
    return message


if __name__ == '__main__':
    load_library_tables()

    app = NSApplication.sharedApplication()

    context = UiContext(
        load_library_tables=load_library_tables,
        fetch_libraries=get_libraries_for_type,
        import_callback=import_to_kicad,
    )

    delegate = AppDelegate.alloc().initWithContext_(context)
    app.setDelegate_(delegate)

    # bring to front when launched by double-click
    NSRunningApplication.currentApplication().activateWithOptions_(
        NSApplicationActivateIgnoringOtherApps
    )

    app.run()
    sys.exit(0)
    # TODO - Application should exit once complete
