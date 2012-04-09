"""gcedit preferences window module.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

    CLASSES

Preferences

    FUNCTIONS

gen_widgets

"""

# TODO:
# [ENH] access keys in tabs, widgets
# [IMP] widget labels
# [IMP] sensitivity
# [IMP] filechooserbuttons choose files, not dirs
# [BUG] filechooserbuttons shouldn't change on close (they become None)
# [IMP] set page (grid) first column to 12px

from gi.repository import Gtk as gtk

from . import conf
from .conf import settings

"""

_widgets is a data structure defining settings to automatically build the
preferences widgets; it is a dict with setting_ID keys and
    (setting_type[, type_args][, update_cb][, update_on_change][, *sensitive])
values.

setting_ID: ID used to identify the setting.
setting_type: a string that indicates the type of setting (see list below).
type_args: data that affects the behaviour of the setting; if the required
           value in the list below is not specified, this is ignored.
update_cb: a function that is passed the running Editor instance, setting_ID
           and the new value of the setting when it is changed (None for types
           with no value).  Returns True to indicate that updating the setting
           has been handled (or should not be handled); otherwise, it is
           automatically updated based on its type (does nothing for types with
           no value).

           Alternatively, update_cb can be the name of a method of Editor to
           call that with setting_ID and the value (and handle its return value
           in the same manner).  If this argument is None or not given, the
           setting is just automatically updated.
update_on_change: whether to call update_cb (and/or perform automatic setting
                  update) when the widget is changed (otherwise only do so
                  when the preferences is closed); defaults to
                  conf.UPDATE_ON_CHANGE.
sensitive: one or more (setting_ID, value) tuples, where the widget is only
           sensitive if the widgets corresponding to each setting_ID have the
           corresponding value.

Setting types are:

button: takes the label, which is assumed to be stock if it starts with 'gtk-';
        otherwise, it is assumed to use underline if it contains '_'.  It can
        also be (label, icon) to show a stock icon with the given label (and
        label may again contain '_' for underline).  This type has no value.
text: shows a text entry.
bool: shows a checkbox.
dir: choose a directory on the real filesystem.
int: shows a widget to set an integer; takes (min, max, step[, units]).  units
     is a list, which, if given, defines a choice of units to show in a
     dropdown to the right, and update_cb is called with (int, choice) for the
     respective values for those setting types when either widget is changed.
choice: shows a dropdown; takes a list of (string) values; value is the index
        of the chosen value in the given list.

"""

_cb = lambda e, i, v: True
_widgets = {
    # interface
    'sel_on_drag': ('bool', None, _cb),
    'warnings': ('button', 'Re-enable all warnings', _cb),
    # trash
    'trash_enabled': ('bool', None, _cb, False),
    'trash_location': ('dir', None, _cb, False, ('trash_enabled', True)),
    'trash_size': ('int', (1, 1023, 1, ('KiB', 'MiB', 'GiB')), _cb, False,
                   ('trash_enabled', True)),
    # backend
    'set_tmp_dir': ('bool',),
    'tmp_dir': ('dir', None, None, True, ('set_tmp_dir', True)),
    'simul_rw': ('choice', ('automatic', 'always', 'never')),
    'block_size': ('int', (1, 1023, 1, ('B', 'KiB', 'MiB')))
}


def _update_widgets (editor, *ws, from_cb = False):
    """Call widget"""
    for setting_id, w, t, cb in ws:
        # get setting value
        # TODO: get v from w based on t
        if t == 'button':
            v = None
        elif t == 'text':
            v = w.get_text()
        elif t == 'bool':
            v = w.get_active()
        elif t == 'dir':
            v = w.get_filename()
        elif t == 'int':
            if hasattr(w, 'other'):
                # has units
                units = w.other
                if isinstance(w, gtk.ComboBox):
                    w, units = units, w
                v = (w.get_value(), units.get_active())
            else:
                v = w.get_value()
        else: # t == 'choice'
            v = w.get_active()
        # call callback, if any
        do = True
        if callable(cb):
            do = cb(editor, setting_id, v)
        elif cb is not None:
            # cb is a method of editor
            do = getattr(editor, cb)(setting_id, v)
        if do and v is not None:
            settings[setting_id] = v

def _cb_wrapper (w, *args):
    """Widget callback; calls _update_widgets with the needed arguments."""
    editor, setting_id, setting_type, cb = args[-1]
    _update_widgets(editor, (setting_id, w, setting_type, cb), from_cb = True)

