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
from typing import Any, Dict, List, Optional, Set, Tuple

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
    global SYMBOL_LIBRARIES, FOOTPRINT_LIBRARIES, MODEL_LIBRARIES
    SYMBOL_LIBRARIES = parse_lib_table(sym_lib_table)
    FOOTPRINT_LIBRARIES = parse_lib_table(footprint_lib_table)
    MODEL_LIBRARIES = discover_3d_libraries()


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
        '${KICAD9_3D_MODEL_DIR}': KICAD_3D_PATH,
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


def discover_3d_libraries() -> List[Dict[str, str]]:
    """! \brief Enumerate available 3D model libraries based on filesystem roots."""

    roots: List[str] = []
    if KICAD_3D_PATH:
        roots.append(KICAD_3D_PATH)

    kisys3d = os.environ.get('KISYS3DMOD')
    if kisys3d:
        roots.extend(kisys3d.split(os.pathsep))

    libraries: List[Dict[str, str]] = []
    seen: Set[str] = set()

    for root in roots:
        if not root:
            continue
        expanded = os.path.abspath(os.path.expandvars(os.path.expanduser(root)))
        if not os.path.isdir(expanded):
            continue

        try:
            entries = sorted(os.listdir(expanded))
        except OSError as exc:  # pragma: no cover - defensive
            print(f'Unable to enumerate 3D library root {expanded}: {exc}')
            continue

        for entry in entries:
            if not entry.endswith('.3dshapes'):
                continue

            uri = os.path.join(expanded, entry)
            key = os.path.abspath(uri)
            if key in seen:
                continue

            libraries.append(
                {
                    'name': entry[:-len('.3dshapes')],
                    'type': 'model',
                    'uri': uri,
                }
            )
            seen.add(key)

    return libraries


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


def _format_atom(node: Any) -> str:
    """! \brief Serialise an atom while preserving KiCad-friendly quoting."""

    return sexpdata.dumps(node)


def _format_sexp(node: Any, indent: int = 0) -> str:
    """! \brief Pretty-print an S-expression using two-space indentation."""

    indent_str = '  ' * indent

    if isinstance(node, list):
        if not node:
            return f'{indent_str}()'

        head = node[0]
        if isinstance(head, list):
            first_line = f'{indent_str}('
            body_items = [ _format_sexp(head, indent + 1) ]
        else:
            first_line = f'{indent_str}({_format_atom(head)}'
            body_items = []

        for child in node[1:]:
            body_items.append(_format_sexp(child, indent + 1))

        if not body_items:
            return f'{first_line})'

        body = '\n'.join(body_items)
        return f'{first_line}\n{body}\n{indent_str})'

    return f'{indent_str}{_format_atom(node)}'


def _merge_symbol_libraries(
    existing_ast: Optional[List[Any]],
    incoming_ast: List[Any],
) -> Tuple[List[Any], int]:
    """! \brief Merge symbol entries, returning the merged AST and count."""

    header_in, meta_in, symbols_in = _split_symbol_library(incoming_ast)

    if existing_ast is None:
        header_out = header_in
        meta_out = list(meta_in)
        symbols_out: List[List[Any]] = []
    else:
        header_existing, meta_existing, symbols_existing = _split_symbol_library(existing_ast)
        header_out = header_existing
        meta_out = list(meta_existing)
        symbols_out = list(symbols_existing)

    name_to_index = { _symbol_entry_name(entry): idx for idx, entry in enumerate(symbols_out) }

    added = 0

    for symbol in symbols_in:
        name = _symbol_entry_name(symbol)
        if name in name_to_index:
            raise AssertionError(
                f"Symbol '{name}' is already present in the target library."
            )
        symbols_out.append(symbol)
        name_to_index[name] = len(symbols_out) - 1
        added += 1

    merged_ast: List[Any] = [header_out, *meta_out, *symbols_out]
    return merged_ast, added


def _serialise_symbol_library(ast: List[Any]) -> str:
    """! \brief Convert a symbol library AST back to text."""

    formatted = _format_sexp(ast)
    if not formatted.endswith('\n'):
        formatted += '\n'
    return formatted


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

    _, _, incoming_symbols = _split_symbol_library(incoming_ast)
    incoming_names = {_symbol_entry_name(symbol) for symbol in incoming_symbols}

    if existing_ast is not None:
        _, _, existing_symbols = _split_symbol_library(existing_ast)
        existing_names = {_symbol_entry_name(symbol) for symbol in existing_symbols}
        duplicates = sorted(existing_names.intersection(incoming_names))
        if duplicates:
            raise AssertionError(
                'Symbols already present in target library: ' + ', '.join(duplicates)
            )

    merged_ast, added = _merge_symbol_libraries(existing_ast, incoming_ast)

    with open(dest_abs, 'w', encoding='utf-8') as handle:
        handle.write(_serialise_symbol_library(merged_ast))

    symbol_word = 'symbol' if added == 1 else 'symbols'
    return (
        f"Added {added} {symbol_word} from {os.path.basename(source_path)} into "
        f"{target_library.get('name', 'unknown')} ({dest_abs})"
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
        if os.path.exists(destination):
            raise AssertionError(
                f"Footprint '{os.path.basename(path)}' already exists in {library_name}."
            )
        if os.path.abspath(path) == os.path.abspath(destination):
            raise AssertionError('Source and destination footprint files are identical.')
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copy(path, destination)
        message = f"Copied footprint {os.path.basename(path)} into {library_name}"
    elif extension in {'.step', '.wrl'}:
        destination_root = resolve_library_uri(uri)

        if destination_root.lower().endswith('.3dshapes'):
            model_dir = destination_root
        elif os.path.isdir(destination_root):
            model_dir = os.path.join(destination_root, f"{library_name}.3dshapes")
        else:
            # Treat URI as a file path; place models alongside in a .3dshapes folder.
            model_dir = os.path.join(os.path.dirname(destination_root), f"{library_name}.3dshapes")

        destination = os.path.join(model_dir, os.path.basename(path))

        if os.path.exists(destination):
            raise AssertionError(
                f"3D model '{os.path.basename(path)}' already exists in {library_name}."
            )
        if os.path.abspath(path) == os.path.abspath(destination):
            raise AssertionError('Source and destination 3D model files are identical.')
        os.makedirs(model_dir, exist_ok=True)
        shutil.copy(path, destination)
        message = (
            f"Copied 3D model {os.path.basename(path)} into {library_name}"
            f" ({model_dir})"
        )
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
