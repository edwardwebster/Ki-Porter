"""UI module containing the Cocoa AppDelegate and window construction."""

import os
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

import objc

from Cocoa import (
    NSApplication,
    NSApplicationActivateIgnoringOtherApps,
    NSButton,
    NSMakeRect,
    NSRunningApplication,
    NSScrollView,
    NSTextField,
    NSTableColumn,
    NSTableView,
    NSTimer,
    NSWindow,
    NSObject,
)
from Cocoa import (
    NSClosableWindowMask,
    NSTitledWindowMask,
    NSMiniaturizableWindowMask,
    NSResizableWindowMask,
)
from Cocoa import (
    NSIndexSet,
    NSLineBreakByWordWrapping,
    NSViewHeightSizable,
    NSViewMaxYMargin,
    NSViewMinXMargin,
    NSViewMinYMargin,
    NSViewWidthSizable,
)


@dataclass
class UiContext:
    """Immutable bundle of callbacks used by the UI layer."""

    load_library_tables: Callable[[], None]
    fetch_libraries: Callable[[str], List[Dict[str, str]]]
    import_callback: Callable[[str, Dict[str, str]], Optional[str]]


class AppDelegate(NSObject):
    r"""! \brief Cocoa delegate that coordinates file handling and UI state."""

    def initWithContext_(self, context: UiContext):
        r"""! \brief Initialise the delegate with callbacks and UI handles."""
        self = objc.super(AppDelegate, self).init()
        if self is None:
            return None

        if context is None:
            raise ValueError('UiContext is required to initialise AppDelegate')

        self._context = context
        self._has_finished_launching = False
        self._queued_paths: List[str] = []
        self._status_field = None
        self._status_history: List[str] = []
        self._library_table = None
        self._import_button = None
        self._window: Optional[NSWindow] = None
        self._pending_file: Optional[str] = None
        self._pending_libraries: List[Dict[str, str]] = []
        self._pending_library_type: Optional[str] = None

        self._build_ui()

        return self

    def applicationDidFinishLaunching_(self, notification):
        r"""! \brief Process any files queued before the app finished launching."""
        self._has_finished_launching = True
        self._schedule_process_queue()

    # This makes the app quit when the last window is closed (red X)
    def applicationShouldTerminateAfterLastWindowClosed_(self, app):
        r"""! \brief Request application termination when the window closes."""
        return True        

    def application_openFile_(self, app, filename):
        r"""! \brief Handle a single file open request from macOS Finder."""
        path = os.path.abspath(filename)
        if self._has_finished_launching:
            self._handle_open_file(path)
        else:
            self._queued_paths.append(path)
            self._update_status(f'Queued file until launch completes: {path}')
        return True

    def application_openFiles_(self, app, filenames):
        r"""! \brief Handle multiple file open requests in sequence."""
        for filename in filenames:
            self.application_openFile_(app, filename)

    def _handle_open_file(self, path: str) -> None:
        r"""! \brief Inspect the supplied file and populate UI selection state."""
        self._context.load_library_tables()
        self._update_status(f'Opened file: {path}')
        library_type = self._library_type_for_path(path)
        if library_type is None:
            print(f'Unsupported file type: {path}')
            self._update_status(f'Unsupported file: {path}')
            return

        libraries = self._libraries_for_type(library_type)

        self._update_status(
            f'Loaded {len(libraries)} {library_type} libraries for {path}'
        )

        if not libraries:
            self._update_status('No KiCad libraries found in preferences')
            self._clear_library_controls()
            return

        self._display_library_choices(path, library_type, libraries)

    def _library_type_for_path(self, path: str) -> Optional[str]:
        r"""! \brief Infer the KiCad library category from a file extension."""
        _, ext = os.path.splitext(path.lower())
        if ext == '.kicad_sym':
            return 'symbol'
        if ext == '.kicad_mod':
            return 'footprint'
        if ext in {'.step', '.wrl'}:
            return 'model'
        return None

    def _libraries_for_type(self, library_type: str) -> List[Dict[str, str]]:
        r"""! \brief Fetch the cached libraries that match the requested type."""
        libraries = self._context.fetch_libraries(library_type)
        return list(libraries) if libraries else []

    def _display_library_choices(
        self,
        file_path: str,
        library_type: str,
        libraries: List[Dict[str, str]],
    ) -> None:
        r"""! \brief Present the available libraries within the main table.

        \param file_path Resolved path of the file being imported.
        \param library_type Computed type of the file (symbol/footprint/model).
        \param libraries Collection of library records to display.
        """
        NSRunningApplication.currentApplication().activateWithOptions_(NSApplicationActivateIgnoringOtherApps)

        self._pending_file = file_path
        self._pending_libraries = list(libraries)
        self._pending_library_type = library_type

        table = getattr(self, '_library_table', None)
        if table is not None:
            table.reloadData()
            if libraries:
                index_set = NSIndexSet.indexSetWithIndex_(0)
                table.selectRowIndexes_byExtendingSelection_(index_set, False)
                table.scrollRowToVisible_(0)

        button = getattr(self, '_import_button', None)
        if button is not None:
            button.setEnabled_(bool(libraries))

        self._update_status(
            f"Select a {library_type} library and press Import for {os.path.basename(file_path)}"
        )

    def _clear_library_controls(self) -> None:
        """! \brief Reset the table selection and disable import actions."""
        self._pending_file = None
        self._pending_libraries = []
        self._pending_library_type = None

        table = getattr(self, '_library_table', None)
        if table is not None:
            table.deselectAll_(None)
            table.reloadData()

        button = getattr(self, '_import_button', None)
        if button is not None:
            button.setEnabled_(False)

    def setStatusField_(self, field):
        """! \brief Attach the status text field to the delegate."""
        self._status_field = field

    def setLibraryTable_(self, table_view):
        """! \brief Attach the NSTableView used to display libraries."""
        self._library_table = table_view

    def setImportButton_(self, button):
        """! \brief Attach the import button control to the delegate."""
        self._import_button = button

    def _update_status(self, message: str) -> None:
        """! \brief Append a status message and update the UI element."""
        field = getattr(self, '_status_field', None)
        self._status_history.append(message)
        # keep the last few messages to avoid unbounded growth
        self._status_history = self._status_history[-8:]
        combined = '\n'.join(self._status_history)
        if field is not None:
            field.setStringValue_(combined)
        else:
            print(message)

    def handleImportButton_(self, sender):
        """! \brief Trigger an import when the user clicks the button."""
        if not self._pending_file or not self._pending_libraries:
            self._update_status('No file ready to import')
            return

        table = getattr(self, '_library_table', None)
        selected_index = -1
        if table is not None:
            selected_index = table.selectedRow()

        if selected_index < 0 or selected_index >= len(self._pending_libraries):
            self._update_status('Select a target library before importing')
            return

        selection = self._pending_libraries[selected_index]
        import_message = self._context.import_callback(self._pending_file, selection)
        display_message = import_message or (
            f"Queued import for {self._pending_file} into {selection.get('name', 'unknown')}"
        )
        self._update_status(display_message)
        self._clear_library_controls()
        # self._schedule_termination()

    # NSTableView data source / delegate
    def numberOfRowsInTableView_(self, table_view):
        """! \brief Report the number of rows available to the table view."""
        return len(self._pending_libraries)

    def tableView_objectValueForTableColumn_row_(self, table_view, column, row_index):
        """! \brief Supply a column value for the requested table row."""
        if row_index < 0 or row_index >= len(self._pending_libraries):
            return ''
        identifier = column.identifier()
        key = str(identifier)
        return self._pending_libraries[row_index].get(key, '')

    def tableViewSelectionDidChange_(self, notification):
        """! \brief Update status text when the table selection changes."""
        table = getattr(self, '_library_table', None)
        if table is None:
            return
        row = table.selectedRow()
        if 0 <= row < len(self._pending_libraries):
            library = self._pending_libraries[row]
            self._update_status(
                f"Selected library '{library.get('name', 'unknown')}'"
            )

    def _schedule_termination(self) -> None:
        """! \brief Terminate the app after the status message is rendered."""
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.25, self, 'terminateApplication:', None, False
        )

    def terminateApplication_(self, timer):
        NSApplication.sharedApplication().terminate_(self)

    def _schedule_process_queue(self) -> None:
        """! \brief Schedule processing for any queued file-open requests."""
        if not self._queued_paths:
            return
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.0, self, 'processQueuedPaths:', None, False
        )

    def processQueuedPaths_(self, timer):
        """! \brief Drain the queued file-open requests sequentially."""
        while self._queued_paths:
            path = self._queued_paths.pop(0)
            self._handle_open_file(path)

    def _build_ui(self) -> None:
        """! \brief Construct the main window and all UI elements."""
        initial_width = 600
        initial_height = 420

        mask = (
            NSTitledWindowMask
            | NSClosableWindowMask
            | NSMiniaturizableWindowMask
            | NSResizableWindowMask
        )
        window_rect = NSMakeRect(500, 500, initial_width, initial_height)
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            window_rect, mask, 2, False
        )
        win.setTitle_('Ki-Porter')
        win.setContentMinSize_((420, 260))
        self._window = win

        content_view = win.contentView()

        library_scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(20, 140, initial_width - 40, initial_height - 180)
        )
        library_scroll.setHasVerticalScroller_(True)
        library_scroll.setHasHorizontalScroller_(False)
        library_scroll.setBorderType_(1)  # Bezel border
        library_scroll.setAutohidesScrollers_(True)
        library_scroll.setAutoresizingMask_(
            NSViewWidthSizable | NSViewHeightSizable | NSViewMinYMargin
        )

        table_view = NSTableView.alloc().initWithFrame_(NSMakeRect(0, 0, 380, 90))
        table_view.setAllowsMultipleSelection_(False)
        table_view.setAllowsEmptySelection_(False)
        table_view.setColumnAutoresizingStyle_(1)  # Uniform column widths
        table_view.setAutoresizesSubviews_(True)
        table_view.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        table_view.setAllowsColumnReordering_(False)
        table_view.setAllowsColumnResizing_(False)
        table_view.setAllowsTypeSelect_(True)

        columns = [
            ('name', 'Name', 160.0),
            ('type', 'Type', 80.0),
            ('descr', 'Description', 240.0),
        ]
        for identifier, title, width in columns:
            column = NSTableColumn.alloc().initWithIdentifier_(identifier)
            column.setWidth_(width)
            column.headerCell().setStringValue_(title)
            column.setEditable_(False)
            table_view.addTableColumn_(column)

        table_view.setDelegate_(self)
        table_view.setDataSource_(self)
        table_view.reloadData()
        self._library_table = table_view

        library_scroll.setDocumentView_(table_view)
        content_view.addSubview_(library_scroll)

        button_width = 120
        button_height = 32
        button_margin = 20
        import_button = NSButton.alloc().initWithFrame_(
            NSMakeRect(
                initial_width - button_margin - button_width,
                button_margin,
                button_width,
                button_height,
            )
        )
        import_button.setTitle_('Import')
        import_button.setTarget_(self)
        import_button.setAction_('handleImportButton:')
        import_button.setEnabled_(False)
        import_button.setAutoresizingMask_(NSViewMinXMargin | NSViewMaxYMargin)
        content_view.addSubview_(import_button)
        self._import_button = import_button

        status_field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(
                20,
                button_margin,
                initial_width - (button_width + (3 * 20)),
                80,
            )
        )
        status_field.setEditable_(False)
        status_field.setBezeled_(False)
        status_field.setDrawsBackground_(False)
        status_field.setUsesSingleLineMode_(False)
        status_field.setLineBreakMode_(NSLineBreakByWordWrapping)
        if hasattr(status_field, 'setMaximumNumberOfLines_'):
            status_field.setMaximumNumberOfLines_(0)
        status_field.setSelectable_(True)
        status_field.cell().setWraps_(True)
        status_field.cell().setScrollable_(False)
        status_field.setStringValue_('Waiting for file...')
        status_field.setAutoresizingMask_(NSViewWidthSizable | NSViewMaxYMargin)
        content_view.addSubview_(status_field)
        self._status_field = status_field

        win.makeKeyAndOrderFront_(None)
