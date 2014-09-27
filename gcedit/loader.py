"""gcedit disk image loader module.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

"""

import os
from html import escape

from .ext.gcutil import GCFS, DiskError, bnr_to_pnm

from . import conf, guiutil, qt

# TODO:
# [ENH] allow selecting multiple disks and removing them all at once
#   - change text in rm confirmation to indicate multiple
#   - open the first selected (warn if more than one)
# [ENH] set 'open', 'remove' button sensitivity according to disk selection
# [ENH] allow drag-and-drop of files onto the table (and out of, as files, into other programs?)
# [ENH] browse on table activate with no selection (table could be empty)

COL_NAME = 0
COL_ICON = 1
COL_SIZE = 2
COL_PATH = 3


def add_to_hist (fn_hist, *fns):
    """Add disk image filenames to the history.

add_to_hist(fn_hist, *fns)

fn_hist: current disk image history.
fns: filenames to add.

"""
    if any([conf.mru_add(fn_hist, os.path.abspath(fn))[0] for fn in fns]):
        conf.write_lines('disk_history', fn_hist)


def run_editor (fn, parent=None):
    """Start and display the editor.

run_editor(fn[, parent]) -> valid

fn: filename to load as a disk image.
parent: parent window for the error dialogue, if shown.

valid: whether the file was found to be valid (if not, an error dialogue is
       shown and the editor isn't started).

"""
    try:
        fs = GCFS(fn)
    except DiskError as e:
        guiutil.error(_('Invalid file: {}').format(e), parent)
        return False
    except IOError as e:
        e = e.strerror[0].lower() + e.strerror[1:]
        guiutil.error(_('Couldn\'t read the file: {}').format(e), parent)
        return False
    else:
        # start the editor (import here because editor imports this module)
        # TODO
        #from .editor import Editor
        #Editor(fs).show()
        return True


def browse (fn_hist, parent=None):
    """Browse for a disk image and open it in the editor.

browse(fn_hist[, parent]) -> opened

fn_hist: current disk image history.
parent: a window for the dialogue's parent.

opened: If True, one disk was chosen, added to the history and opened in the
        editor.  If False, no disks were chosen, or one disk was chosen and it
        was invalid.  If a list of filenames, each one was added to the
        history.

"""
    fns = qt.QFileDialog.getOpenFileNames(
        # NOTE: the title for a file open dialogue
        parent, _('Open Disk Image'), conf.settings['loader_path'], None, None,
        qt.QFileDialog.DontResolveSymlinks
    )[0]

    if fns:
        # remember dir
        conf.settings['loader_path'] = os.path.dirname(fns[0])
        # add to history
        add_to_hist(fn_hist, *fns)
        if len(fns) == 1:
            if run_editor(fns[0], parent):
                return True
            else:
                return False
        else:
            return fns
    else:
        return False


def update_model_item (item, data):
    if isinstance(data, str):
        item.setText(data)
    elif isinstance(data, qt.QIcon):
        item.setIcon(data)
    elif isinstance(data, qt.QPixmap):
        if data.isNull():
            item.setIcon(guiutil.invalid_icon())
        else:
            item.setData(data, qt.Qt.DecorationRole)


def disk_tooltip (fn, info):
    name = info['name']
    tooltip = '<b>{} ({}, {})</b>\n{}'
    tooltip = tooltip.format(*(escape(arg) for arg in (
        info['full name'], info['code'], info['full developer'], fn
    )))
    desc = ' '.join(info['description'].splitlines()).strip()
    if desc:
        tooltip += '\n\n' + desc


class LoadThreadSignals (qt.QObject):
    # corresponds to the table columns, then tooltip
    loaded = qt.pyqtSignal(str, qt.QPixmap, str, str, str)


