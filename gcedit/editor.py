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
# - on import dir, can rename two invalid-named files to same name
# - 'do this for all remaining conflicts' for move_conflict
# - dialogues should use primary text (brief summary - have no title)
# - breadcrumbs shrink if reduce size to < 10px above minimum
# - in overwrite with copy/import, have the deletion in the same history action
#   - history action can be list of actions
#   - need to add copies/imports and deletes to this list in the right order
# - remember last import/extract paths (separately)
# - can search within filesystem (ctrl-f, edit/find and ctrl-g, edit/find again)
# - menus:
#   - switch disk image (go back to initial screen)
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
# - display file size
# - instead of progress disappearing, give it a finish() method which replaces buttons with a 'Close' button, allows closing by esc/etc., sets default response to Close (if error, destroy dialogue instead of calling this)

# NOTE: os.stat().st_dev gives path's device ID

import os
from time import sleep
from traceback import format_exc
from html import escape
from math import log10
try:
    from threading import Thread
except ImportError:
    from dummy_threading import Thread
from queue import Queue

from gi.repository import Gtk as gtk, Gdk as gdk, Pango as pango
from .ext import fsmanage
from .ext.gcutil import tree_from_dir, valid_name

IDENTIFIER = 'gcedit'
INVALID_FN_CHARS = ({b'/'}, {'/'})
SLEEP_INTERVAL = .02

def printable_path (path):
    """Get a printable version of a list-style path."""
    return '/' + '/'.join(path)

def printable_filesize (size):
    """Get a printable version of a filesize in bytes."""
    for factor, suffix in (
        (0, ''),
        (1, 'Ki'),
        (2, 'Mi'),
        (3, 'Gi'),
        (4, 'Ti')
    ):
        if size < 1024 ** (factor + 1):
            break
    size /= (1024 ** factor)
    # 3 significant figures but always show up to units
    dp = max(2 - int(log10(max(size, 1))), 0)
    return ('{:.' + str(dp) + 'f}{}B').format(size, suffix)

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

def question (title, msg, options, parent = None, default = None,
              warning = False, return_dialogue = False):
    """Show a dialogue asking a question.

question(title, msg, options[, parent][, default], warning = False,
         return_dialogue = False) -> response

title: dialogue title text.
msg: text to display.
options: a list of options to present as buttons, where each is the button text
         or a stock ID.
parent: dialogue parent.
default: the index of the option in the list that should be selected by default
         (pressing enter normally).
warning: whether this is a warning dialogue (instead of just a question).
return_dialogue: whether to return the created dialogue instead of running it.

response: The index of the clicked button in the list, or a number less than 0
          if the dialogue was closed.

"""
    # TODO: option to show 'don't ask again' checkbox; return its value too
    mt = gtk.MessageType.WARNING if warning else gtk.MessageType.QUESTION
    d = gtk.MessageDialog(parent, gtk.DialogFlags.DESTROY_WITH_PARENT,
                          mt, gtk.ButtonsType.NONE, msg)
    d.add_buttons(*(sum(((o, i) for i, o in enumerate(options)), ())))
    d.set_title(title)
    # FIXME: sets default to 0 if we don't set it here
    if default is not None:
        d.set_default_response(default)
    if return_dialogue:
        return d
    else:
        response = d.run()
        d.destroy()
        return response

def error (msg, parent = None, *widgets):
    """Show an error dialogue.

error(msg, parent = None, *widgets)

msg: text to display.
parent: dialogue parent.
widgets: widgets to add to the same grid as the text, which is at (0, 0) with
         size (1, 1).  A widget can be (widget, x, y, w, h) to determine its
         position; otherwise, it is placed the first free cell in column 0 once
         all widgets with given positions have been placed.
         widget.show() is called.

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
    d.set_border_width(6)
    # grid
    g = gtk.Grid()
    d.get_content_area().pack_start(g, True, True, 0)
    g.set_border_width(6)
    g.set_property('margin-bottom', 12)
    g.set_column_spacing(12)
    g.set_row_spacing(12)
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

def move_conflict (fn_from, f_to, parent = None, invalid = False):
    """Show a dialogue that handles a conflict in moving a file.

