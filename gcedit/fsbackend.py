"""gcedit filesystem manager backend module.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

    CLASSES

FSBackend

"""

# TODO:
# [ENH] 'do this for all remaining conflicts' for move_conflict
# [ENH] in overwrite with copy/import, have the deletion in the same history action
#   - history action can be list of actions
#   - need to add copies/imports and deletes to this list in the right order

import os
from copy import deepcopy
from html import escape

from gi.repository import Gtk as gtk
from .ext import gcutil

from . import guiutil
from . import conf
from .conf import settings


class FSBackend:
    """The backend for fsmanage, to make changes to the filesystem.

Takes a gcutil.GCFS instance and an Editor instance.

    METHODS

reset
get_tree
get_file
undo
redo
can_undo
can_redo
do_import
[those required by fsmanage.Manager]

    ATTRIBUTES

fs, editor: the arguments given to the constructor.

"""

    def __init__ (self, fs, editor):
        self.fs = fs
        self.editor = editor
        self._hist_pos = 0
        self._hist = []
        self._sizes = {}
        self._update_sizes()

    def reset (self):
        """Forget all history."""
        self._hist_pos = 0
        self._hist = []
        self.editor.hist_update()
        self._sizes = {}
        self._update_sizes()

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
                return (parent, k)
            except NameError:
                # never found any, but didn't raise an exception: this is root
                return (tree, None)
        else:
            return tree

    def get_file (self, path):
        """Get the file at the given path in the tree.

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

    def _get_size (self, is_dir, path):
        """Get the total filesize of a path.

_get_size(is_dir, path) -> size

"""
        if is_dir:
            key = self.get_tree(path, True)[1]
        else:
            key = self.get_file(path)[1]
        return self._sizes[path[0]][key]

    def _update_sizes (self, *paths):
        """Add sizes to the cache for the given paths.

If no paths are given, update all sizes.

