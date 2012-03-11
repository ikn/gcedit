"""gcedit editor module.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

    CLASSES

FSBackend
Editor

"""

# TODO:
# - pasting/creating dir/importing in non-existent dir breaks things
# - can't import Documents/Music (check what utf-8 encoding a unicode string with japanese does) (should just show error: can't have such a filename?) (is it really shift-jis?  check yagcd)
# - buttons tab order is weird
# - remember last import/extract paths (separately)
# - can search within filesystem
# - menus:
#   - switch disk image
#   - buttons
#   - compress, decompress, discard all changes (fs.update(), manager.refresh()), reload from disk (fs.update())
#   - split view (horiz/vert/close)
# - built-in tabbed editor (expands window out to the right)
#   - if rename/move a file being edited, rename the tab
#   - if delete, show error
#   - if write, ask if want to save files being edited; afterwards, 're-open' them and show error if can't for some reason
#   - in context menu, buttons
#   - on open, check if can decode to text; if not, have hex editor
#   - option for open_files to edit instead of extract
# - track deleted files (not dirs) (get paths recursively) and put in trash when write

# NOTE: os.stat().st_dev gives path's device ID

import os
from traceback import format_exc

from gi.repository import Gtk as gtk
from .ext import fsmanage
from .ext.gcutil import tree_from_dir

IDENTIFIER = 'gcedit'

def nice_path (path):
    """Get a printable version of a list-style path."""
    return '/' + '/'.join(path)

def text_viewer (text, wrap_mode = gtk.WrapMode.WORD):
    """Get a read-only Gtk.TextView widget in a Gtk.ScrolledWindow.

text_viewer(text, wrap_mode = Gtk.WrapMode.WORD) -> widget



"""
    w = gtk.ScrolledWindow()
    v = gtk.TextView()
    w.add(v)
    v.set_editable(False)
    v.set_cursor_visible(False)
    v.set_wrap_mode(wrap_mode)
    v.get_buffer().set_text(text)
    v.set_vexpand(True)
    v.set_hexpand(True)
    v.set_valign(gtk.Align.FILL)
    v.set_halign(gtk.Align.FILL)
    v.show()
    return w

def error (msg, parent = None, *widgets, spacing = 12):
    """Show an error dialogue.

error(msg, parent = None, *widgets, spacing = 12)

msg: text to display.
parent: dialogue parent.
widgets: widgets to add to the same grid as the text, which is at (0, 0) with
         size (1, 1).  A widget can be (widget, x, y, w, h) to determine its
         position; otherwise, it is placed the first free cell in column 0 once
         all widgets with given positions have been placed.
         widget.show() is called.
spacing: spacing between added widgets in both directions.  Pass
         (h_spacing, v_spacing) to specify them separately.  This is a
         keyword-only argument.

"""
    # using .run(), so don't need modal flag
    d = gtk.Dialog('Error', parent, gtk.DialogFlags.DESTROY_WITH_PARENT,
                   (gtk.STOCK_OK, gtk.ResponseType.OK))
    # label
    msg = gtk.Label(msg)
    msg.set_line_wrap(True)
    msg.set_selectable(True)
    msg.set_halign(gtk.Align.START)
    msg.set_valign(gtk.Align.START)
    # some properties
    d.set_resizable(False)
    d.set_default_response(gtk.ResponseType.OK)
    c = d.get_content_area()
    c.set_property('margin', 12)
    c.set_spacing(12)
    # grid
    g = gtk.Grid()
    c.pack_start(g, True, True, 0)
    if isinstance(spacing, int):
        spacing = (spacing, spacing)
    g.set_column_spacing(spacing[0])
    g.set_row_spacing(spacing[1])
    # add label and given widgets, if any
    used_rows = set()
    todo = []
    min_x = 0
    min_y = 0
    max_y = 1
    i = 0
    for widget in ((msg, 0, 0, 1, 1),) + widgets:
        if isinstance(widget, gtk.Widget):
            # leave until later
            todo.append(widget)
        else:
            # place where asked
            widget, x, y, w, h = widget
            if x <= 0 and x + w > 0:
                used_rows.update(range(y, y + h))
            g.attach(widget, x, y, w, h)
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y + w)
        widget.show()
    for widget in todo:
        # place in first free cell in column 0
        while i in used_rows:
            i += 1
        g.attach(widget, 0, i, 1, 1)
        max_y = max(max_y, i + 1)
        i += 1
    # add image
    img = gtk.Image.new_from_stock(gtk.STOCK_DIALOG_ERROR, gtk.IconSize.DIALOG)
    img.set_halign(gtk.Align.CENTER)
    img.set_valign(gtk.Align.START)
    g.attach(img, min_x - 1, min_y, 1, max_y - min_y)
    img.show()
    # run
    g.show()
    d.run()
    d.destroy()