move_conflict(fn_from, fn_to[, parent], invalid = False) -> action

fn_from: the filename to move from.
f_to: the full file path to move to (in a printable format).
parent: dialogue parent.
invalid: whether the problem is that the destination is invalid (as opposed to
         the destination existing).

action: True to overwrite (not for an invalid name), False to cancel the move,
        or a string to move to that name instead.

"""
    # get dialogue
    msg = 'The file \'{}\' cannot be moved to \'{}\' because {}.'
    reason = 'the destination name is invalid' if invalid else \
             'the destination file exists'
    msg = msg.format(fn_from, f_to, reason)
    buttons = ['_Rename', gtk.STOCK_CANCEL]
    if not invalid:
        buttons.append('_Overwrite')
    d = question('Filename Conflict', msg, buttons, parent, 1, warning = True,
                 return_dialogue = True)
    # rename button sensitivity
    d.set_response_sensitive(0, False)
    def set_sensitive (e, *args):
        renaming = e.get_text()
        d.set_response_sensitive(0, renaming)
        d.set_default_response(0 if renaming else 1)
        e.set_activates_default(renaming)
    # make message left-aligned
    msg_area = d.get_message_area()
    msg_area.get_children()[0].set_alignment(0, .5)
    # add error message
    err = gtk.Label('<i>Error: invalid filename.</i>')
    err.set_use_markup(True)
    err.set_alignment(0, .5)
    msg_area.pack_start(err, False, False, 0)
    # add entry
    h = gtk.Box(gtk.Orientation.HORIZONTAL, 6)
    msg_area.pack_start(h, False, False, 0)
    h.pack_start(gtk.Label('New name:'), False, False, 0)
    e = gtk.Entry()
    h.pack_start(e, False, False, 0)
    e.connect('changed', set_sensitive)
    h.show_all()
    if invalid:
        # add invalid name details
        details = _invalid_name_details_expander()
        msg_area.pack_start(details, False, False, 0)
        details.show()
    # run
    while True:
        response = d.run()
        if response == 2:
            action = True
        elif response == 0:
            action = e.get_text()
            if INVALID_FN_CHARS[isinstance(action, str)].intersection(action):
                e.grab_focus()
                err.show()
                continue
        else:
            action = False
        break
    d.destroy() # need to do this after we retrieve entry's text
    return action

def _invalid_name_details_expander ():
    """Get a Gtk.Expander with invalid name details."""
    e = gtk.Expander()
    e.set_label('_Details')
    e.set_use_underline(True)
    l = gtk.Label('It must be possible to encode file and directory names ' \
                  'using the shift-JIS encoding, and \'/\' and null bytes ' \
                  '(\'\\0\') are not allowed.')
    e.add(l)
    l.set_line_wrap(True)
    l.show()
    return e

def invalid_name_dialogue (paths, parent = None):
    """Show an error dialogue for trying to create files with invalid names.

invalid_name_dialogue(paths[, parent])

paths: a list of the invalid paths (in printable form).
parent: dialogue parent.

"""
    widgets = []
    if len(paths) == 1:
        msg = 'Couldn\'t create \'{}\' because its name is invalid.'
        msg = msg.format(paths)
    else:
        msg = 'The following items couldn\'t be created because their names ' \
              'are invalid:'
        widgets.append(text_viewer('\n'.join(paths), gtk.WrapMode.NONE))
    # details
    e = _invalid_name_details_expander()
    widgets.append(e)
    error(msg, parent, *widgets)

def invalid_name (name):
    """Check if a filename is valid."""
    if INVALID_FN_CHARS[isinstance(name, str)].intersection(name):
        return False
    else:
        return not valid_name(name)


class Progress (gtk.Dialog):
    """Show a progress dialogue.  Subclass of Gtk.Dialog.

