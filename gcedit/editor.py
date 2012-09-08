"""gcedit editor module.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

    CLASSES

Editor

"""

# TODO:
# [FEA] decompress (need backend support)
# [BUG] menu separators don't draw properly
# [FEA] multi-paned file manager
# [FEA] track deleted files (not dirs) (get paths recursively) and put in trash when write
# [ENH] progress windows: remaining time estimation
# [ENH] import/export via drag-and-drop
# [FEA] open archives inline (reuse GCFS code, probably)

import os
from platform import system
from time import sleep
from traceback import format_exc
try:
    from threading import Thread
except ImportError:
    from dummy_threading import Thread
from queue import Queue
from html import escape

from gi.repository import Gtk as gtk
from .ext import fsmanage, gcutil

from .fsbackend import FSBackend
from .prefs import Preferences
from . import guiutil, search, loader, conf
from .conf import settings

system = system()

def mk_fn (cb, *cb_args):
    def f (*args):
        cb(*cb_args)
    return f


class MenuBar (gtk.MenuBar):
    """Editor menu bar (Gtk.MenuBar subclass).

Takes the current Editor instance.

"""
    def __init__ (self, editor):
        gtk.MenuBar.__init__(self)
        self.accel_group = accel_group = gtk.AccelGroup()

        def in_manager (cb, *args):
            editor.file_manager.grab_focus()
            cb(*args)

        for title, items in (
        (gtk.STOCK_FILE, ({
                'widget': gtk.STOCK_OPEN,
                'tooltip': _('Close this file and load a different one'),
                'cb': editor.browse,
                'accel': '<ctrl>o'
            }, {
                'widget': (_('Back to _Loader'), gtk.STOCK_HOME),
                'tooltip': _('Go back to the list of recently opened files'),
                'cb': editor.back_to_loader
            }, {
                'widget': gtk.STOCK_QUIT,
                'tooltip': _('Quit the application'),
                'cb': editor.quit,
                'accel': '<ctrl>q'
        })), (gtk.STOCK_EDIT, ({
                'widget': gtk.STOCK_UNDO,
                'tooltip': _('Undo the last change'),
                'cb': editor.fs_backend.undo,
                'accel': '<ctrl>z'
            }, {
                'widget': gtk.STOCK_REDO,
                'tooltip': _('Redo the next change'),
                'cb': editor.fs_backend.redo,
                'accel': '<ctrl>y' if system == 'Windows' else '<ctrl><shift>z'
            }, None, {
                'widget': gtk.STOCK_CUT,
                'tooltip': _('Prepare to move selected files'),
                'cb': (in_manager, editor.file_manager.cut),
                'accel': '<ctrl>x'
            }, {
                'widget': gtk.STOCK_COPY,
                'tooltip': _('Prepare to copy selected files'),
                'cb': (in_manager, editor.file_manager.copy),
                'accel': '<ctrl>c'
            }, {
                'widget': gtk.STOCK_PASTE,
                'tooltip': _('Paste cut or copied files'),
                'cb': (in_manager, editor.file_manager.paste),
                'accel': '<ctrl>v'
            }, {
                'widget': gtk.STOCK_DELETE,
                'tooltip': _('Delete selected files'),
                'cb': (in_manager, editor.file_manager.delete),
                'accel': 'Delete'
            }, {
                'widget': '_Rename',
                'tooltip': _('Rename selected files'),
                'cb': (in_manager, editor.file_manager.rename),
                'accel': 'F2'
            }, {
                'widget': gtk.STOCK_NEW,
                'tooltip': _('Create directory'),
                'cb': (in_manager, editor.file_manager.new_dir),
                'accel': '<ctrl>n'
            }, None, {
                'widget': (_('_Import Files'), gtk.STOCK_HARDDISK),
                # NOTE: tooltip on the 'Import Files' button
                'tooltip': _('Import files from outside'),
                'cb': (editor.fs_backend.do_import, False),
                'accel': '<ctrl>i'
            }, {
                'widget': (_('I_mport Directories'), gtk.STOCK_HARDDISK),
                # NOTE: tooltip on the 'Import Directories' button
                'tooltip': _('Import directories from outside'),
                'cb': (editor.fs_backend.do_import, True),
                'accel': '<ctrl><shift>i'
            }, {
                'widget': (_('_Extract'), gtk.STOCK_EXECUTE),
                'tooltip': _('Extract the selected files'),
                'cb': editor.extract,
                'accel': '<ctrl>e'
            }, None, {
                'widget': gtk.STOCK_SELECT_ALL,
                'tooltip': _('Select all files'),
                'cb': (in_manager,
                       editor.file_manager.get_selection().select_all),
                'accel': '<ctrl>a',
            }, None, {
                'widget': gtk.STOCK_FIND,
                'tooltip': _('Search for files in the disk'),
                'cb': editor.start_find,
                'accel': '<ctrl>f'
            }, None, {
                'widget': gtk.STOCK_PREFERENCES,
                'tooltip': _('Open the preferences window'),
                'cb': editor.open_prefs,
                'accel': '<ctrl>p'
        })), (_('_Disk'), ({
                'widget': (_('_Discard Changes'), gtk.STOCK_CLEAR),
                'tooltip': _('Undo all changes that have been made since the '
                             'last write'),
                'cb': editor.discard_changes
            }, {
                'widget': _('_Compress Disk'),
                'tooltip': _('Reorganise files in the disk to reduce free '
                             'space'),
                'cb': editor.compress
            },
            # decompress
            {
                'widget': (_('_Write'), gtk.STOCK_SAVE),
                'tooltip': _('Write changes to the disk image'),
                'cb': editor.write,
                'accel': '<ctrl>s'
        })), (_('_View'), ({
                'widget': gtk.STOCK_GO_BACK,
                'tooltip': _('Go to the previous directory'),
                'cb': (in_manager, editor.file_manager.back),
                'accel': '<alt>Left'
            }, {
                'widget': gtk.STOCK_GO_FORWARD,
                'tooltip': _('Go to the next directory in history'),
                'cb': (in_manager, editor.file_manager.forwards),
                'accel': '<alt>Right'
            }, {
                'widget': gtk.STOCK_GO_UP,
                'tooltip': _('Go to parent directory'),
                'cb': (in_manager, editor.file_manager.up),
                'accel': '<alt>Up'
            }
            # ----
            # split horizontally
            # split vertically
            # close split
        )), (gtk.STOCK_HELP, ({
                'widget': gtk.STOCK_ABOUT,
                'cb': editor.about
        },))):
            # menu button
            title_item = guiutil.MenuItem(title)
            if title.startswith('gtk-'):
                title_item.set_image(None)
            self.append(title_item)
            menu = gtk.Menu()
            # needs accel group so accels work
            menu.set_accel_group(accel_group)
            title_item.set_submenu(menu)
            menu_accel_path = '<GCEdit>/' + title_item.get_label()
            # menu items
            for data in items:
                if data is None:
                    # separator
                    data = {'widget': None}
                item = guiutil.MenuItem(data['widget'],
                                        data.get('tooltip', None))
                menu.append(item)
                # callback
                try:
                    cb = data['cb']
                except KeyError:
                    pass
                else:
                    if callable(cb):
                        args = ()
                    else:
                        cb, *args = cb
                    item.connect('activate', mk_fn(cb, *args))
                # accelerator
                try:
                    accel = data['accel']
                except KeyError:
                    pass
                else:
                    accel_path = menu_accel_path + '/' + item.get_label()
                    item.set_accel_path(accel_path)
                    key, mods = gtk.accelerator_parse(accel)
                    gtk.AccelMap.add_entry(accel_path, key, mods)
        # restore accels
        gtk.AccelMap.load(os.path.join(conf.CONF_DIR, 'accels'))
        gtk.AccelMap.get().connect('changed', self._save_accels)

    def _save_accels (self, *args):
        """Save accels when changed."""
        gtk.AccelMap.save(os.path.join(conf.CONF_DIR, 'accels'))