"""
        if paths:
            paths = {path[0] for path in paths}
        else:
            # get all toplevel paths
            paths = gcutil.tree_names(self.fs.tree)
        # update sizes for toplevel parents of paths
        for name in paths:
            path = (name,)
            try:
                parent, key = self.get_tree(path, True)
            except ValueError:
                try:
                    key = self.get_file(path)[1]
                    tree = {None: [key]}
                except ValueError:
                    continue
                else:
                    sizes = self.fs.tree_size(tree, True, True)
                    sizes = {key: sizes[key]}
            else:
                sizes = self.fs.tree_size(parent[key], True, True, key)
            self._sizes[name] = sizes

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
                self._update_sizes(*(x[0] for x in data))
        elif action == 'new':
            self.delete(data, hist = False)
        else: # import
            self.delete(*(path for path, f in data), hist = False)
        self.editor.file_manager.refresh()
        self.editor.hist_update()

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
            self._update_sizes(*(path for path, f in data))
        self.editor.file_manager.refresh()
        self.editor.hist_update()

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
        self.editor.hist_update()

    def _validate_tree (self, tree, src, dest):
        """Clean up a tree, fixing invalid names."""
        names = {}
        for k in tree:
            if k is not None:
                names[k[0]] = (True, k)
        for k in tree[None]:
            names[k[0]] = (False, k)
        # check each item
        to_check = list(names.keys())
        while to_check:
            name = to_check.pop(0)
            is_dir, k = names[name]
            want_name = name
            this_src = os.path.join(src, name)
            while True:
                this_dest = dest + [want_name]
                p_dest = guiutil.printable_path(this_dest)
                if want_name != name:
                    # want to rename
                    if want_name in names:
                        # target exists
                        action = guiutil.move_conflict(this_src, p_dest,
                                                       self.editor)
                    else:
                        # allow rename
                        action = None
                elif guiutil.invalid_name(name):
                    # invalid name
                    action = guiutil.move_conflict(this_src, p_dest,
                                                   self.editor, True)
                else:
                    break
                if action is True:
                    # overwrite: remove target
                    target_is_dir, target_k = names[want_name]
                    if target_is_dir:
                        del tree[target_k]
                    else:
                        tree[None].remove(target_k)
                    del names[want_name]
                    if want_name in to_check:
                        to_check.remove(want_name)
                    # rename
                    action = None
                if action:
                    # request rename
                    want_name = action
                elif action is None:
                    # rename
                    del names[name]
                    name = want_name
                    new_k = (name, k[1])
                    names[name] = new_k
                    if is_dir:
                        data = tree[k]
                        del tree[k]
                        tree[new_k] = data
                    else:
                        tree[None][tree[None].index(k)] = new_k
                    k = new_k
                else: # action is False
                    # don't copy
                    if is_dir:
                        del tree[k]
                    else:
                        tree[None].remove(k)
                    del names[name]
                    break
            # validate subdirs (but might have been removed from tree)
            if is_dir and k in tree:
                self._validate_tree(tree[k], this_src, this_dest)

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
        if dirs:
            # NOTE: the title for a file open dialogue
            title = _('Choose Directories')
        else:
            # NOTE: the title for a file open dialogue
            title = _('Choose Files')
        d = gtk.FileChooserDialog(title, self.editor, action, buttons)
        d.set_current_folder(settings['import_path'])
        d.set_select_multiple(True)
        response = d.run()
        fs = d.get_filenames()
        import_path = d.get_current_folder()
        d.destroy()
        if response == rt.OK:
            # remember dir
            settings['import_path'] = import_path
            # import
            current_path = self.editor.file_manager.path
            try:
                current = self.get_tree(current_path)
            except ValueError:
                d.destroy()
                guiutil.error(_('Can\'t import to a non-existent directory.'))
                return
            current_names = gcutil.tree_names(current)
            new = []
            new_names = []
            for f in fs:
                name = os.path.basename(f)
                failed = False
                # check if exists
                while True:
                    dest = guiutil.printable_path(current_path + [name])
                    if name in current_names:
                        # exists
                        action = guiutil.move_conflict(name, dest, self.editor)
                    elif guiutil.invalid_name(name):
                        action = guiutil.move_conflict(name, dest, self.editor,
                                                       True)
                    else:
                        break
                    # handle action
                    if action is True:
                        self.delete(current_path + [name])
                        current_names.remove(name)
                    elif action:
                        name = action
                    else:
                        failed = True
                        break
                if not failed:
                    # add to tree
                    if dirs:
                        tree = gcutil.tree_from_dir(f)
                        self._validate_tree(tree, f, current_path + [name])
                        current[(name, None)] = f = tree
                    else:
                        current[None].append((name, f))
                    new.append((current_path + [name], f))
                    new_names.append(name)
                    current_names.append(name)
            if new:
                self._update_sizes(*(path for path, tree in new))
                self.editor.file_manager.refresh(*new_names)
                self._add_hist(('import', new))

    def list_dir (self, path):
        path = tuple(path)
        try:
            tree = self.get_tree(path)
        except ValueError:
            # doesn't exist: show error
            guiutil.error(_('Directory doesn\'t exist.'), self.editor)
            items = []
        else:
            size = self._get_size
            niceify = guiutil.printable_filesize
            items = []
            for k, v in tree.items():
                if k is None:
                    # files
                    for name, i in v:
                        this_size = niceify(size(False, path + (name,)))
                        items.append((name, False, this_size, escape(name)))
                else:
                    # dir
                    name = k[0]
                    this_size = niceify(size(True, path + (name,)))
                    items.append((name, True, this_size, escape(name)))
        return items

    def open_files (self, *files):
        self.editor.extract(*(f[0] for f in files))

    def copy (self, *data, return_failed = False, hist = True,
              update_sizes = True):
        failed = []
        cannot_copy = []
        said_nodest = False
        for old, new in data:
            foreign = False
            if old[0] is True:
                # from another Manager: check data is valid
                this_data, old = old[1:]
                if not isinstance(this_data, tuple) or len(this_data) != 3 or \
                   this_data[0] != conf.IDENTIFIER:
                    failed.append(old)
                    continue
                if this_data[2] != id(self.editor):
                    # different Editor
                    foreign = True
                    guiutil.error(_('Drag-and-drop between instances is not '
                                    'supported yet.'))
                    #print(this_data, old, new)
                    failed.append(old)
                    continue
            # get destination
            try:
                dest = self.get_tree(new[:-1])
            except ValueError:
                if not said_nodest:
                    guiutil.error(_('Can\'t copy to a non-existent '
                                    'directory.'))
                    said_nodest = True
                failed.append(old)
                cannot_copy.append(guiutil.printable_path(old))
                continue
            current_items = [k[0] for k in dest if k is not None]
            current_items += [name for name, i in dest[None]]
            is_dir = True
            # get source
            try:
                # try to get dir
                parent, (old[-1], index) = self.get_tree(old, True)
            except ValueError:
                # file instead
                is_dir = False
                try:
                    parent, (old[-1], index) = self.get_file(old)
                except ValueError:
                    # been deleted or something
                    failed.append(old)
                    cannot_copy.append(guiutil.printable_path(old))
                    continue
            this_failed = False
            while True:
                p_new = guiutil.printable_path(new)
                if new[-1] in current_items:
                    # exists
                    action = guiutil.move_conflict(old[-1], p_new, self.editor)
                elif guiutil.invalid_name(new[-1]):
                    action = guiutil.move_conflict(old[-1], p_new, self.editor,
                                                   True)
                else:
                    break
                # handle action
                if action is True:
                    if old == new:
                        # same file: do nothing
                        break
                    else:
                        self.delete(new)
                        current_items.remove(new[-1])
                elif action:
                    new[-1] = action
                else:
                    this_failed = True
                    break
            if this_failed:
                failed.append(old)
            elif old != new:
                # copy
                if is_dir:
                    # copy tree so they can be modified independently
                    dest[(new[-1], index)] = deepcopy(parent[(old[-1], index)])
                else:
                    dest[None].append((new[-1], index))
        if cannot_copy:
            # show error for files that couldn't be copied
            v = guiutil.text_viewer('\n'.join(cannot_copy), gtk.WrapMode.NONE)
            guiutil.error(_('Couldn\'t copy some items:'), self.editor, v)
        # add to history
        succeeded = [x for x in data if x[0] not in failed and x[0] != x[1]]
        if succeeded:
            if update_sizes:
                self._update_sizes(*(new for old, new in succeeded))
            if hist:
                self._add_hist(('copy', succeeded))
        if return_failed:
            return failed
        else:
            return len(failed) != len(data)

    def move (self, *data, hist = True, update_sizes = True):
        failed = self.copy(*data, return_failed = True, hist = False,
                           update_sizes = False)
        if len(failed) != len(data):
            succeeded = [x for x in data if x[0] not in failed]
            if succeeded:
                self.delete(*(old for old, new in succeeded), hist = False,
                            update_sizes = False)
                # add to history
                if update_sizes:
                    self._update_sizes(*sum((tuple(x) for x in succeeded), ()))
                if hist:
                    self._add_hist(('move', succeeded))
            return True
        else:
            return False

    def delete (self, *files, hist = True, update_sizes = True):
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
        if done:
            if update_sizes:
                self._update_sizes(*(x[0] for x in done))
            if hist:
                self._add_hist(('delete', done))
        return True

    def new_dir (self, path, hist = True, update_sizes = True):
        *dest, name = path
        try:
            dest = self.get_tree(dest)
        except ValueError:
            guiutil.error(_('Can\'t create a directory in a non-existent '
                            'directory.'))
            return False
        current_items = [k[0] for k in dest if k is not None]
        current_items += [name for name, i in dest[None]]
        if name in current_items:
            # already exists: show error
            path = guiutil.printable_path(path)
            msg = _('Directory \'{}\' already exists.')
            guiutil.error(msg.format(path, self.editor))
            return False
        elif guiutil.invalid_name(name):
            guiutil.invalid_name_dialogue((guiutil.printable_path(path),),
                                          self.editor)
            return False
        else:
            dest[(name, None)] = {None: []}
            if update_sizes:
                self._update_sizes(path)
            if hist:
                self._add_hist(('new', path))
            return True