Act directly on the bar attribute to control the progress bar itself.

    CONSTRUCTOR

Progress(title[, cancel][, pause][, parent])

title: dialogue title.
cancel: response for the cancel button (else don't show a cancel button).
pause: response for the pause button (else don't show a pause button).
parent: parent widget.

    METHODS

set_item

    ATTRIBUTES

bar: Gtk.ProgressBar instance.
item: current item that's being processed, or None.

"""
    def __init__ (self, title, cancel = None, pause = None, parent = None):
        self.item = None
        # create dialogue
        flags = gtk.DialogFlags.MODAL | gtk.DialogFlags.DESTROY_WITH_PARENT
        buttons = []
        if cancel is not None:
            buttons += [gtk.STOCK_CANCEL, cancel]
        if pause is not None:
            buttons += ['_Pause', pause]
        gtk.Dialog.__init__(self, title, parent, flags, buttons)
        if pause is not None:
            self.set_default_response(pause)
        # some properties
        self.set_border_width(12)
        self.set_default_size(400, 0)
        self.set_deletable(False)
        self.connect('delete-event', lambda *args: True)
        # add widgets
        v = self.vbox
        v.set_spacing(6)
        head = escape(title)
        head = '<span weight="bold" size="larger">{}\n</span>'.format(head)
        head = gtk.Label(head)
        head.set_use_markup(True)
        head.set_alignment(0, .5)
        v.pack_start(head, False, False, 0)
        self.bar = gtk.ProgressBar()
        v.pack_start(self.bar, False, False, 0)
        self.bar.set_show_text(True)
        self._item = i = gtk.Label()
        i.set_alignment(0, .5)
        i.set_ellipsize(pango.EllipsizeMode.END) # to avoid dialogue resizing
        i.show()
        v.show_all()

    def set_item (self, item = None):
        """Set the text that displays the current item being progressed.

If no argument is given, the current item text is removed from the dialogue.

"""
        if item is None:
            if self.item is not None:
                self.vbox.remove(self._item)
        else:
            self._item.set_text('<i>{}</i>'.format(escape(item)))
            # for some reason we have to do this every time we set the text
            self._item.set_use_markup(True)
            if self.item is None:
                self.vbox.pack_start(self._item, False, False, 0)
        self.item = item


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

    def reset (self):
        """Forget all history."""
        self._hist_pos = 0
        self._hist = []
        self.editor.update_hist_btns()

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
        response = d.run()
        fs = d.get_filenames()
        d.destroy()
        if response == rt.OK:
            # import
            current_path = self.editor.file_manager.path
            try:
                current = self.get_tree(current_path)
            except ValueError:
                d.destroy()
                error('Can\'t import to a non-existent directory.')
                return
            current_names = [name for name, i in current[None]]
            current_names += [x[0] for x in current if x is not None]
            new = []
            new_names = []
            for f in fs:
                name = os.path.basename(f)
                failed = False
                # check if exists
                while True:
                    dest = printable_path(current_path + [name])
                    if name in current_names:
                        # exists
                        action = move_conflict(name, dest, self.editor)
                    elif invalid_name(name):
                        action = move_conflict(name, dest, self.editor, True)
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
                        tree = tree_from_dir(f)
                        # check contained items' names' validity
                        items = self.editor.fs.get_file_tree_locations(tree)
                        for (this_name, fn), parent, k in items:
                            while invalid_name(this_name):
                                action = move_conflict(fn, this_name,
                                                       self.editor, True)
                                if action:
                                    this_name = action
                                    parent[None][k] = (this_name, fn)
                                else:
                                    break
                        current[(name, None)] = f = tree
                    else:
                        current[None].append((name, f))
                    new.append((current_path + [name], f))
                    new_names.append(name)
                    current_names.append(name)
            if new:
                self.editor.file_manager.refresh(*new_names)
                self._add_hist(('import', new))

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
        said_nodest = False
        for old, new in data:
            foreign = False
            if old[0] is True:
                # from another Manager: check data is valid
                this_data, old = old[1:]
                if not isinstance(this_data, tuple) or len(this_data) != 3 or \
                   this_data[0] != IDENTIFIER:
                    continue
                if this_data[2] != id(self.editor):
                    # different Editor
                    foreign = True
                    error('Drag-and-drop between instances is not supported ' \
                          'yet.')
                    print(this_data, old, new)
                    continue
            # get destination
            try:
                dest = self.get_tree(new[:-1])
            except ValueError:
                if not said_nodest:
                    error('Can\'t copy to a non-existent directory.')
                    said_nodest = True
                failed.append(old)
                cannot_copy.append(printable_path(old))
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
                    cannot_copy.append(printable_path(old))
                    continue
            this_failed = False
            while True:
                if new[-1] in current_items:
                    # exists
                    # same dir means rename or same file, so skip (rename will go
                    # back to renaming on fail)
                    if old[:-1] == new[:-1] and not foreign:
                        this_failed = True
                        break
                    else:
                        action = move_conflict(old[-1], printable_path(new),
                                               self.editor)
                elif invalid_name(new[-1]):
                    action = move_conflict(old[-1], printable_path(new),
                                           self.editor, True)
                else:
                    break
                # handle action
                if action is True:
                    self.delete(new)
                    current_items.remove(new[-1])
                elif action:
                    new[-1] = action
                else:
                    this_failed = True
                    break
            if this_failed:
                failed.append(old)
            else:
                # copy
                if is_dir:
                    dest[(new[-1], index)] = parent[(old[-1], index)]
                else:
                    dest[None].append((new[-1], index))
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
        try:
            dest = self.get_tree(dest)
        except ValueError:
            error('Can\'t create a directory in a non-existent directory.')
            return False
        current_items = [k[0] for k in dest if k is not None]
        current_items += [name for name, i in dest[None]]
        if name in current_items:
            # already exists: show error
            path = printable_path(path)
            error('Directory \'{}\' already exists.'.format(path, self.editor))
            return False
        elif invalid_name(name):
            invalid_name_dialogue((printable_path(path),), self.editor)
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
        self.set_title('GCEdit') # TODO: include game name (need BNR support) [http://developer.gnome.org/hig-book/stable/windows-primary.html.en#primary-window-titles]
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
        # automatically computed button focus order is weird
        g.set_focus_chain(btns + [g_right])
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

    def _extract (self, q, files):
        """Extract files from the disk."""
        progress = lambda *args: q.put((False, args))
        failed = self.fs.extract(*files, progress = progress)
        q.put((True, failed))

    def extract (self, *files):
        """Extract the files at the given paths, else the selected files."""
        if not files:
            # get selected files
            files = self.file_manager.get_selected_files()
            if not files:
                # nothing to do
                msg = 'No files selected: to extract, select some files first.'
                error(msg, self)
                return
            path = self.file_manager.path
            files = [path + [name] for name in files]
        # get destination(s)
        rt = gtk.ResponseType
        if len(files) == 1:
            # ask for filename to extract to
            label = 'Choose where to extract to'
            action = gtk.FileChooserAction.SAVE
        else:
            # ask for directory to extract all files to
            label = 'Choose a directory to extract all items to'
            action = gtk.FileChooserAction.SELECT_FOLDER
        buttons = (gtk.STOCK_CLOSE, rt.CLOSE, gtk.STOCK_OK, rt.OK)
        d = gtk.FileChooserDialog(label, self, action, buttons)
        if d.run() != rt.OK:
            d.destroy()
            return
        dest = d.get_filename()
        d.destroy()
        if len(files) == 1:
            dests = [dest]
        else:
            dests = [os.path.join(dest, f[-1]) for f in files]
        # get dirs' trees and files' entries indices
        args = []
        for f, d in zip(files, dests):
            try:
                f = self.fs_backend.get_tree(f)
            except ValueError:
                f = self.fs_backend.get_file(f)[1][1]
            args.append((f, d))
        # show progress dialogue
        d = Progress('Extracting files', parent = self)
        d.show()
        # start write in another thread
        q = Queue()
        t = Thread(target = self._extract, args = (q, args))
        t.start()
        while True:
            while q.empty():
                while gtk.events_pending():
                    gtk.main_iteration()
                sleep(SLEEP_INTERVAL)
            finished, data = q.get()
            if finished:
                # finished
                failed = data
                break
            else:
                # update progress bar
                done, total, name = data
                d.bar.set_fraction(done / total)
                done = printable_filesize(done)
                total = printable_filesize(total)
                d.bar.set_text('Completed {} of {}'.format(done, total))
                d.set_item('Extracting file: ' + name)
        t.join()
        d.destroy()
        # display failed list
        if failed:
            v = text_viewer('\n'.join(dest for f, dest in failed),
                            gtk.WrapMode.NONE)
            msg = 'Couldn\'t extract to the following locations.  Maybe the ' \
                  'files already exist, or you don\'t have permission to ' \
                  'write here.'
            error(msg, self, v)

    def _write (self, q):
        """Perform a write."""
        try:
            self.fs.write(progress = lambda *args: q.put(args))
        except Exception as e:
            if hasattr(e, 'handled') and e.handled is True:
                # disk should still be in the same state
                q.put(('Couldn\'t write: {}.'.format(e.args[0]), None))
            else:
                # not good: show traceback
                msg = 'Something may have gone horribly wrong, and the ' \
                        'disk image might have ended up in an ' \
                        'inconsistent state.  Here\'s some debug ' \
                        'information.'
                q.put((msg, format_exc().strip()))
        else:
            q.put((None, None))

    def write (self):
        """Write changes to the disk."""
        confirm_buttons = (gtk.STOCK_CANCEL, '_Write Anyway')
        if not self.fs.changed():
            # no need to write
            return
        elif self.fs.disk_changed():
            msg = 'The contents of the disk have been changed by another ' \
                  'program since it was loaded.  Are you sure you want to ' \
                  'continue?'
            if question('Confirm Write', msg, confirm_buttons, self,
                        warning = True) != 1:
                return
        # ask for confirmation
        msg = 'Once your changes have been written to the disk, they ' \
                'cannot be undone.  Are you sure you want to continue?'
        if question('Confirm Write', msg, confirm_buttons, self,
                    warning = True) != 1:
            return
        # show progress dialogue
        d = Progress('Writing to disk', parent = self)
        d.show()
        # start write in another thread
        q = Queue()
        t = Thread(target = self._write, args = (q,))
        t.start()
        while True:
            while q.empty():
                while gtk.events_pending():
                    gtk.main_iteration()
                sleep(SLEEP_INTERVAL)
            got = q.get()
            if len(got) == 3:
                # update progress bar
                done, total, name = got
                d.bar.set_fraction(done / total)
                done = printable_filesize(done)
                total = printable_filesize(total)
                d.bar.set_text('Completed {} of {}'.format(done, total))
                d.set_item('Copying file: ' + name)
            else:
                # finished
                msg, traceback = got
                break
        t.join()
        d.destroy()
        if msg is None:
            # tree is different, so have to get rid of history
            self.fs_backend.reset()
            self.file_manager.refresh()
        else:
            # show error
            if traceback is None:
                error(msg, self)
                refresh = False
            else:
                v = text_viewer(traceback, gtk.WrapMode.WORD_CHAR)
                error(msg, self, v)
                # don't try and do anything else, in case it breaks things

    def quit (self, *args):
        """Quit the program."""
        if not self.get_sensitive():
            # doing stuff
            return True
        if self.fs_backend.can_undo() or self.fs_backend.can_redo():
            # confirm
            msg = 'The changes you\'ve made will be lost if you quit.  Are ' \
                  'you sure you want to continue?'
            if question('Confirm Quit', msg,
                        (gtk.STOCK_CANCEL, '_Quit Anyway'), self,
                        warning = True) != 1:
                return True
        gtk.main_quit()