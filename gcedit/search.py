"""gcedit search window module.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

    CLASSES

SearchResultsBackend
SearchWindow

"""

from gi.repository import Gtk as gtk, Pango as pango

from .ext.fsmanage import Manager
from .ext.gcutil import search_tree

from . import guiutil, conf

# TODO:
# [FEA] history (gtk.EntryCompletion)
# [FEA] options (case-sensitive, regex, whole name, include dirs/files)
# [ENH] setting to close search on choosing an item
# [ENH] enable results column headers, and make them resizable


class SearchResultsBackend:
    """A read-only fsmanage backend that lists search results.

Takes the current Editor instance.

    ATTRIBUTES

items: a list of files and directories, each an (is_dir, path) tuple, where
       path is the item's full list-style path in the searched filesystem.  The
       root directory cannot be included (because it has no name).  Modify this
       attribute directly then call the Manager's refresh method to display
       the results.

"""

    def __init__ (self, editor):
        self.editor = editor
        self.items = []

    def list_dir (self, path):
        printable_path = guiutil.printable_path
        return [(path[-1], is_dir, printable_path(path[:-1]), repr(path)) \
                for is_dir, path in self.items]

    def open_items (self, *items):
        assert len(items) == 1
        try:
            self.editor.file_manager.present_item(eval(items[0][2]))
        except ValueError:
            # doesn't exist (any more)
            msg = _('The selected file no longer exists.')
            guiutil.error(msg, self.editor.search)
        else:
            self.editor.present()

    #def open_files (self, *files):
        #assert len(files) == 1
        #self.editor.file_manager.present_item(eval(files[0][2]))
        #self.editor.present()

    #def open_dirs (self, *dirs):
        #assert len(dirs) == 1
        #self.editor.file_manager.set_path(eval(dirs[0][2]))
        #self.editor.present()


class SearchWindow (guiutil.Window):
    """Search window (guiutil.Window subclass).

Takes the current Editor instance.

    METHODS

search

    ATTRIBUTES

manager: fsmanage.Manager instance.
entry: the gtk.Entry used for the search text.

"""

    def __init__ (self, editor):
        self.editor = editor
        # window
        guiutil.Window.__init__(self, 'search')
        self.set_border_width(12)
        self.set_title('Find Files - {}'.format(conf.APPLICATION))
        self.connect('delete-event', self._close)
        # close on escape
        group = gtk.AccelGroup()
        find = lambda *args: self.entry.grab_focus()
        for accel, cb in (('Escape', self._close),
                          ('<ctrl>f', find),
                          ('F3', find)):
            key, mods = gtk.accelerator_parse(accel)
            group.connect(key, mods, 0, cb)
        self.add_accel_group(group)
        # widgets
        g = gtk.Grid()
        g.set_row_spacing(6)
        g.set_column_spacing(6)
        self.add(g)
        # backend, manager
        backend = SearchResultsBackend(editor)
        r = gtk.CellRendererText()
        r.set_property('ellipsize', pango.EllipsizeMode.END)
        extra_cols = [(_('Parent'), r, True), ('path', False)]
        self.manager = m = Manager(backend, [], True, False, False, False,
                                   False, extra_cols)
        s = gtk.ScrolledWindow()
        g.attach(s, 0, 0, 3, 1)
        s.set_policy(gtk.PolicyType.NEVER, gtk.PolicyType.AUTOMATIC)
        s.add(m)
        m.set_hexpand(True)
        m.set_vexpand(True)
        # bar
        self.entry = e = gtk.Entry()
        g.attach(e, 0, 1, 1, 1)
        e.connect('activate', self.search) # activating default is slow...?
        b = gtk.Button(None, gtk.STOCK_FIND)
        b.set_can_default(True)
        g.attach(b, 1, 1, 1, 1)
        b.grab_default()
        b.connect('clicked', self.search)
        b = gtk.Button(None, gtk.STOCK_CLOSE)
        g.attach(b, 2, 1, 1, 1)
        b.connect('clicked', self._close)
        self.show_all()
        self.hide()

    def search (self, *args):
        """Perform a search: show matches for the current text and options."""
        text = self.entry.get_text()
        results = search_tree(self.editor.fs.tree, text)
        items = [(is_dir, [d_name for d_name, d_index in path] + [name]) \
                 for is_dir, path, (name, index) in results]
        self.manager.backend.items = items
        self.manager.refresh()

    def _focus_manager (self, *args):
        """Give manager focus if entry is focused."""
        if self.entry.is_focus():
            self.manager.grab_focus()

    def _close (self, *args):
        """Close callback."""
        self.editor.end_find()
        return True