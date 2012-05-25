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
# - show name, banner, size, other details
#   - need BNR support
# - 'browse' button
# - option to always load chosen disk on startup
# - _rm, _click, _menu (has Open, Remove, Clear List)

from os.path import abspath, basename

from gi.repository import Gtk as gtk, Pango as pango

from gcedit import conf, guiutil
from gcedit.editor import Editor
from gcedit.ext.gcutil import GCFS

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
    if fn not in fn_hist:
        fn_hist.append(fn)
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
        g.set_row_spacing(6)
        self.add(g)

        # treeview
        self._model = m = gtk.ListStore(str, str)
        m.set_sort_column_id(COL_FN, gtk.SortType.ASCENDING)
        self._tree = tree = gtk.TreeView(m)
        tree.set_headers_visible(False)
        tree.set_search_column(COL_FN)
        tree.set_rules_hint(True)
        tree.set_tooltip_column(COL_PATH)
        tree.connect('row-activated', self._open)
        self.connect('button-press-event', self._click)
        # content
        r = gtk.CellRendererText()
        r.set_property('ellipsize', pango.EllipsizeMode.END)
        c = gtk.TreeViewColumn(_('Filename'), r, text = COL_FN)
        c.set_expand(True)
        tree.append_column(c)
        self._add_fns(*fn_hist)
        # add to window
        s = gtk.ScrolledWindow()
        g.attach(s, 0, 0, 1, 1)
        s.set_policy(gtk.PolicyType.NEVER, gtk.PolicyType.AUTOMATIC)
        s.add(tree)
        tree.set_hexpand(True)
        tree.set_vexpand(True)
        # accelerators
        group = self.accel_group = gtk.AccelGroup()
        accels = [
            ('Menu', self._menu),
            ('Delete', self._rm)
        ]
        def mk_fn (cb, *cb_args):
            def f (*args):
                if self.is_focus():
                    cb(*cb_args)
            return f
        for accel, cb, *args in accels:
            key, mods = gtk.accelerator_parse(accel)
            group.connect(key, mods, 0, mk_fn(cb, *args))
        # button
        b = gtk.Button('_Browse...', None, True)
        g.attach(b, 0, 1, 1, 1)
        b.connect('clicked', self._browse)

        self.show_all()
        self.hide()

    def _add_fns (self, *fns):
        """Add the given disk images to the tree.

Each is as stored in the history.

"""
        m = self._model
        for fn in fns:
            m.append((basename(fn), fn))

    def _open (self, tree, path, column):
        """Open a file."""
        fn = self._model[path][COL_PATH]
        if run_editor(fn):
            self.destroy()
            add_to_hist(fn, self._fn_hist)

    def _click (self, tree, event):
        """Callback for clicking the tree."""
        pass

    def _rm (self):
        """Remove the currently selected disk image."""
        pass

    def _menu (self):
        """Show a context menu."""
        pass

    def _browse (self, b):
        """Show a file chooser to find a disk image."""
        if browse(self._fn_hist, self):
            self.destroy()

    def quit (self, *args):
        """Quit the application."""
        gtk.main_quit()