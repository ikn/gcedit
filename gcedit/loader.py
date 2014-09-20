"""gcedit disk image loader module.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

    CLASSES

LoadDisk

    FUNCTIONS

run_editor
add_to_hist
browse

"""

# TODO:
# [ENH] allow selecting multiple disks and removing them all at once
#   - change text in rm confirmation to indicate multiple
#   - open the first selected (warn if more than one)

from os.path import abspath, basename, getsize
from html import escape
from threading import Thread
from queue import Queue

from gi.repository import Gtk as gtk, Pango as pango, GdkPixbuf as pixbuf
from gi.repository.GLib import GError
from .ext.gcutil import GCFS, DiskError, bnr_to_pnm

from . import conf, guiutil
from .conf import settings

COL_NAME = 0
COL_ICON = 1
COL_SIZE = 2
COL_PATH = 3
COL_INFO = 4

def run_editor (fn, parent = None):
    """Start and display the editor.

run_editor(fn[, parent]) -> valid

fn: filename to load as a disk image.
parent: parent window for the error dialogue, if shown; this is destroyed if
        the file is a valid disk image.

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
        if parent:
            parent.destroy()
        # start the editor (import here because editor imports this module)
        from .editor import Editor
        Editor(fs).show()
        return True

def add_to_hist (fn_hist, *fns):
    """Add disk image filenames to the history.

add_to_hist(fn_hist, *fns)

fn_hist: current disk image history.
fns: filenames to add.

"""
    if any([conf.mru_add(fn_hist, abspath(fn))[0] for fn in fns]):
        conf.write_lines('disk_history', fn_hist)

def browse (fn_hist = None, parent = None, allow_multi = False):
    """Browse for a disk image and open it in the editor.

browse([fn_hist][, parent], allow_multi = False) -> opened

fn_hist: current disk image history; if not given, it is loaded from disk.
parent: a window for the dialogue's parent.
allow_multi: whether to allow loading multiple files.

opened: If True, one disk was chosen, added to the history and opened in the
        editor, and parent was destroyed.  If False, the action was cancelled,
        or one disk was chosen and it was invalid.  If a list of filenames,
        each one was added to the history.

"""
    rt = gtk.ResponseType
    buttons = (gtk.STOCK_CLOSE, rt.CLOSE, gtk.STOCK_OK, rt.OK)
    # NOTE: the title for a file open dialogue
    load = gtk.FileChooserDialog(_('Open Disk Image'), parent,
                                 gtk.FileChooserAction.OPEN, buttons)
    if allow_multi:
        load.set_select_multiple(True)
    load.set_current_folder(settings['loader_path'])
    if load.run() == rt.OK:
        # got one
        fns = load.get_filenames() if allow_multi else [load.get_filename()]
        # remember dir
        settings['loader_path'] = load.get_current_folder()
    else:
        fns = []
    load.destroy()
    if not fns:
        return False
    # add to history
    if fn_hist is None:
        fn_hist = conf.read_lines('disk_history')
    add_to_hist(fn_hist, *fns)
    if len(fns) == 1:
        if run_editor(fns[0], parent):
            return True
        else:
            return False
    else:
        return fns


class LoadDisk (guiutil.Window):
    """The window for choosing a disk image to load.

    CONSTRUCTOR

LoadDisk([fn_hist])

fn_hist: current disk image history; if not given, it is loaded from disk.