class Editor (guiutil.Window):
    """The main application window.

Takes a gcutil.GCFS instance.

    METHODS

hist_update
browse
back_to_loader
extract
start_find
end_find
discard_changes
compress
write
about
set_sel_on_drag
reset_warnings
update_bs
open_prefs
quit

    ATTRIBUTES

fs: the given gcutil.GCFS instance.
fs_backend: FSBackend instance.
file_manager: fsmanage.Manager instance.
buttons: a list of the buttons on the left.
prefs: preferences window or None.
searching: whether the search bar is currently open.
search: search window or None.
search_manager: fsmanage.Manager instance for search results, or None.

"""

    def __init__ (self, fs):
        self.searching = False
        self.prefs = None
        self.search = None
        self.search_manager = None
        self.fs = fs
        self.update_bs()
        self.fs_backend = FSBackend(fs, self)
        ident = (conf.IDENTIFIER, self.fs.fn, id(self))
        disabled_accels = ('F5', '<alt>Up', '<alt>Left', '<alt>Right',
                           '<ctrl>x', '<ctrl>c', '<ctrl>v', 'Delete', 'F2',
                           '<ctrl>n')
        m = fsmanage.Manager(self.fs_backend, identifier = ident,
                             # NOTE: filesize
                             extra_cols = [(_('Size'), None), None],
                             disabled_accels = disabled_accels)
        self.file_manager = m
        m.set_tooltip_column(fsmanage.COL_LAST + 2)
        self.set_sel_on_drag(settings['sel_on_drag'])
        menu_bar = MenuBar(self)
        # window
        guiutil.Window.__init__(self, 'main')
        self._name = self.fs.get_info()['name']
        self._update_title()
        self.connect('delete-event', self.quit)
        # shortcuts
        self.add_accel_group(menu_bar.accel_group)
        self.add_accel_group(self.file_manager.accel_group)
        # contents
        g = gtk.Grid()
        self.add(g)
        g.set_column_spacing(12)
        g.set_row_spacing(6)
        g.set_margin_bottom(12)
        g.attach(menu_bar, -1, -1, 4, 1)
        for x in (-1, 2):
            a = gtk.Alignment()
            g.attach(a, x, 0, 1, 1)
        # left
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
             _('Write changes to the disk image'), self.write)
        ):
            if btn_data is None:
                for b in fsmanage.buttons(m):
                    btns.append(b)
            else:
                name, tooltip, cb, *cb_args = btn_data
                b = guiutil.Button(name, tooltip)
                btns.append(b)
                if cb is not None:
                    b.connect('clicked', f, cb, *cb_args)
        for i, b in enumerate(btns):
            g.attach(b, 0, i, 1, 1)
        self.hist_update()
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
        m.set_hexpand(True)
        m.set_vexpand(True)
        # automatically computed button focus order is weird
        g.set_focus_chain(btns + [g_right])
        # display
        self.show_all()
        self.hide()
        m.grab_focus()

    def _update_title (self):
        """Set the window title based on the current state."""
        fn = os.path.abspath(self.fs.fn)
        changed = '*' if self.fs_backend.can_undo() else ''
        self.set_title('{}{} ({}) - {}'.format(changed, self._name, fn,
                                               conf.APPLICATION))

    def hist_update (self):
        """Update stuff when the history changes."""
        self.buttons[0].set_sensitive(self.fs_backend.can_undo())
        self.buttons[1].set_sensitive(self.fs_backend.can_redo())
        self.buttons[-1].set_sensitive(self.fs.changed())
        self._update_title()

    def _confirm_open (self):
        """Asks to open a different file and returns the answer."""
        if self.fs_backend.can_undo() or self.fs_backend.can_redo():
            msg = _('The changes you\'ve made will be lost if you open a '
                    'different file.  Are you sure you want to continue?')
            if 'open_with_changes' not in settings['disabled_warnings']:
                btns = (gtk.STOCK_CANCEL, _('_Open Anyway'))
                # NOTE: confirmation dialogue title
                if guiutil.question(_('Confirm Open'), msg, btns, self, None,
                                    True, ('open_with_changes', 1)) != 1:
                    return False
        return True

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
                q.put(('handled_err', e))
            else:
                # not good: show traceback
                q.put(('unhandled_err', (e, format_exc().strip())))
        else:
            q.put(('end', rtn))

    def _run_with_progress (self, method, title, item_text, handled_msg,
                            failed = None, handled = {}, *args, **kwargs):
        """Run a backend function with a progress window.

_run_with_progress(method, title, item_text, handled_msg[, failed],
                   handled = {}, *args, **kwargs) -> (rtn, err)

method: the method of the GCFS instance to call.
title: the window title.
item_text: format for the text displayed for each item; with an item returned
           by the method, this function displays item_text.format(item).
handled_msg: message to do .format(error_message) on and display for 'handled'
             error messages.
failed: an (optional) function that takes the return value of the method and
        returns whether it has failed (in which case, this function returns
        immediately instead of leaving the progress window open for the user to
        close it).
handled: a {cls: msg} dict of 'handled' error messages to show for each
         Exception subclass raised by method.
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
                # clicked cancel: request from worker
                status['cancelled'] = 2
                return 2
            elif status['cancelled'] == 4:
                # clicked force cancel: check with user
                status['cancelled'] += 1
                q.put(('force_cancel', None))
            elif status['cancelled'] == 5:
                # waiting for force cancel confirmation: pause
                return 1
            elif status['cancelled'] == 6:
                # confirmed force cancel: request from worker
                return 3
            else:
                if status['cancelled'] == 2:
                    # cancel request to worker denied
                    status['cancelled'] += 1
                    q.put(('failed_cancel', None))
                if status['paused']:
                    # paused
                    return 1

        def pause_cb (b):
            status['paused'] = True

        def unpause_cb (b):
            status['paused'] = False

        def cancel_cb (b):
            if status['cancelled'] == 3:
                # already tried to cancel: force cancel
                status['cancelled'] += 1
            else:
                # request cancel
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
        err = None
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
            elif action == 'failed_cancel':
                # a cancel attempt failed: change button to Force Cancel
                b = status['cancel_btn']
                b.set_label(_('Force _Cancel'))
                img = gtk.Image.new_from_stock(gtk.STOCK_CANCEL,
                                               gtk.IconSize.BUTTON)
                b.set_image(img)
                # show error message next to buttons
                err_msg = _('Cannot cancel: files have been overwritten.')
                err_msg = gtk.Label('<i>{}</i>'.format(escape(err_msg)))
                err_msg.set_use_markup(True)
                bb = d.get_action_area()
                bs = bb.get_children()
                bb.pack_start(err_msg, True, True, 0)
                for b in bs:
                    bb.remove(b)
                for b in reversed(bs):
                    bb.pack_end(b, False, False, 0)
                err_msg.show()
            elif action == 'force_cancel':
                # ask user to confirm force cancel request
                msg = _('Forcing the process to cancel may corrupt the disk ' \
                        'image or the files on it.  Are you sure you want ' \
                        'to  continue?')
                btns = (_('Continue _Working'), _('_Cancel Anyway'))
                if 'force_cancel' in settings['disabled_warnings'] or \
                   guiutil.question(_('Confirm Force Cancel'), msg, btns, self,
                                    None, True, ('force_cancel', 1)) == 1:
                    status['cancelled'] += 1
                else:
                    status['cancelled'] = 3
            elif action == 'handled_err':
                err = data
                err_handled = True
                break
            elif action == 'unhandled_err':
                err, traceback = data
                err_handled = False
                break
            else: # action == 'end'
                # finished
                rtn = data
                break
        t.join()
        # save autoclose setting
        self._set_autoclose(d.autoclose.get_active())
        if err is not None:
            d.destroy()
            # show error
            if err_handled or type(err) in handled:
                if err_handled:
                    handled_msg = handled_msg.format(err.args[0])
                else:
                    handled_msg = handled_msg.format(handled[type(err)])
                guiutil.error(handled_msg, self)
            else:
                msg = _('Something may have gone horribly wrong, and the disk '
                        'image might have ended up in an inconsistent state.  '
                        'Here\'s some debug information.')
                v = guiutil.text_viewer(traceback, gtk.WrapMode.WORD_CHAR)
                guiutil.error(msg, self, v)
                # don't try and do anything else, in case it breaks things
            rtn = None
        elif failed is not None and failed(rtn):
            d.destroy()
        else:
            if rtn and isinstance(rtn, int):
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
                    self._set_autoclose(True)
            d.destroy()
        return (rtn, err is not None)

    def browse (self):
        """Open a new disk image."""
        if self._confirm_open():
            loader.browse(None, self)

    def back_to_loader (self):
        """Go back to the disk loader."""
        if self._confirm_open():
            self.destroy()
            loader.LoadDisk().show()

    def extract (self, *files):
        """Extract the files at the given paths, else the selected files."""
        if not files:
            # get selected files
            files = self.file_manager.get_selected_files()
            if not files:
                # nothing to do
                msg = _('No files selected: to extract, select some files '
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
            label = _('Choose Where to Extract to')
            action = gtk.FileChooserAction.SAVE
        else:
            # ask for directory to extract all files to
            # NOTE: title for a file chooser dialogue
            label = _('Choose a Directory to Extract All Items to')
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
        failed_cb = lambda rtn: rtn and not isinstance(rtn, int)
        # NOTE: {} is an error message
        msg = _('Couldn\'t extract: {}.')
        handled = {IOError: _('reading or writing failed')}
        failed, err = self._run_with_progress('extract', _('Extracting Files'),
                                              _('Extracting file: {}'), msg,
                                              failed_cb, handled, args)
        if failed and failed is not True:
            # display failed list
            v = guiutil.text_viewer('\n'.join(dest for f, dest in failed),
                                    gtk.WrapMode.NONE)
            msg = _('Couldn\'t extract to the following locations.  Maybe the '
                    'files already exist, or you don\'t have permission to '
                    'write here.')
            guiutil.error(msg, self, v)

    def start_find (self):
        """Open the search bar."""
        self.searching = True
        if self.search is None:
            # create window
            self.search = w = search.SearchWindow(self)
        else:
            w = self.search
        # show window
        w.present()
        w.entry.grab_focus()

    def end_find (self):
        """Close the search bar."""
        if self.searching:
            self.searching = False
            self.search.hide()
            self.search.cleanup()

    def discard_changes (self):
        """Discard all unwritten changes to the disk."""
        b = self.fs_backend
        while b.can_undo():
            b.undo()

    def compress (self):
        """Compress the disk image."""
        btns = (gtk.STOCK_CANCEL, _('_Compress Anyway'))
        # ask for confirmation
        if 'compress' not in settings['disabled_warnings']:
            msg = _('This will discard all changes that haven\'t been written '
                    ' to the disk.  Are you sure you want to continue?')
            if guiutil.question(_('Confirm Compress'), msg, btns,
                                self, None, True, ('compress', 1)) != 1:
                return
        # show progress dialogue
        # NOTE: {} is an error message
        msg = _('Couldn\'t compress: {}.')
        tmp_dir = settings['tmp_dir'] if settings['set_tmp_dir'] else None
        rtn, err = self._run_with_progress('compress', _('Compressing Disk'),
                                           _('Moving file: {}'), msg)
        if not rtn and not err:
            # forget history, refresh tree
            self.fs_backend.reset()
            self.file_manager.refresh()

    def write (self):
        """Write changes to the disk."""
        if not self.fs.changed():
            return
        btns = (gtk.STOCK_CANCEL, _('_Write Anyway'))
        if self.fs.disk_changed():
            if 'changed_write' not in settings['disabled_warnings']:
                msg = _('The contents of the disk have been changed by '
                        'another program since it was loaded.  Are you sure '
                        'you want to continue?')
                # NOTE: confirmation dialogue title
                if guiutil.question(_('Confirm Write'), msg, btns, self, None,
                                    True, ('changed_write', 1)) != 1:
                    return
        # ask for confirmation
        if 'write' not in settings['disabled_warnings']:
            msg = _('Once your changes have been written to the disk, they '
                    'cannot be undone.  Are you sure you want to continue?')
            if guiutil.question(_('Confirm Write'), msg, btns, self, None,
                                True, ('write', 1)) != 1:
                return
        # show progress dialogue
        # NOTE: {} is an error message
        msg = _('Couldn\'t write: {}.')
        tmp_dir = settings['tmp_dir'] if settings['set_tmp_dir'] else None
        rtn, err = self._run_with_progress('write', _('Writing to Disk'),
                                           _('Copying file: {}'), msg, None,
                                           {}, tmp_dir)
        if not rtn and not err:
            # tree is different, so have to get rid of history
            self.fs_backend.reset()
            self.file_manager.refresh()

    def about (self):
        """Show About dialogue."""
        d = gtk.AboutDialog()
        for k, v in {
            # NOTE: About dialogue title; {} becomes the program name
            'program-name': conf.APPLICATION,
            'version': conf.VERSION,
            'title': _('About {}').format(conf.APPLICATION),
            'copyright': _('Copyright 2012 Joseph Lansdowne'),
            'comments': _('A GameCube disk editor'),
            'license-type': gtk.License.GPL_3_0,
            'website': 'http://i-know-nothing.co.cc/GCEdit',
            'website-label': 'i-know-nothing.co.cc/GCEdit',
            # NOTE: replace this with your name as you wish to be credited
            'translator-credits': _('translator-credits'),
            'logo-icon-name': conf.IDENTIFIER,
        }.items():
            d.set_property(k, v)
        d.run()
        d.destroy()

    def set_sel_on_drag (self, value):
        """Update value of select_on_drag of file manager."""
        self.file_manager.set_rubber_banding(value)

    def reset_warnings (self):
        """Re-enable all disabled warnings."""
        settings['disabled_warnings'] = None

    def update_bs (self, value = None):
        """Update the gcutil module's BLOCK_SIZE setting."""
        if value is None:
            bs, exp = settings['block_size']
        else:
            bs, exp = value
        bs *= 1024 ** exp
        gcutil.BLOCK_SIZE = int(bs)

    def _set_autoclose (self, value):
        """Change the autoclose setting."""
        if self.prefs is None:
            settings['autoclose_progress'] = value
        else:
            self.prefs.widgets['autoclose_progress'].set_active(value)

    def open_prefs (self):
        """Open the preferences window."""
        if self.prefs is None:
            self.prefs = Preferences(self)
        else:
            self.prefs.present()

    def quit (self, *args):
        """Quit the program."""
        if self.fs_backend.can_undo() or self.fs_backend.can_redo():
            # confirm
            msg = _('The changes you\'ve made will be lost if you quit.  Are '
                    'you sure you want to continue?')
            if 'quit_with_changes' not in settings['disabled_warnings']:
                btns = (gtk.STOCK_CANCEL, _('_Quit Anyway'))
                # NOTE: confirmation dialogue title
                if guiutil.question(_('Confirm Quit'), msg, btns, self, None,
                                    True, ('quit_with_changes', 1)) != 1:
                    return True
        gtk.main_quit()