class FSBackend:
    """The backend for fsmanage, to make changes to the filesystem.

Takes a gcutil.GCFS instance and an Editor instance.

    METHODS

(as required by fsmanage.Manager)
get_tree
get_file
undo
redo
can_undo
can_redo
do_import

    ATTRIBUTES

fs, editor: the arguments given to the constructor.

"""

    def __init__ (self, fs, editor):
        self.fs = fs
        self.editor = editor
        self._hist_pos = 0
        self._hist = []

    def get_tree (self, path, return_parent = False):
        """Get the tree for the given path.

get_tree(path, return_parent = False) -> rtn

path: hierarchical list of directories.
return_parent: whether to return the parent of the required tree rather than
               the tree itself.

rtn: if return_parent is False this is the tree for the given path.  Otherwise,
     this is (parent, key), where:
    parent: the tree of the parent directory of the given path, or the root
            tree if the path is root.
    key: the key of the path's tree in the parent, or None if the path has no
         parent (is root).

"""
        tree = self.fs.tree
        for d in path:
            found = False
            for k in tree:
                if k is not None:
                    if k[0] == d:
                        # found the next dir in path
                        parent = tree
                        tree = tree[k]
                        found = True
                        break
            if not found:
                raise ValueError('invalid path')
        if return_parent:
            try:
                return parent, k
            except NameError:
                # never found any, but didn't raise an exception: this is root
                return tree, None
        else:
            return tree

    def get_file (self, path):
        """Get the the file at the given path in the tree.

Returns (parent, entry), where parent is the file's parent directory and entry
is its entry in the tree.

"""
        *path, name = path
        tree = self.get_tree(path)
        for entry in tree[None]:
            if entry[0] == name:
                return tree, entry
        # nothing found
        raise ValueError('invalid path')

    def undo (self):
        """Undo the last action."""
        if not self.can_undo():
            return
        self._hist_pos -= 1
        action, data = self._hist[self._hist_pos]
        if action == 'move':
            self.move(*((new, old) for old, new in data), hist = False)
        elif action == 'copy':
            self.delete(*(new for old, new in data), hist = False)
        elif action == 'delete':
            for x in data:
                parent = self.get_tree(x[0][:-1])
                if len(x) == 2:
                    # file
                    parent[None].append(x[1])
                else:
                    # dir
                    parent[x[1]] = x[2]
        elif action == 'new':
            self.delete(data, hist = False)
        else: # import
            for path, f in data:
                self.delete(path, hist = False)
        self.editor.file_manager.refresh()
        self.editor.update_hist_btns()

    def redo (self):
        """Redo the next action."""
        if not self.can_redo():
            return
        action, data = self._hist[self._hist_pos]
        self._hist_pos += 1
        if action == 'move':
            self.move(*data, hist = False)
        elif action == 'copy':
            self.copy(*data, hist = False)
        elif action == 'delete':
            self.delete(*(x[0] for x in data), hist = False)
        elif action == 'new':
            self.new_dir(data, hist = False)
        else: # import
            for (*parent, name), f in data:
                tree = self.get_tree(parent)
                if isinstance(f, dict):
                    # dir
                    tree[(name, None)] = f
                else:
                    # file
                    tree[None].append((name, f))
        self.editor.file_manager.refresh()
        self.editor.update_hist_btns()

    def can_undo (self):
        """Check whether there's anything to undo."""
        return self._hist_pos > 0

    def can_redo (self):
        """Check whether there's anything to redo."""
        return self._hist_pos < len(self._hist)

    def _add_hist (self, data):
        """Add an action to the history."""
        self._hist = self._hist[:self._hist_pos]
        self._hist.append(data)
        self._hist_pos += 1
        self.editor.update_hist_btns()

    def do_import (self, dirs):
        """Open an import dialogue.

Takes an argument indicating whether to import directories (else files).

"""
        rt = gtk.ResponseType
        if dirs:
            action = gtk.FileChooserAction.SELECT_FOLDER
        else:
            action = gtk.FileChooserAction.OPEN
        buttons = (gtk.STOCK_CLOSE, rt.CLOSE, gtk.STOCK_OK, rt.OK)
        d = gtk.FileChooserDialog('Choose files', self.editor, action, buttons)
        d.set_select_multiple(True)
        if d.run() == rt.OK:
            # import
            current_path = self.editor.file_manager.path
            current = self.get_tree(current_path)
            current_names = [name for name, i in current[None]]
            current_names += [x[0] for x in current if x is not None]
            new = []
            new_names = []
            for f in d.get_filenames():
                name = os.path.basename(f)
                failed = False
                # check if exists
                while name in current_names or name in new:
                    # exists: ask what action to take
                    print('failed:', f)
                    # TODO: show overwrite/don't copy/rename error dialogue
                    this_failed = True ##
                    break ##
                    if overwrite:
                        # TODO: careful of history
                        self.delete(new)
                        current_items.remove(name)
                    elif rename:
                        name = new_name
                    else:
                        failed = True
                        break
                if not failed:
                    # add to tree
                    if dirs:
                        tree = tree_from_dir(f)
                        current[(name, None)] = f = tree
                    else:
                        current[None].append((name, f))
                    new.append((current_path + [name], f))
                    new_names.append(name)
            if new:
                self.editor.file_manager.refresh(*new_names)
                self._add_hist(('import', new))
        d.destroy()

    def list_dir (self, path):
        try:
            tree = self.get_tree(path)
        except ValueError:
            # doesn't exist: show error
            error('Directory doesn\'t exist.', self.editor)
            items = []
        else:
            # dirs
            items = [(k[0], True) for k in tree if k is not None]
            # files
            items += [(name, False) for name, i in tree[None]]
        return items

    def open_files (self, *files):
        self.editor.extract(*files)

    def copy (self, *data, return_failed = False, hist = True):
        failed = []
        cannot_copy = []
        for old, new in data:
            foreign = False
            if old[0] is True:
                # from another Manager: check data is valid
                this_data, old = old[1:]
                if not isinstance(this_data, tuple) or len(this_data) != 3 or \
                   this_data[0] != IDENTIFIER:
                    continue
                if this_data[2] == id(self.editor):
                    # same Editor
                    pass
                else:
                    # different Editor
                    foreign = True
                    # TODO
                    error('Drag-and-drop between instances is not supported ' \
                          'yet.')
                    print(this_data, old, new)
                    continue
            # get destination
            *dest, name = new
            dest = self.get_tree(dest)
            current_items = [k[0] for k in dest if k is not None]
            current_items += [name for name, i in dest[None]]
            is_dir = True
            try:
                # try to get dir
                parent, k = self.get_tree(old, True)
            except ValueError:
                # file instead
                is_dir = False
                try:
                    parent, k = self.get_file(old)
                except ValueError:
                    # been deleted or something
                    failed.append(old)
                    cannot_copy.append(nice_path(old))
                    continue
            this_failed = False
            while name in current_items:
                # exists
                # skip if it's the same file
                if old == new and not foreign:
                    this_failed = True
                    break
                # else ask what action to take
                # TODO: show overwrite/don't copy/rename error dialogue
                print('failed:', k[0]) ##
                this_failed = True ##
                break ##
                if overwrite:
                    # TODO: careful of history
                    self.delete(new)
                    current_items.remove(name)
                elif rename:
                    name = new_name
                    new = dest + [name]
                else:
                    this_failed = True
                    break
            if this_failed:
                failed.append(old)
            else:
                # copy
                if is_dir:
                    dest[(name, k[1])] = parent[k]
                else:
                    dest[None].append((new[-1], k[1]))
        if cannot_copy:
            # show error for files that couldn't be copied
            v = text_viewer('\n'.join(cannot_copy), gtk.WrapMode.NONE)
            error('Couldn\'t copy some items:', self.editor, v)
        # add to history
        if hist:
            succeeded = [x for x in data if x[0] not in failed]
            if succeeded:
                self._add_hist(('copy', succeeded))
        if return_failed:
            return failed
        else:
            return len(failed) != len(data)

    def move (self, *data, hist = True):
        failed = self.copy(*data, return_failed = True, hist = False)
        if len(failed) != len(data):
            succeeded = [x for x in data if x[0] not in failed]
            self.delete(*(old for old, new in succeeded), hist = False)
            # add to history
            if hist and succeeded:
                self._add_hist(('move', succeeded))
            return True
        else:
            return False

    def delete (self, *files, hist = True):
        done = []
        for f in files:
            try:
                # dir
                parent, k = self.get_tree(f, True)
            except ValueError:
                # file
                parent, entry = self.get_file(f)
                parent[None].remove(entry)
                done.append((f, entry))
            else:
                done.append((f, k, parent[k]))
                del parent[k]
        # history
        if hist and done:
            self._add_hist(('delete', done))
        return True

    def new_dir (self, path, hist = True):
        *dest, name = path
        dest = self.get_tree(dest)
        current_items = [k[0] for k in dest if k is not None]
        current_items += [name for name, i in dest[None]]
        if name in current_items:
            # already exists: show error
            error('Directory \'{}\' already exists.'.format(nice_path(path)),
                  self.editor)
            return False
        else:
            if hist:
                self._add_hist(('new', path))
            dest[(name, None)] = {None: []}
            return True