"""

    def __init__ (self, fn_hist = None):
        self.do_quit = False
        if fn_hist is None:
            self._fn_hist = conf.read_lines('disk_history')
        else:
            self._fn_hist = fn_hist
        # window
        guiutil.Window.__init__(self, 'loader')
        self.set_border_width(12)
        self.set_title(conf.APPLICATION)
        self.connect('delete-event', self.quit)
        g = gtk.Grid()
        g.set_column_spacing(6)
        g.set_row_spacing(6)
        self.add(g)

        # label
        l = gtk.Label(_('Recent files:'))
        l.set_alignment(0, .5)
        g.attach(l, 0, 0, 3, 1)
        # treeview
        self._model = m = gtk.ListStore(str, pixbuf.Pixbuf, str, str, str)
        m.set_default_sort_func(self._sort_tree)
        # FIXME: -1 should be DEFAULT_SORT_COLUMN_ID, but I can't find it
        m.set_sort_column_id(-1, gtk.SortType.DESCENDING)
        self._tree = tree = gtk.TreeView(m)
        tree.set_headers_visible(False)
        tree.set_search_column(COL_NAME)
        tree.set_rules_hint(True)
        tree.set_tooltip_column(COL_INFO)
        open_cb = lambda t, path, c: self._open(m[path][COL_PATH])
        tree.connect('row-activated', open_cb)
        tree.connect('button-press-event', self._click)
        # content
        cols = []
        for name, col, *props in (
            (_('Name'), COL_NAME),
            (_('Size'), COL_SIZE),
            (_('Path'), COL_PATH, ('ellipsize', pango.EllipsizeMode.START))
        ):
            r = gtk.CellRendererText()
            for k, v in props:
                r.set_property(k, v)
            cols.append(gtk.TreeViewColumn(name, r, text = col))
        r = gtk.CellRendererPixbuf()
        cols.insert(1, gtk.TreeViewColumn(_('Banner'), r, pixbuf = COL_ICON))
        for col in cols:
            tree.append_column(col)
        # add to window
        s = gtk.ScrolledWindow()
        g.attach(s, 0, 1, 3, 1)
        s.set_policy(gtk.PolicyType.NEVER, gtk.PolicyType.AUTOMATIC)
        s.add(tree)
        tree.set_hexpand(True)
        tree.set_vexpand(True)
        # accelerators
        group = self.accel_group = gtk.AccelGroup()
        accels = [
            ('Menu', self._menu, 0, gtk.get_current_event_time()),
            ('Delete', self._rm)
        ]
        def mk_fn (cb, *cb_args):
            def f (*args):
                if tree.is_focus():
                    cb(*cb_args)
            return f
        for accel, cb, *args in accels:
            key, mods = gtk.accelerator_parse(accel)
            group.connect(key, mods, 0, mk_fn(cb, *args))
        self.add_accel_group(group)
        # buttons
        for i, (data, cb) in enumerate((
            (gtk.STOCK_OPEN, self._open_current),
            (gtk.STOCK_REMOVE, self._rm),
            ((_('Remove _All'), gtk.STOCK_REMOVE), self._rm_all)
        )):
            b = guiutil.Button(data)
            g.attach(b, i, 2, 1, 1)
            b.connect('clicked', cb)
        b = guiutil.Button((_('_Browse...'), gtk.STOCK_FIND))
        g.attach(b, 0, 3, 3, 1)
        b.connect('clicked', self._browse)

        self.show_all()
        self._add_fns(*self._fn_hist)
        tree.grab_focus()

    def _get_selected (self):
        """Get (model, iter, file_path) for the selected disk image.

i and file_path are None if nothing is selected.

"""
        m, i = self._tree.get_selection().get_selected()
        if i is None:
            return (m, None, None)
        else:
            return (m, i, m[i][COL_PATH])

    def _get_disk_info (self, q, fns):
        for fn in fns:
            try:
                fs = GCFS(fn)
                info = fs.get_info()
                info.update(fs.get_bnr_info())
            except (IOError, DiskError, ValueError):
                info = None
            else:
                # load image into pixbuf
                try:
                    img = bnr_to_pnm(info['img'])
                    ldr = pixbuf.PixbufLoader.new_with_type('pnm')
                    ldr.write(img)
                    info['img'] = ldr.get_pixbuf()
                    ldr.close()
                except GError:
                    info['img'] = None
            try:
                size = getsize(fn)
            except OSError:
                size = None
            q.put((size, info))

    def _add_fns (self, *fns):
        """Add the given disk images to the tree.

Each is as stored in the history.

