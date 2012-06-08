"""gcedit search window module.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

    CLASSES

SearchResultsBackend
SearchWindow

"""

from html import escape

from gi.repository import Gtk as gtk, Pango as pango
from .ext.fsmanage import Manager, COL_LAST
from .ext.gcutil import search_tree

from . import guiutil, conf
from .conf import settings

# TODO:
# [FEA] options (case-sensitive, regex, whole name, include dirs/files)


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
        return [(path[-1], is_dir, printable_path(path[:-1]),
                 escape(printable_path(path)), repr(path)) \
                for is_dir, path in self.items]

    def open_items (self, *items):
        assert len(items) == 1
        try:
            self.editor.file_manager.present_item(eval(items[0][3]))
        except ValueError:
            # doesn't exist (any more)
            msg = _('The selected file no longer exists.')
            guiutil.error(msg, self.editor.search)
        else:
            self.editor.present()
            if settings['close_search']:
                self.editor.end_find()


class SearchWindow (guiutil.Window):
    """Search window (guiutil.Window subclass).

Takes the current Editor instance.

    METHODS

search
cleanup

    ATTRIBUTES

editor: as given.
history: a list of past searches.
manager: fsmanage.Manager instance.
entry: the gtk.Entry used for the search text.

"""

    def __init__ (self, editor):
        self.editor = editor
        self.history = conf.read_lines('search_history')
        self._hist_changed = False
        backend = SearchResultsBackend(editor)
        r = gtk.CellRendererText()
        r.set_property('ellipsize', pango.EllipsizeMode.END)
        extra_cols = [(_('Parent Directory'), r, True), None, None]
        self.manager = m = Manager(backend, [], True, False, False, extra_cols)
        m.get_selection().set_mode(gtk.SelectionMode.SINGLE)
        m.set_headers_visible(True)
        m.set_tooltip_column(COL_LAST + 2)
        # window
        guiutil.Window.__init__(self, 'search')
        self.set_border_width(12)
        self.set_title('Find Files - {}'.format(conf.APPLICATION))
        self.connect('delete-event', self._close)
        # shortcuts
        group = gtk.AccelGroup()
        find = lambda *args: self.entry.grab_focus()
        for accel, cb in (('Escape', self._close),
                          ('<ctrl>f', find),
                          ('F3', find)):
            key, mods = gtk.accelerator_parse(accel)
            group.connect(key, mods, 0, cb)
        self.add_accel_group(group)
        self.add_accel_group(m.accel_group)
        # widgets
        g = gtk.Grid()
        g.set_row_spacing(6)
        g.set_column_spacing(6)
        self.add(g)
        # manager
        s = gtk.ScrolledWindow()
        g.attach(s, 0, 0, 2, 1)
        s.set_policy(gtk.PolicyType.AUTOMATIC, gtk.PolicyType.AUTOMATIC)
        s.add(m)
        m.set_hexpand(True)
        m.set_vexpand(True)
        # completion for search history
        c = gtk.EntryCompletion()
        self._completion_model = model = gtk.ListStore(str)
        for search in self.history:
            model.append((search,))
        c.set_model(model)
        c.set_text_column(0)
        c.connect('match-selected', self._complete)
        # entry
        self.entry = e = gtk.Entry()
        e.set_completion(c)
        e.set_hexpand(True)
        g.attach(e, 0, 1, 1, 1)
        e.connect('activate', self.search) # activating default is slow...?
        # buttons
        bb = gtk.ButtonBox(gtk.Orientation.HORIZONTAL)
        bb.set_spacing(6)
        g.attach(bb, 1, 1, 1, 1)
        b = guiutil.Button(gtk.STOCK_FIND)
        b.set_can_default(True)
        bb.pack_start(b, False, False, 0)
        b.grab_default()
        b.connect('clicked', self.search)
        b = guiutil.Button(gtk.STOCK_CLOSE)
        bb.pack_start(b, False, False, 0)
        b.connect('clicked', self._close)
        self.show_all()
        self.hide()

    def _complete (self, c, m, i):
        """Callback for selecting a completion for the search box."""
        self.entry.set_text(m[i][0])
        self.search()
        return True

    def search (self, *args):
        """Perform a search: show matches for the current text and options."""
        search = self.entry.get_text()
        results = search_tree(self.editor.fs.tree, search)
        items = [(is_dir, [d_name for d_name, d_index in path] + [name]) \
                 for is_dir, path, (name, index) in results]
        self.manager.backend.items = items
        self.manager.refresh()
        # add to history
        if search:
            changed, new = conf.mru_add(self.history, search)
            if changed:
                self._hist_changed = True
            if new:
                self._completion_model.append((search,))

    def _focus_manager (self, *args):
        """Give manager focus if entry is focused."""
        if self.entry.is_focus():
            self.manager.grab_focus()

    def cleanup (self):
        """Save some stuff."""
        if self._hist_changed:
            h = self.history
            # truncate history if necessary
            if settings['search_hist_limited']:
                max_size = settings['search_hist_size']
                if max_size == 0:
                    h = []
                else:
                    h = h[-max_size:]
            conf.write_lines('search_history', h)
            self._hist_changed = False

    def _close (self, *args):
        """Close callback."""
        self.editor.end_find()
        return True