class LoadThread (qt.QRunnable):
    def __init__ (self, fn):
        qt.QRunnable.__init__(self)
        self.fn = fn
        self.signals = LoadThreadSignals()

    def run (self):
        fn = self.fn
        try:
            fs = GCFS(fn)
            info = fs.get_info()
            info.update(fs.get_bnr_info())

        except (IOError, DiskError, ValueError):
            name = os.path.basename(fn)
            img = qt.QPixmap()
            tooltip = escape(fn)

        else:
            # load image into pixbuf
            name = info['name']
            img_pnm = bnr_to_pnm(info['img'])
            img = qt.QPixmap()
            if not img.loadFromData(img_pnm, b'PPM'):
                # loading failed
                img = qt.QPixmap()
            tooltip = disk_tooltip(fn, info)

        try:
            size = os.path.getsize(fn)
        except OSError as e:
            size = ''
        else:
            size = guiutil.printable_filesize(size)

        self.signals.loaded.emit(name, img, size, fn, tooltip)


class LoadDisk (guiutil.Window):
    """The window for choosing a disk image to load.

    CONSTRUCTOR

LoadDisk(fn_hist)

fn_hist: current disk image history.

"""

    def __init__ (self, fn_hist):
        self._fn_hist = fn_hist
        guiutil.Window.__init__(self, 'loader')
        self.setWindowTitle(conf.APPLICATION)

        menu = qt.QMenu()
        self._table = table = guiutil.DeselectableTableView(COL_NAME)

        window_actions = guiutil.mk_actions({
            'browse': {
                'icon': 'edit-find',
                'text': _('&Browse...'),
                'tooltip': _('Load a new disk from the filesystem'),
                'key': qt.QKeySequence.Open,
                'clicked': self._browse
            },
            'quit': {
                'icon': 'application-exit',
                'text': _('&Quit'),
                'tooltip': _('Quit the application'),
                'key': qt.QKeySequence.Quit,
                'clicked': self._quit
            }
        }, self)

        table_actions = guiutil.mk_actions({
            'open': {
                'icon': 'document-open',
                'text': _('&Open'),
                'tooltip': _('Open the selected disk for editing'),
                'clicked': self._open_current,
            },
            'remove': {
                'icon': 'list-remove',
                'text': _('&Remove'),
                'tooltip': _('Remove the selected disk from the known disks '
                             'list'),
                'key': qt.QKeySequence.Delete,
                'clicked': self._rm_current
            },
            'remove all': {
                'icon': 'list-remove',
                'text': _('Remove &All'),
                'tooltip': _('Remove all disks from the known disks list'),
                'clicked': self._rm_all
            }
        }, table)

        # layout
        g = qt.QGridLayout()
        w = qt.QWidget(self)
        w.setLayout(g)
        self.setCentralWidget(w)

        # label
        g.addWidget(qt.QLabel(_('Recent files:')), 0, 0, 1, 3)

        # disks
        self._model = model = qt.QStandardItemModel()
        g.addWidget(table, 1, 0, 1, 3)
        table.setModel(model)
        table.setItemDelegate(guiutil.NoFocusItemDelegate())
        table.setSelectionMode(qt.QAbstractItemView.SingleSelection)
        table.setSelectionBehavior(qt.QAbstractItemView.SelectRows)
        table.setHorizontalScrollMode(qt.QAbstractItemView.ScrollPerPixel)
        table.setVerticalScrollMode(qt.QAbstractItemView.ScrollPerPixel)
        table.activated.connect(
            lambda m_idx: self._open(model.item(m_idx.row(), COL_PATH).text()))
        table.right_click.connect(menu.popup)

        table.setShowGrid(False)
        table.setWordWrap(False)
        # only affects the last column - no others have resize mode stretch
        table.setTextElideMode(qt.Qt.ElideLeft)
        h = table.horizontalHeader()
        h.hide()
        h.setSectionResizeMode(qt.QHeaderView.ResizeToContents)
        h.setStretchLastSection(True)
        table.verticalHeader().hide()

        # disks menu
        menu.setToolTipsVisible(True)
        for action in table_actions.values():
            menu.addAction(action)

        # buttons
        for name, where in (
            ('open', (2, 0)), ('remove', (2, 1)), ('remove all', (2, 2)),
            ('browse', (3, 0, 1, 3))
        ):
            action = window_actions.get(name, table_actions.get(name))
            g.addWidget(guiutil.ActionButton(action), *where)

        self._add_fns(*self._fn_hist)

    def _save_hist (self):
        """Save the current known files list to disk."""
        conf.write_lines('disk_history', self._fn_hist)

    def _open (self, fn):
        """Open the given disk image."""
        if run_editor(fn, self):
            self._quit()
            add_to_hist(self._fn_hist, fn)

    def _get_selected_row (self):
        """Get the index of the currently selected disks table row, or None."""
        rows = self._table.selectionModel().selectedRows()
        return rows[0].row() if len(rows) == 1 else None

    def _open_current (self):
        """Open the currently selected disk image."""
        row = self._get_selected_row()
        if row is not None:
            self._open(self._model.item(row, COL_PATH).text())

    def _rm_current (self):
        """Remove the currently selected disk image."""
        row = self._get_selected_row()
        msg = _('Remove the selected file from this list?')
        btns = ((_('&Cancel'), 'window-close', qt.QMessageBox.RejectRole),
                (_('&Remove Anyway'), 'list-remove',
                 qt.QMessageBox.DestructiveRole))
        if (row is not None and guiutil.question(msg, btns, self, 0, True,
                                                 ('rm_disk', 1)) == 1):
            fn = self._model.item(row, COL_PATH).text()
            if self._model.removeRow(row):
                self._fn_hist.remove(fn)
                self._save_hist()

    def _rm_all (self):
        """Remove all disk images."""
        msg = _('Remove the selected file from this list?')
        btns = ((_('&Cancel'), 'window-close', qt.QMessageBox.RejectRole),
                (_('&Remove Anyway'), 'list-remove',
                 qt.QMessageBox.DestructiveRole))
        if (self._fn_hist and guiutil.question(msg, btns, self, 0, True,
                                               ('rm_all_disks', 1)) == 1):
            self._fn_hist = []
            self._save_hist()
            self._model.clear()

    def _browse (self):
        """Show a file chooser to find a disk image."""
        fns = browse(self._fn_hist, self)
        if fns is True:
            self._quit()
        elif fns:
            self._add_fns(*fns)

    def _add_details (self, name, icon, size, fn, tooltip):
        """Fill out data for a disk in the known list."""
        model = self._model
        # update all rows containing this disk (should only be one anyway)
        for row in range(model.rowCount()):
            if model.item(row, COL_PATH).text() == fn:
                for col, data in enumerate((name, icon, size, fn)):
                    item = model.item(row, col)
                    update_model_item(item, data)
                    item.setToolTip(tooltip)

    def _add_fns (self, *fns):
        """Add the given disk images to the tree.

Each is as stored in the history.

"""
        model = self._model
        old_fns = {model.item(i, COL_PATH).text()
                   for i in range(model.rowCount())}

        # insert new rows at the top
        for fn in fns:
            if fn not in old_fns:
                # use a row with basic data until we've loaded the details
                row = []
                for data in (
                    os.path.basename(fn), guiutil.invalid_icon(), None, fn
                ):
                    item = qt.QStandardItem()
                    update_model_item(item, data)
                    item.setEditable(False)
                    row.append(item)
                model.insertRow(0, row)

                # start data-loading thread
                run = LoadThread(fn)
                run.signals.loaded.connect(self._add_details)
                qt.QThreadPool.globalInstance().start(run)

    def _quit (self):
        self.close()


def run (set_main_window):
    fn_hist = conf.read_lines('disk_history')
    ldr = LoadDisk(fn_hist)
    ldr.show()
    set_main_window(ldr)


def load (fn, set_main_window):
    # try to load given file
    if run_editor(fn):
        fn_hist = conf.read_lines('disk_history')
        add_to_hist(fn_hist, fn)
    else:
        # failed: fall back to loader
        run(set_main_window)
