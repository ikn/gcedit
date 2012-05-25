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
# [ENH] show name, banner, size, other details (need BNR support)
# [ENH] confirm _rm, _rm_all

from os.path import abspath, basename

from gi.repository import Gtk as gtk, Pango as pango

from . import conf, guiutil
from .editor import Editor
from .ext.gcutil import GCFS

COL_FN = 0
COL_PATH = 1

def run_editor (fn, parent = None):
    """Start and display the editor.

run_editor(fn[, parent]) -> valid

fn: filename to load as a disk image.
parent: parent window for the error dialogue, if shown.

valid: whether the file was found to be valid (if not, an error dialogue is
       shown and the editor isn't started).

"""
    try:
        fs = GCFS(fn)
    except: # TODO: [ENH] raise something in GCFS if invalid
        # TODO: [ENH] show error dialogue and return to disk loader
        return False
    else:
        # start the editor
        Editor(fs).show()
        # make sure the editor is realised before returning (so that destroying
        # parent happens after, and editor gets focus)
        while gtk.events_pending():
            gtk.main_iteration()
        return True

def add_to_hist (fn, fn_hist):
    """Add a disk image filename to the history.

add_to_hist(fn, fn_hist)

fn: filename to add.
fn_hist: current disk image history.

"""
    fn = abspath(fn)
    if conf.mru_add(fn_hist, fn)[0]:
        conf.write_lines('disk_history', fn_hist)

def browse (fn_hist = None, parent = None):
    """Browse for a disk image and open it in the editor.

browse(fn_hist[, parent]) -> opened

fn_hist: current disk image history.
parent: a window for the dialogue's parent.

opened: whether the disk image was opened in the editor.

"""
    rt = gtk.ResponseType
    buttons = (gtk.STOCK_CLOSE, rt.CLOSE, gtk.STOCK_OK, rt.OK)
    # NOTE: the title for a file open dialogue
    load = gtk.FileChooserDialog(_('Open disk image'), parent,
                                 gtk.FileChooserAction.OPEN, buttons)
    if load.run() == rt.OK:
        # got one
        fn = load.get_filename()
    else:
        fn = None
    load.destroy()
    # open file if given
    if fn is not None:
        if run_editor(fn):
            add_to_hist(fn, fn_hist)
            return True
    return False


class LoadDisk (guiutil.Window):
    """The window for choosing a disk image to load.

    CONSTRUCTOR

LoadDisk(fn_hist)

fn_hist: current disk image history; must have at least one item.

"""

    def __init__ (self, fn_hist):
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
        self._model = m = gtk.ListStore(str, str)
        self._model.set_default_sort_func(self._sort_tree)
        # FIXME: -1 should be DEFAULT_SORT_COLUMN_ID, but I can't find it
        self._model.set_sort_column_id(-1, gtk.SortType.DESCENDING)
        self._tree = tree = gtk.TreeView(m)
        tree.set_headers_visible(False)
        tree.set_search_column(COL_FN)
        tree.set_rules_hint(True)
        tree.set_tooltip_column(COL_PATH)
        open_cb = lambda t, path, c: self._open(self._model[path][COL_PATH])
        tree.connect('row-activated', open_cb)
        tree.connect('button-press-event', self._click)
        # content
        r = gtk.CellRendererText()
        r.set_property('ellipsize', pango.EllipsizeMode.END)
        c = gtk.TreeViewColumn(_('Filename'), r, text = COL_FN)
        c.set_expand(True)
        tree.append_column(c)
        self._add_fns(*fn_hist)
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
        self.hide()

    def _get_selected (self):
        """Get (model, iter, file_path) for the selected disk image.

i and file_path are None if nothing is selected.

"""
        m, i = self._tree.get_selection().get_selected()
        if i is None:
            return m, None, None
        else:
            return m, i, m[i][COL_PATH]

    def _add_fns (self, *fns):
        """Add the given disk images to the tree.

Each is as stored in the history.

"""
        m = self._model
        for fn in fns:
            m.append((basename(fn), fn))

    def _open (self, fn):
        """Open the given disk image."""
        if run_editor(fn):
            self.destroy()
            add_to_hist(fn, self._fn_hist)

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
            self._fn_hist.remove(m[i][COL_PATH])
            conf.write_lines('disk_history', self._fn_hist)
            del m[i]

    def _rm_all (self, *args):
        """Remove all disk images."""
        if self._fn_hist:
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
            path = self._get_selected()[1]
            if path is None:
                path = False
        if path:
            fn = self._model[path][COL_PATH]
            items = [(gtk.STOCK_OPEN, lambda *args: self._open(fn)),
                     (gtk.STOCK_REMOVE, self._rm)]
        else:
            items = []
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
        if browse(self._fn_hist, self):
            self.destroy()

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
        gtk.main_quit()