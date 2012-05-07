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
# [ENH] include game name in window title (need BNR support)
# [ENH] icon
# [FEA] pause/cancel in write/extract
# [FEA] display file size
# [FEA] can search within filesystem (ctrl-f, edit/find; shows bar with entry and Next/Previous buttons)
# [FEA] track deleted files (not dirs) (get paths recursively) and put in trash when write
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

import os
from time import sleep
from traceback import format_exc
try:
    from threading import Thread
except ImportError:
    from dummy_threading import Thread
from queue import Queue
from html import escape

from gi.repository import Gtk as gtk, Gdk as gdk
from .ext import fsmanage, gcutil

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

hist_update
extract
write
set_sel_on_drag
reset_warnings
update_threaded
update_bs
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
        self.fs = fs
        self.update_threaded()
        self.update_bs()
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
        self._update_title()
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
            (gtk.STOCK_UNDO, _('Undo the last change'), self.fs_backend.undo),
            (gtk.STOCK_REDO, _('Redo the next change'), self.fs_backend.redo),
            None,
            ((_('_Import Files'), gtk.STOCK_HARDDISK),
              # NOTE: tooltip on the 'Import Files' button
             _('Import files from outside'), self.fs_backend.do_import, False),
            ((_('I_mport Directories'), gtk.STOCK_HARDDISK),
              # NOTE: tooltip on the 'Import Directories' button
             _('Import directories from outside'), self.fs_backend.do_import,
             True),
            ((_('_Extract'), gtk.STOCK_EXECUTE),
             _('Extract the selected files'), self.extract),
            ((_('_Write'), gtk.STOCK_SAVE),
             _('Write changes to the disk image'), self.write),
            (gtk.STOCK_PREFERENCES, _('Open the preferences window'),
             self.open_prefs),
            (gtk.STOCK_QUIT, _('Quit the application'), self.quit)
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

    def _update_title (self):
        """Set the window title based on the current state."""
        fn = os.path.basename(self.fs.fn)
        changed = '*' if self.fs_backend.can_undo() else ''
        self.set_title('{}{} - {}'.format(changed, fn, conf.APPLICATION))

    def hist_update (self):
        """Update stuff when the history changes."""
        self.buttons[0].set_sensitive(self.fs_backend.can_undo())
        self.buttons[1].set_sensitive(self.fs_backend.can_redo())
        self._update_title()

    def _run_with_progress_backend (self, q, method, progress, args, kwargs):
        """Wrapper that calls a backend function with a progress method.

_run_with_progress_backend(q, method, progress, args, kwargs)

q: a queue to put things on.
method: the method of the GCFS instance to call.
progress: the progress callback to pass to the method.
args, kwargs: arguments to the method, excluding the progress argument.

"""
        try:
            rtn = getattr(self.fs, method)(*args, progress = progress,
                                           **kwargs)
        except Exception as e:
            if hasattr(e, 'handled') and e.handled is True:
                # disk should still be in the same state
                # NOTE: {} is an error message
                msg = _('Couldn\'t write: {}.').format(e.args[0])
                q.put(('handled_err', msg))
            else:
                # not good: show traceback
                msg = _('Something may have gone horribly wrong, and the ' \
                        'disk image might have ended up in an ' \
                        'inconsistent state.  Here\'s some debug ' \
                        'information.')
                q.put(('unhandled_err', (msg, format_exc().strip())))
        else:
            q.put(('end', rtn))

    def _run_with_progress (self, method, title, item_text, failed = None,
                            *args, **kwargs):
        """Run a backend function with a progress window.

_run_with_progress(method, title, item_text[, failed], *args, **kwargs)
    -> (rtn, err)

method: the method of the GCFS instance to call.
title: the window title.
item_text: format for the text displayed for each item; with an item returned
           by the method, this function displays item_text.format(item).
failed: an (optional) function that takes the return value of the method and
        returns whether it has failed (in which case, this function returns
        immediately instead of leaving the progress window open for the user to
        close it).
args, kwargs: arguments passed to the method, excluding the progress argument.

rtn: the method's return value, or None if it raised an exception.
err: whether the method raised an exception (to make it possible to distingish
     between it raising an exception and it returning None).

"""
        # create callbacks
        q = Queue()
        status = {'paused': False, 'cancelled': False, 'cancel_btn': None}

        def progress (*args):
            if args[0] is not None:
                q.put(('progress', args))
            if status['cancelled'] == 1:
                # cancelled
                status['cancelled'] = 2
                return 2
            else:
                if status['cancelled'] == 2:
                    # cancel attempted, but unsuccessful
                    status['cancelled'] = False
                    status['cancel_btn'].set_sensitive(False)
                    # do silly stuff
                    err = _('Cannot cancel: files have been overwritten.')
                    err = gtk.Label('<i>{}</i>'.format(escape(err)))
                    err.set_use_markup(True)
                    err.set_line_wrap(True)
                    err.set_alignment(0, .5)
                    bb = d.get_action_area()
                    bs = bb.get_children()
                    bb.pack_start(err, True, True, 0)
                    for b in bs:
                        bb.remove(b)
                    for b in reversed(bs):
                        bb.pack_end(b, False, False, 0)
                    err.show()
                if status['paused']:
                    # paused
                    return 1

        def pause_cb (b):
            status['paused'] = True

        def unpause_cb (b):
            status['paused'] = False

        def cancel_cb (b):
            status['cancelled'] = 1
            status['cancel_btn'] = b
            d.set_item(_('Cancelling...'))

        # create dialogue
        d = guiutil.Progress(title, cancel_cb, pause_cb, unpause_cb, self,
                             autoclose = settings['autoclose_progress'])
        d.set_item(_('Preparing...'))
        d.show()
        # start write in another thread
        t = Thread(target = self._run_with_progress_backend,
                   args = (q, method, progress, args, kwargs))
        t.start()
        err_msg = None
        while True:
            while q.empty():
                while gtk.events_pending():
                    gtk.main_iteration()
                sleep(conf.SLEEP_INTERVAL)
            action, data = q.get()
            if action == 'progress':
                # update progress bar
                done, total, name = data
                d.bar.set_fraction(done / total)
                done = guiutil.printable_filesize(done)
                total = guiutil.printable_filesize(total)
                # NOTE: eg. 'Completed 5MiB of 34MiB'
                d.bar.set_text(_('Completed {} of {}').format(done, total))
                if not status['cancelled']:
                    d.set_item(item_text.format(name))
            elif action == 'handled_err':
                err_msg = data
                err_handled = True
                break
            elif action == 'unhandled_err':
                err_msg, traceback = data
                err_handled = False
                break
            else: # action == 'end'
                # finished
                rtn = data
                break
        t.join()
        # save autoclose setting
        settings['autoclose_progress'] = d.autoclose.get_active()
        if err_msg is not None:
            d.destroy()
            # show error
            if err_handled:
                guiutil.error(err_msg, self)
            else:
                v = guiutil.text_viewer(traceback, gtk.WrapMode.WORD_CHAR)
                guiutil.error(err_msg, self, v)
                # don't try and do anything else, in case it breaks things
            rtn = None
        elif failed is not None and failed(rtn):
            d.destroy()
        else:
            if rtn is True:
                # cancelled
                d.set_item(_('Cancelled.'))
            else:
                # completed
                d.bar.set_fraction(1)
                d.bar.set_text(_('Completed'))
                d.set_item(_('All items complete.'))
            autoclose = d.finish()
            # wait for user to close dialogue
            if not autoclose:
                if d.run() == 0:
                    settings['autoclose_progress'] = True
            d.destroy()
        return (rtn, err_msg is not None)

    def extract (self, *files):
        """Extract the files at the given paths, else the selected files."""
        if not files:
            # get selected files
            files = self.file_manager.get_selected_files()
            if not files:
                # nothing to do
                msg = _('No files selected: to extract, select some files ' \
                        'first.')
                guiutil.error(msg, self)
                return
            path = self.file_manager.path
            files = [path + [name] for name in files]
        # get destination(s)
        rt = gtk.ResponseType
        if len(files) == 1:
            # ask for filename to extract to
            # NOTE: title for a file chooser dialogue
            label = _('Choose where to extract to')
            action = gtk.FileChooserAction.SAVE
        else:
            # ask for directory to extract all files to
            # NOTE: title for a file chooser dialogue
            label = _('Choose a directory to extract all items to')
            action = gtk.FileChooserAction.SELECT_FOLDER
        buttons = (gtk.STOCK_CLOSE, rt.CLOSE, gtk.STOCK_OK, rt.OK)
        d = gtk.FileChooserDialog(label, self, action, buttons)
        d.set_current_folder(settings['extract_path'])
        if len(files) == 1:
            # set name to that in the disk
            d.set_current_name(files[0][-1])
        if d.run() != rt.OK:
            d.destroy()
            return
        dest = d.get_filename()
        # remember dir
        settings['extract_path'] = d.get_current_folder()
        d.destroy()
        # get full destination paths
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
        failed_cb = lambda rtn: rtn and rtn is not True
        failed, err = self._run_with_progress('extract', _('Extracting files'),
                                              _('Extracting file: {}'),
                                              failed_cb, args)
        if failed and failed is not True:
            # display failed list
            v = guiutil.text_viewer('\n'.join(dest for f, dest in failed),
                                    gtk.WrapMode.NONE)
            msg = _('Couldn\'t extract to the following locations.  Maybe ' \
                    'the files already exist, or you don\'t have permission ' \
                    'to write here.')
            guiutil.error(msg, self, v)

    def write (self):
        """Write changes to the disk."""
        confirm_buttons = (gtk.STOCK_CANCEL, _('_Write Anyway'))
        if not self.fs.changed():
            # no need to write
            return
        elif self.fs.disk_changed():
            if 'changed_write' not in settings['disabled_warnings']:
                msg = _('The contents of the disk have been changed by ' \
                        'another program since it was loaded.  Are you sure ' \
                        'you want to continue?')
                ask_again = ('changed_write', 1)
                # NOTE: confirmation dialogue title
                if guiutil.question(_('Confirm Write'), msg, confirm_buttons,
                                    self, None, True, ask_again) != 1:
                    return
        # ask for confirmation
        if 'write' not in settings['disabled_warnings']:
            msg = _('Once your changes have been written to the disk, they ' \
                    'cannot be undone.  Are you sure you want to continue?')
            if guiutil.question(_('Confirm Write'), msg, confirm_buttons, self,
                                None, True, ('write', 1)) != 1:
                return
        # show progress dialogue
        tmp_dir = settings['tmp_dir'] if settings['set_tmp_dir'] else None
        rtn, err = self._run_with_progress('write', _('Writing to disk'),
                                           _('Copying file: {}'), None,
                                           tmp_dir)
        if not err:
            # tree is different, so have to get rid of history
            self.fs_backend.reset()
            self.file_manager.refresh()

    def _state_cb (self, w, e):
        """Save changes to maximised state."""
        is_max = e.new_window_state & gdk.WindowState.MAXIMIZED
        settings['win_max'] = bool(is_max)

    def _size_cb (self, w, size):
        """Save changes to window size."""
        if not settings['win_max']:
            settings['win_size'] = (size.width, size.height)

    def set_sel_on_drag (self, value):
        """Update value of select_on_drag of file manager."""
        self.file_manager.set_rubber_banding(value)

    def reset_warnings (self):
        """Re-enable all disabled warnings."""
        settings['disabled_warnings'] = None

    def update_threaded (self, value = None):
        """Update the gcutil module's THREADED setting."""
        if value is None:
            gcutil.THREADED = settings['threaded_copy']
        else:
            gcutil.THREADED = value

    def update_bs (self, value = None):
        """Update the gcutil module's BLOCK_SIZE setting."""
        if value is None:
            bs, exp = settings['block_size']
        else:
            bs, exp = value
        bs *= 1024 ** exp
        gcutil.BLOCK_SIZE = int(bs)

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
            msg = _('The changes you\'ve made will be lost if you quit.  ' \
                    'Are you sure you want to continue?')
            if 'quit_with_changes' not in settings['disabled_warnings']:
                # NOTE: confirmation dialogue title
                if guiutil.question(_('Confirm Quit'), msg,
                                    (gtk.STOCK_CANCEL, _('_Quit Anyway')), self,
                                    None, True, ('quit_with_changes', 1)) != 1:
                    return True
        gtk.main_quit()