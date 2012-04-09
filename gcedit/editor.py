"""gcedit editor module.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

    CLASSES

Editor

"""

# TODO:
# [BUG] on import dir, can rename two invalid-named files to same name
# [ENH] icon
# [ENH] 'do this for all remaining conflicts' for move_conflict
# [ENH] dialogues should use primary text (brief summary - have no title)
# [ENH] in overwrite with copy/import, have the deletion in the same history action
#   - history action can be list of actions
#   - need to add copies/imports and deletes to this list in the right order
# [ENH] remember last import/extract paths (separately)
# [FEA] can search within filesystem (ctrl-f, edit/find; shows bar with entry and Next/Previous buttons)
# [FEA] menus:
#   - switch disk image (go back to initial screen)
#   - buttons
#   - compress, decompress, discard all changes (fs.update(), manager.refresh()), reload from disk (fs.update())
#   - split view (horiz/vert/close)
#   - about
# [FEA] built-in tabbed editor (expands window out to the right)
#   - if rename/move a file being edited, rename the tab
#   - if delete, show error
#   - if write, ask if want to save files being edited; afterwards, 're-open' them and show error if can't for some reason
#   - in context menu, buttons
#   - on open, check if can decode to text; if not, have hex editor
#   - option for open_files to edit instead of extract
# [FEA] track deleted files (not dirs) (get paths recursively) and put in trash when write
# [FEA] display file size

# NOTE: os.stat().st_dev gives path's device ID

import os
from time import sleep
from traceback import format_exc
try:
    from threading import Thread
except ImportError:
    from dummy_threading import Thread
from queue import Queue

from gi.repository import Gtk as gtk, Gdk as gdk
from .ext import fsmanage

from .fsbackend import FSBackend
from .prefs import Preferences
from . import guiutil
from . import conf
from .conf import settings

IDENTIFIER = 'gcedit'


class Editor (gtk.Window):
    """The main application window.

Takes a gcutil.GCFS instance.

    METHODS

update_hist_btns
extract
write
open_prefs
quit

    ATTRIBUTES

fs: the given gcutil.GCFS instance.
fs_backend: FSBackend instance.
file_manager: fsmanage.Manager instance.
buttons: a list of the buttons on the left.
prefs: preferences window or None

"""

    def __init__ (self, fs):
        #print(conf.gen_widgets(self))
        self.fs = fs
        self.fs_backend = FSBackend(fs, self)
        ident = (conf.IDENTIFIER, self.fs.fn, id(self))
        m = fsmanage.Manager(self.fs_backend, identifier = ident,
                             drag_to_select = settings['sel_on_drag'])
        self.file_manager = m
        # window
        gtk.Window.__init__(self)
        w, h = settings['win_size'][:2]
        self.set_default_size(w, h)
        if settings['win_max']:
            self.maximize()
        self.set_border_width(12)
        # TODO: [ENH] include game name (need BNR support) [http://developer.gnome.org/hig-book/stable/windows-primary.html.en#primary-window-titles]
        self.set_title(conf.APPLICATION)
        self.connect('delete-event', self.quit)
        self.connect('size-allocate', self._size_cb)
        self.connect('window-state-event', self._state_cb)
        # contents
        g = gtk.Grid()
        self.add(g)
        g.set_row_spacing(6)
        g.set_column_spacing(12)
        # left
        self.prefs = None
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
            (gtk.STOCK_PREFERENCES, 'Open the preferences window',
             self.open_prefs),
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

    def _state_cb (self, w, e):
        """Save changes to maximised state."""
        is_max = e.new_window_state & gdk.WindowState.MAXIMIZED
        settings['win_max'] = bool(is_max)

    def _size_cb (self, w, size):
        """Save changes to window size."""
        if not settings['win_max']:
            settings['win_size'] = (size.width, size.height)

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
                guiutil.error(msg, self)
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
        if len(files) == 1:
            # set name to that in the disk
            d.set_current_name(files[0][-1])
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
        d = guiutil.Progress('Extracting files', parent = self)
        d.show()
        # start write in another thread
        q = Queue()
        t = Thread(target = self._extract, args = (q, args))
        t.start()
        while True:
            while q.empty():
                while gtk.events_pending():
                    gtk.main_iteration()
                sleep(conf.SLEEP_INTERVAL)
            finished, data = q.get()
            if finished:
                # finished
                failed = data
                break
            else:
                # update progress bar
                done, total, name = data
                d.bar.set_fraction(done / total)
                done = guiutil.printable_filesize(done)
                total = guiutil.printable_filesize(total)
                d.bar.set_text('Completed {} of {}'.format(done, total))
                d.set_item('Extracting file: ' + name)
        t.join()
        if failed:
            d.destroy()
            # display failed list
            v = guiutil.text_viewer('\n'.join(dest for f, dest in failed),
                                    gtk.WrapMode.NONE)
            msg = 'Couldn\'t extract to the following locations.  Maybe the ' \
                  'files already exist, or you don\'t have permission to ' \
                  'write here.'
            guiutil.error(msg, self, v)
        else:
            d.bar.set_fraction(1)
            d.bar.set_text(None)
            d.set_item('All items complete')
            d.finish()
            d.run()
            d.destroy()

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
            if guiutil.question('Confirm Write', msg, confirm_buttons, self,
                                warning = True) != 1:
                return
        # ask for confirmation
        msg = 'Once your changes have been written to the disk, they ' \
                'cannot be undone.  Are you sure you want to continue?'
        if guiutil.question('Confirm Write', msg, confirm_buttons, self,
                            warning = True) != 1:
            return
        # show progress dialogue
        d = guiutil.Progress('Writing to disk', parent = self)
        d.show()
        # start write in another thread
        q = Queue()
        t = Thread(target = self._write, args = (q,))
        t.start()
        while True:
            while q.empty():
                while gtk.events_pending():
                    gtk.main_iteration()
                sleep(conf.SLEEP_INTERVAL)
            got = q.get()
            if len(got) == 3:
                # update progress bar
                done, total, name = got
                d.bar.set_fraction(done / total)
                done = guiutil.printable_filesize(done)
                total = guiutil.printable_filesize(total)
                d.bar.set_text('Completed {} of {}'.format(done, total))
                d.set_item('Copying file: ' + name)
            else:
                # finished
                msg, traceback = got
                break
        t.join()
        if msg is None:
            d.bar.set_fraction(1)
            d.bar.set_text(None)
            d.set_item('All items complete')
            d.finish()
            d.run()
            d.destroy()
            # tree is different, so have to get rid of history
            self.fs_backend.reset()
            self.file_manager.refresh()
        else:
            d.destroy()
            # show error
            if traceback is None:
                guiutil.error(msg, self)
                refresh = False
            else:
                v = guiutil.text_viewer(traceback, gtk.WrapMode.WORD_CHAR)
                guiutil.error(msg, self, v)
                # don't try and do anything else, in case it breaks things

    def open_prefs (self):
        """Open the preferences window."""
        if self.prefs is None:
            self.prefs = Preferences(self)
        else:
            self.prefs.present()

    def quit (self, *args):
        """Quit the program."""
        if not self.get_sensitive():
            # doing stuff
            return True
        if self.fs_backend.can_undo() or self.fs_backend.can_redo():
            # confirm
            msg = 'The changes you\'ve made will be lost if you quit.  Are ' \
                  'you sure you want to continue?'
            if guiutil.question('Confirm Quit', msg,
                                (gtk.STOCK_CANCEL, '_Quit Anyway'), self,
                                warning = True) != 1:
                return True
        gtk.main_quit()