"""
        if not fns:
            return
        m = self._model
        # fill in basic data
        for fn in fns:
            m.append((basename(fn), None, '', fn, ''))
        # disable sorting
        # FIXME: -2 should be UNSORTED_SORT_COLUMN_ID, but I can't find it
        m.set_sort_column_id(-2, gtk.SortType.ASCENDING)
        # get new order
        old_fns, fns = fns, []
        rows = []
        for i, row in enumerate(m):
            fn = row[COL_PATH]
            if fn in old_fns:
                rows.append(i)
                fns.append(fn)
        # select first new row
        self._tree.get_selection().select_path(rows[0])
        # start data-loading thread
        q = Queue()
        t = Thread(target = self._get_disk_info, args = (q, fns))
        t.start()
        for i, fn in zip(rows, fns):
            while q.empty():
                while gtk.events_pending():
                    gtk.main_iteration()
            data = q.get()
            size, info = data
            if size is None:
                size = ''
            else:
                size = guiutil.printable_filesize(size)
            if info is None:
                name = basename(fn)
                tooltip = escape(fn)
            else:
                name = info['name']
                tooltip = '<b>{} ({}, {})</b>\n{}'
                tooltip = tooltip.format(*(escape(arg) for arg in (
                    info['full name'], info['code'], info['full developer'], fn
                )))
                desc = ' '.join(info['description'].splitlines()).strip()
                if desc:
                    tooltip += '\n\n' + desc
            m[i] = (name, info['img'], size, fn, tooltip)
        # re-enable sorting
        # FIXME: -1 should be DEFAULT_SORT_COLUMN_ID, but I can't find it
        m.set_sort_column_id(-1, gtk.SortType.DESCENDING)
        # wait for thread
        t.join()

    def _open (self, fn):
        """Open the given disk image."""
        if run_editor(fn, self):
            add_to_hist(self._fn_hist, fn)

    def _open_current (self, *args):
        """Open the currently selected disk image."""
        m, i, fn = self._get_selected()
        if fn is not None:
            self._open(fn)

    def _click (self, tree, event):
        """Callback for clicking the tree."""
        if event.button not in (1, 3):
            return
        tree = self._tree
        sel = tree.get_path_at_pos(int(event.x), int(event.y))
        if sel is None:
            # deselect
            tree.get_selection().unselect_all()
        if event.button == 3:
            # right-click: show context menu
            if sel is None:
                # no-file context menu
                self._menu(event.button, event.time, False)
            else:
                self._menu(event.button, event.time, sel[0])

    def _rm (self, *args):
        """Remove the currently selected disk image."""
        m, i, fn = self._get_selected()
        if fn is not None:
            btns = (gtk.STOCK_CANCEL, _('_Remove Anyway'))
            if 'rm_disk' not in settings['disabled_warnings']:
                msg = _('Remove the selected file from this list?')
                if guiutil.question(msg, btns, self, None, True,
                                    ('rm_disk', 1)) != 1:
                    return
            self._fn_hist.remove(fn)
            conf.write_lines('disk_history', self._fn_hist)
            del m[i]

    def _rm_all (self, *args):
        """Remove all disk images."""
        if self._fn_hist:
            btns = (gtk.STOCK_CANCEL, _('_Remove Anyway'))
            if 'rm_all_disks' not in settings['disabled_warnings']:
                msg = _('Remove all files from this list?')
                if guiutil.question(msg, btns, self, None, True,
                                    ('rm_all_disks', 1)) != 1:
                    return
            self._fn_hist = []
            conf.write_lines('disk_history', [])
            self._model.clear()

    def _menu (self, btn = None, time = None, path = None):
        """Show a context menu.

_menu([btn][, time][, path])

btn: event button, if any.
time: event time, if any.
path: Gtk.TreePath for the row to show a menu for, or False to show a menu for
      no row; if not given, the current selection is used.

"""
        if path is None:
            fn = self._get_selected()[2]
        elif path is False:
            fn = None
        else:
            fn = self._model[path][COL_PATH]
        if fn is None:
            items = []
        else:
            items = [(gtk.STOCK_OPEN, lambda *args: self._open(fn)),
                     (gtk.STOCK_REMOVE, self._rm)]
        items.append(((_('Remove _All'), gtk.STOCK_REMOVE), self._rm_all))
        # create menu
        # HACK: need to store the menu for some reason, else it doesn't show up
        # - maybe GTK stores it in such a way that the garbage collector thinks
        # it can get rid of it or something
        menu = self._temp_menu = gtk.Menu()
        for data, cb in items:
            item = guiutil.MenuItem(data)
            item.connect('activate', cb)
            menu.append(item)
        menu.show_all()
        menu.popup(None, None, None, None, btn, time)

    def _browse (self, b):
        """Show a file chooser to find a disk image."""
        old_fns = list(self._fn_hist)
        fns = browse(self._fn_hist, self, True)
        if fns not in (True, False):
            self._add_fns(*(fn for fn in fns if fn not in old_fns))

    def _sort_tree (self, model, iter1, iter2, data):
        """Sort callback."""
        path1 = model[iter1][COL_PATH]
        path2 = model[iter2][COL_PATH]
        if path1 == path2:
            return 0
        else:
            h = self._fn_hist
            return h.index(path1) - h.index(path2)

    def quit (self, *args):
        """Quit the application."""
        if gtk.main_level():
            gtk.main_quit()
        else:
            self.do_quit = True
            return True