class Editor (gtk.Window):
    """The main application window.

Takes a gcutil.GCFS instance.

    METHODS

update_hist_btns
extract
write
quit

    ATTRIBUTES

fs: the given gcutil.GCFS instance.
fs_backend: FSBackend instance.
file_manager: fsmanage.Manager instance.
buttons: a list of the buttons on the left.

"""

    def __init__ (self, fs):
        self.fs = fs
        self.fs_backend = FSBackend(fs, self)
        ident = (IDENTIFIER, self.fs.fn, id(self))
        m = fsmanage.Manager(self.fs_backend, identifier = ident)
        self.file_manager = m
        # window
        gtk.Window.__init__(self)
        self.resize(350, 350)
        self.set_border_width(12)
        self.connect('delete-event', self.quit)
        # contents
        g = gtk.Grid()
        self.add(g)
        g.set_row_spacing(6)
        g.set_column_spacing(12)
        # left
        self.buttons = btns = []
        f = lambda widget, cb, *args: cb(*args)
        for btn_data in (
            (gtk.STOCK_UNDO, 'Undo the last change', self.fs_backend.undo),
            (gtk.STOCK_REDO, 'Redo the next change', self.fs_backend.redo),
            None,
            (('_Import Files', gtk.STOCK_HARDDISK),
             'Import files from outside', self.fs_backend.do_import, False),
            (('I_mport Folders', gtk.STOCK_HARDDISK),
             'Import folders from outside', self.fs_backend.do_import, True),
            (('_Extract', gtk.STOCK_EXECUTE), 'Extract the selected files',
             self.extract),
            (('_Write', gtk.STOCK_SAVE), 'Write changes to the disk image',
             self.write),
            (gtk.STOCK_QUIT, 'Quit the application', self.quit)
        ):
            if btn_data is None:
                for b in fsmanage.buttons(m):
                    btns.append(b)
            else:
                name, tooltip, cb, *cb_args = btn_data
                if not isinstance(name, str):
                    name, icon = name
                    b = gtk.Button(name, None, '_' in name)
                    # FIXME: 4 should be GTK_ICON_SIZE_BUTTON, but I can't find
                    # it
                    img = gtk.Image.new_from_stock(icon, gtk.IconSize.BUTTON)
                    b.set_image(img)
                elif name.startswith('gtk-'):
                    b = gtk.Button(None, name)
                else:
                    b = gtk.Button(name, None, '_' in name)
                btns.append(b)
                if tooltip is not None:
                     b.set_tooltip_text(tooltip)
                if cb is not None:
                    b.connect('clicked', f, cb, *cb_args)
        for i, b in enumerate(btns):
            g.attach(b, 0, i, 1, 1)
        # undo/redo insensitive
        for b in btns[:2]:
            b.set_sensitive(False)
        # right
        g_right = gtk.Grid()
        g.attach(g_right, 1, 0, 1, len(btns))
        g_right.set_row_spacing(6)
        address = fsmanage.AddressBar(m, root_icon = gtk.STOCK_CDROM)
        g_right.attach(address, 0, 0, 1, 1)
        s = gtk.ScrolledWindow()
        g_right.attach(s, 0, 1, 1, 1)
        s.set_policy(gtk.PolicyType.NEVER, gtk.PolicyType.AUTOMATIC)
        s.add(m)
        m.set_vexpand(True)
        m.set_hexpand(True)
        # shortcuts
        group = gtk.AccelGroup()
        accels = (
            ('<ctrl>z', self.fs_backend.undo),
            ('<ctrl><shift>z', self.fs_backend.redo),
            ('<ctrl>y', self.fs_backend.redo)
        )
        def mk_fn (cb, *cb_args):
            def f (*args):
                cb(*cb_args)
            return f
        for accel, cb, *args in accels:
            key, mods = gtk.accelerator_parse(accel)
            group.connect(key, mods, 0, mk_fn(cb, *args))
        self.add_accel_group(group)
        self.add_accel_group(self.file_manager.accel_group)
        # display
        self.show_all()
        m.grab_focus()

    def update_hist_btns (self):
        """Update undo/redo buttons' sensitivity."""
        self.buttons[0].set_sensitive(self.fs_backend.can_undo())
        self.buttons[1].set_sensitive(self.fs_backend.can_redo())

    def extract (self, *files):
        """Extract the files at the given paths, else the selected files."""
        if not files:
            path = self.file_manager.path
            files = self.file_manager.get_selected_files()
            files = [path + [name] for name in files]
            if not files:
                # nothing to do
                return
        # TODO:
        # - if one file, ask for a filename to save it under
        # - if >1, list them and ask for a dir to put them in
        # - display failed list

    def write (self):
        """Write changes to the disk."""
        write = True
        if not self.fs.changed():
            # no need to write
            write = False
        elif self.fs.disk_changed():
            # TODO: ask: write anyway / cancel
            write = False
        if write:
            # TODO: progress bar
            # TODO: ask to confirm - can't undo/all undo history lost
            try:
                self.fs.write()
            except Exception as e:
                if hasattr(e, 'handled') and e.handled is True:
                    # disk should still be in the same state
                    error('Couldn\'t write: {}.'.format(e.args[0]), self)
                else:
                    # not good: show traceback
                    msg = 'Something may have gone horribly wrong, and the ' \
                          'disk image might have ended up in an ' \
                          'inconsistent state.  Here\'s some debug ' \
                          'information:'
                    v = text_viewer(format_exc().strip(),
                                    gtk.WrapMode.WORD_CHAR)
                    error(msg, self, v)

    def quit (self, *args):
        """Quit the program."""
        # TODO: if have unsaved changes, confirm
        gtk.main_quit()