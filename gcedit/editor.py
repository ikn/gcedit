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
# - option to remember last import/extract path separately

# NOTE: os.stat().st_dev gives path's device ID

from gi.repository import Gtk as gtk
from .ext import fsmanage

IDENTIFIER = 'gcedit'


class FSBackend:
    """The backend for fsmanage, to make changes to the filesystem.

Takes a gcutil.GCFS instance and an Editor instance.

    METHODS

(as required by fsmanage.Manager)
get_tree
get_file
undo
redo

    ATTRIBUTES

fs, editor: the arguments given to the constructor.

"""

    def __init__ (self, fs, editor):
        self.fs = fs
        self.editor = editor

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

    def list_dir (self, path):
        try:
            tree = self.get_tree(path)
        except ValueError:
            # TODO: show doesn't exist dialogue
            items = []
        else:
            # dirs
            items = [(k[0], True) for k in tree if k is not None]
            # files
            items += [(name, False) for name, i in tree[None]]
        return items

    def open_files (self, *files):
        self.editor.extract(*files)

    def copy (self, *data, return_failed = False):
        failed = []
        cannot_copy = []
        for old, new in data:
            if old[0] is True:
                # from another Manager: check data is valid
                data, old = old[1:]
                if not isinstance(data, tuple) or len(data) != 3 or \
                   data[0] != IDENTIFIER:
                    continue
                if data[2] == id(self.editor):
                    # same Editor
                    print('same')
                    pass
                else:
                    print(data, old, new)
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
                    cannot_copy.append(old[-1])
                    continue
            this_failed = False
            while name in current_items:
                # exists: ask what action to take 
                print('failed:', k[0])
                failed.append(old)
                # TODO: show overwrite/don't copy/rename error dialogue
                this_failed = True ##
                break ##
                if overwrite:
                    self.delete(new)
                    current_items.remove(name)
                elif rename:
                    name = new_name
                    new = dest + [name]
                else:
                    this_failed = True
                    break
            if not this_failed:
                # copy
                if is_dir:
                    dest[(name, k[1])] = parent[k]
                else:
                    dest[None].append((new[-1], k[1]))
        if cannot_copy:
            # show error for files that couldn't be copied
            # TODO: show error dialogue
            print('couldn\'t copy:', cannot_copy)
        if return_failed:
            return failed
        else:
            return len(failed) != len(data)

    def move (self, *data):
        failed = self.copy(*data, return_failed = True)
        if len(failed) != len(data):
            self.delete(*(old for old, new in data if old not in failed))
            return True
        else:
            return False

    def delete (self, *files):
        for f in files:
            try:
                # dir
                parent, k = self.get_tree(f, True)
                del parent[k]
            except ValueError:
                # file
                parent, entry = self.get_file(f)
                parent[None].remove(entry)
        return True

    def new_dir (self, path):
        *dest, name = path
        dest = self.get_tree(dest)
        current_items = [k[0] for k in dest if k is not None]
        current_items += [name for name, i in dest[None]]
        if name in current_items:
            # TODO: show error dialogue
            print('exists:', name)
            return False
        else:
            dest[(name, None)] = {None: []}
            return True


class Editor (gtk.Window):
    """The main application window.

Takes a gcutil.GCFS instance.

    METHODS

extract
quit

    ATTRIBUTES

fs: the given gcutil.GCFS instance.
fs_backend: FSBackend instance.
file_manager: fsmanage.Manager instance.

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
        btns = []
        f = lambda widget, cb, *args: cb(*args)
        for btn_data in (
            (gtk.STOCK_UNDO, 'Undo the last change', None),
            (gtk.STOCK_REDO, 'Redo the next change', None),
            None,
            (('_Extract', gtk.STOCK_EXECUTE), 'Extract the selected files',
             self.extract),
            (('_Write', gtk.STOCK_SAVE), 'Write changes to the disk image',
             self.fs.write),
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
                    b.set_image(gtk.Image.new_from_stock(icon, 4))
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
        self.add_accel_group(self.file_manager.accel_group)
        # display
        self.show_all()
        address.update()
        m.grab_focus()

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

    def quit (self, *args):
        """Quit the program."""
        # TODO: if have unsaved changes, confirm
        gtk.main_quit()