def _gen_widget (editor, setting_id, t, data = None, cb = None,
                 update_on_change = conf.UPDATE_ON_CHANGE, *sensitive):
    """Generate a setting's widget.

Takes the elements of the data stored in the setting's _widgets entry as
arguments.

"""
    if t == 'button':
        # data is label
        if not isinstance(data, str):
            name, icon = data
            w = gtk.Button(name, None, '_' in name)
            img = gtk.Image.new_from_stock(icon, gtk.IconSize.BUTTON)
            w.set_image(img)
        elif data.startswith('gtk-'):
            w = gtk.Button(None, data)
        else:
            w = gtk.Button(data, None, '_' in data)
    elif t == 'text':
        w = gtk.Entry()
        w.set_text(settings[setting_id])
    elif t == 'bool':
        w = gtk.CheckButton()
        w.set_active(settings[setting_id])
    elif t == 'dir':
        w = gtk.FileChooserButton('Choose a directory',
                                  gtk.FileChooserAction.SELECT_FOLDER)
        w.set_filename(settings[setting_id])
    elif t == 'int':
        w = gtk.SpinButton.new_with_range(*data[:3])
        v = settings[setting_id]
        if len(data) == 4:
            w.set_value(v[0])
            # combo box for units
            units = gtk.ComboBoxText()
            for item in data[3]:
                units.append_text(item)
            units.set_active(v[1])
            units.connect('changed', _cb_wrapper, (editor, setting_id, t, cb))
            w.other = units
            units.other = w
            # put in a container
            real_w = gtk.Box(False, 6)
            real_w.pack_start(w, False, False, 0)
            real_w.pack_start(units, False, False, 0)
            w.show()
            units.show()
        else:
            w.set_value(v)
    else: # t == 'choice'
        w = gtk.ComboBoxText()
        for item in data:
            w.append_text(item)
        w.set_active(settings[setting_id])
    # attach callback
    signal = {'button': 'clicked', 'text': 'changed', 'bool': 'toggled',
              'dir': 'file-set', 'int': 'value-changed',
              'choice': 'changed'}[t]
    if update_on_change:
        w.connect(signal, _cb_wrapper, (editor, setting_id, t, cb))
    try:
        real_w
    except NameError:
        real_w = w
    return real_w, w, cb, update_on_change

def gen_widgets (editor):
    """Generate widgets for all settings.

gen_widgets(editor) -> (widgets, cb)

editor: the running Editor instance.

widgets: a setting_ID: widget dict for all settings.
cb: a function to call to update some settings when the preferences window is
closed.

"""
    ws = {}
    update_on_close = []
    for setting_id, data in _widgets.items():
        real_w, w, cb, update_on_change = _gen_widget(editor, setting_id,
                                                      *data)
        ws[setting_id] = real_w
        if not update_on_change:
            update_on_close.append((setting_id, w, data[0], cb))
    if update_on_close:
        # call remaining callbacks on preferences close
        cb = lambda: _update_widgets(editor, *update_on_close)
    else:
        cb = lambda: None
    return ws, cb

"""

_prefs is a dict of tabs, the keys their titles.  Each tab is a list containing
headings and settings; a heading is a str object, and a setting is a
(setting_ID[, label]) tuple.

"""

_prefs = {
    'Interface': (('sel_on_drag',), ('warnings',)),
    'Trash': (('trash_enabled',), ('trash_location',), ('trash_size',)),
    'Backend': (('set_tmp_dir',), ('tmp_dir',), ('simul_rw',), ('block_size',))
}


class Preferences (gtk.Window):
    """Preferences window (Gtk.Window subclass).

Takes the running Editor instance.

    METHODS

quit

"""

    def __init__ (self, editor):
        gtk.Window.__init__(self)
        self.set_resizable(False)
        self.set_border_width(12)
        self.set_title(conf.APPLICATION + ' Preferences')
        self.connect('delete-event', self.quit)
        self._widgets, self._end_cb = gen_widgets(editor)
        # add outer stuff
        v = gtk.Box(False, 12)
        v.set_orientation(gtk.Orientation.VERTICAL)
        self.add(v)
        tabs = gtk.Notebook()
        v.pack_start(tabs, True, True, 0)
        bs = gtk.Box()
        v.pack_start(bs, False, False, 0)
        b = gtk.Button(None, gtk.STOCK_CLOSE)
        bs.pack_end(b, False, False, 0)
        b.connect('clicked', self.quit)
        # create pages with widgets
        for tab, items in _prefs.items():
            page = gtk.Grid()
            page.set_row_spacing(6)
            page.set_border_width(12)
            tabs.append_page(page, gtk.Label(tab))
            y = 0
            items = list(items) # might be modified
            for item in items:
                if y == 0 and not isinstance(item, str):
                    # if first item isn't a heading, use tab name
                    # add this item back to the list first
                    items.insert(1, item)
                    item = tab
                if isinstance(item, str):
                    # heading
                    l = gtk.Label('<b>{}</b>'.format(item))
                    page.attach(l, 0, y, 2, 1)
                    l.set_use_markup(True)
                    l.set_alignment(0, .5)
                    if y != 0:
                        l.set_margin_top(6)
                else:
                    # setting
                    if len(item) == 2:
                        # got a label
                        print(item[1])
                        # TODO; maybe y += 1
                    page.attach(self._widgets[item[0]], 1, y, 1, 1)
                y += 1
        self.show_all()

    def quit (self, *args):
        """Clean up and hide the window."""
        self._end_cb()
        self.hide()
        return True