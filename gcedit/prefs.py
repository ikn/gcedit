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
# [IMP] sensitivity

import os

from gi.repository import Gtk as gtk

from . import conf
from .conf import settings

"""

_widgets is a data structure defining settings to automatically build the
preferences widgets; it is a setting_ID: data dict, where:

setting_ID: ID used to identify the setting.
data: a dict with the following keys (all are optional except type and,
      depending on the type, data):

t: a string that indicates the type of setting (see list below).
label: a string for the widget's label.  If it contains '_', it is treated as
       using underline.
tooltip: tooltip to show when hovering over the widget.
data: data that affects the behaviour of the setting; if the required
           value in the list below is not specified, this is ignored.
cb: a function that is passed the running Editor instance, setting_ID and the
    new value of the setting when it is changed (None for types with no value).
    Returns True to indicate that updating the setting has been handled (or
    should not be handled); otherwise, it is automatically updated based on its
    type (does nothing for types with no value).

    Alternatively, update_cb can be the name of a method of Editor to call that
    with setting_ID and the value (and handle its return value in the same
    manner).  If this argument is None or not given, the setting is just
    automatically updated.
on_change: whether to call update_cb (and/or perform automatic setting update)
           when the widget is changed (otherwise only do so when the
           preferences is closed); defaults to conf.UPDATE_ON_CHANGE.
sensitive: a list of (setting_ID, value) tuples, where the widget is only
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


_default_widget_data = {'label': None, 'tooltip': None, 'data': None,
                        'cb': None, 'on_change': conf.UPDATE_ON_CHANGE,
                        'sensitive': ()}

_cb = lambda e, i, v: True
_widgets = {
    # interface
    'sel_on_drag': {
        't': 'bool',
        'label': '_Drag to select files',
        'tooltip': 'Otherwise dragging moves or copies files, even if they ' \
                   'are not already selected',
        'cb': _cb
    },
    'warnings': {
        't': 'button',
        'data': '_Re-enable all warnings',
        'cb': _cb
    },
    # trash
    'trash_enabled': {
        't': 'bool',
        'label': '_Enable trash',
        'cb': _cb,
        'on_change': False
    },
    'trash_location': {
        't': 'dir',
        'label': 'Trash _location:',
        'cb': _cb,
        'on_change': False,
        'sensitive': [('trash_enabled', True)]
    },
    'trash_size': {
        't': 'int',
        'label': 'Maximum _size:',
        'data': (1, 1023, 1, ('KiB', 'MiB', 'GiB')),
        'cb': _cb,
        'on_change': False,
        'sensitive': [('trash_enabled', True)]
    },
    # advanced
    'set_tmp_dir': {
        't': 'bool',
        'label': '_Set a specific directory to use for temporary files',
        'tooltip': 'Otherwise the location is decided automatically'
    },
    'tmp_dir': {
        't': 'dir',
        'label': '_Directory to use:',
        'sensitive': [('set_tmp_dir', True)]
    },
    'simul_rw': {
        't': 'choice',
        'label': '_Read and write data simultaneously:',
        'tooltip': 'If automatic, do so when the source and destination ' \
                   'files are on different disks',
        'data': ('automatic', 'always', 'never')
    },
    'block_size': {
        't': 'int',
        'label': 'Read and write in _blocks of:',
        'data': (1, 1023, 1, ('B', 'KiB', 'MiB'))
    }
}


def _update_widgets (editor, *ws, from_cb = False):
    """Call widget"""
    for setting_id, w, t, cb in ws:
        # get setting value
        if t == 'button':
            v = None
        elif t == 'text':
            v = w.get_text()
        elif t == 'bool':
            v = w.get_active()
        elif t == 'dir':
            v = w.fn
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

def _gen_widget (editor, setting_id, t, label, tooltip, data, cb, on_change,
                 sensitive):
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
        w = NonFailFileChooserButton(
            gtk.FileChooserAction.SELECT_FOLDER, settings[setting_id],
            'Choose a directory', _cb_wrapper, (editor, setting_id, t, cb)
        )
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
              'dir': None, 'int': 'value-changed',
              'choice': 'changed'}[t]
    if on_change and signal is not None:
        w.connect(signal, _cb_wrapper, (editor, setting_id, t, cb))
    try:
        real_w
    except NameError:
        real_w = w
    # tooltip
    if tooltip is not None:
        real_w.set_tooltip_text(tooltip)
    return real_w, w

def gen_widgets (editor):
    """Generate widgets for all settings.

gen_widgets(editor) -> (widgets, cb)

editor: the running Editor instance.

widgets: a setting_ID: widget dict for all settings.
cb: a function to call to update some settings when the preferences window is
closed.

"""
    ws = {}
    on_close = []
    for setting_id, got_data in _widgets.items():
        data = dict(_default_widget_data)
        data.update(got_data)
        real_w, w = _gen_widget(editor, setting_id, **data)
        ws[setting_id] = real_w
        if not data['on_change']:
            on_close.append((setting_id, w, data['t'], data['cb']))
    if on_close:
        # call remaining callbacks on preferences close
        cb = lambda: _update_widgets(editor, *on_close)
    else:
        cb = lambda: None
    return ws, cb

"""

_prefs is a list of tabs, which are (title, items) tuples.  Titles may contain '_' to use underline.  Items is a list containing headings, standalone labels
and settings.  A heading is (heading_text, None), a label is
(label_text, use_markup) and a setting is the setting ID.

"""

_prefs = (
    ('_Interface', ('sel_on_drag', 'warnings')),
    ('_Trash', (('The trash directory is used to save files that are ' \
                 'deleted from disk images.  Note that disabling the trash ' \
                 'or reducing its size may <b>permanently delete</b> items ' \
                 'to fit the new settings.', True),
                'trash_enabled', 'trash_location', 'trash_size')),
    ('_Advanced', ('set_tmp_dir', 'tmp_dir', 'simul_rw', 'block_size'))
)


class NonFailFileChooserButton (gtk.Button):
    """A FileChooserButton that doesn't fail.  Gtk.Button subclass.

    CONSTRUCTOR

NonFailFileChooserButton(action, fn[, title][, changed_cb, *cb_args])

action: a Gtk.FileChooserAction.
fn: initial file (or directory) path.
title: title of Gtk.FileChooserDialog window.
changed_cb: function to call with this instance then *cb_args when the stored
            file path is changed by the user.

    ATTRIBUTES

action, title, changed_cb, cb_args: as given.
fn: as given; changes to match the new path when the user chooses one (the
    change is made before changed_cb is called).

"""
    def __init__ (self, action, fn, title = None, changed_cb = None, *cb_args):
        self.action = action
        self.fn = fn
        self.title = title
        self.changed_cb = changed_cb
        self.cb_args = cb_args
        # create button
        gtk.Button.__init__(self)
        self.update_label()
        a = gtk.FileChooserAction
        icon = gtk.STOCK_FILE if action in (a.OPEN, a.SAVE) else \
               gtk.STOCK_DIRECTORY
        img = gtk.Image.new_from_stock(icon, gtk.IconSize.BUTTON)
        self.set_image(img)
        self.connect('clicked', self.popup)

    def update_label (self):
        """Update the button label to the current path."""
        self.set_label(os.path.basename(self.fn))

    def popup (self, *args):
        """Show the Gtk.FileChooserDialog window."""
        # create dialogue
        a = gtk.FileChooserAction
        if self.action == a.SAVE:
            ok_btn = gtk.STOCK_SAVE
        else:
            ok_btn = gtk.STOCK_OK
        rt = gtk.ResponseType
        buttons = (gtk.STOCK_CLOSE, rt.CLOSE, ok_btn, rt.OK)
        d = gtk.FileChooserDialog(self.title, self.get_toplevel(),
                                  self.action, buttons)
        # run
        d.set_filename(self.fn)
        if self.action in (a.SAVE, a.CREATE_FOLDER):
            d.set_current_name(os.path.basename(self.fn))
        if d.run() == rt.OK:
            fn = d.get_filename()
            if fn != self.fn:
                # filename changed
                self.fn = fn
                self.update_label()
                if self.changed_cb is not None:
                    self.changed_cb(self, *self.cb_args)
        d.destroy()


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
        for tab, items in _prefs:
            page = gtk.Grid()
            page.set_row_spacing(6)
            page.set_column_spacing(6)
            page.set_border_width(12)
            l = gtk.Label(tab)
            l.set_use_underline('_' in tab)
            tabs.append_page(page, l)
            y = 0
            items = list(items) # might be modified
            done_spacer = False
            for item in items:
                do_spacer = not done_spacer
                # if first item isn't a heading, show tab name as heading
                if y == 0 and (isinstance(item, str) or item[1] is not None):
                    # add this item back to the list first
                    items.insert(1, item)
                    item = (tab.replace('_', ''), None)
                if not isinstance(item, str):
                    text, markup = item
                    if markup is None:
                        # heading
                        l = gtk.Label('<b>{}</b>'.format(text))
                        page.attach(l, 0, y, 3, 1)
                        l.set_use_markup(True)
                        if y != 0:
                            l.set_margin_top(6)
                        do_spacer = False
                    else:
                        # label
                        l = gtk.Label(text)
                        page.attach(l, 1, y, 2, 1)
                        l.set_use_markup(markup)
                        l.set_line_wrap(True)
                    l.set_alignment(0, .5)
                else:
                    # setting
                    w = self._widgets[item]
                    w_x = 1
                    w_w = 2
                    data = _widgets[item]
                    try:
                        label = data['label']
                    except KeyError:
                        pass
                    else:
                        # got a label; checkbox has own label
                        if data['t'] == 'bool':
                            w.set_label(label)
                            w.set_use_underline('_' in label)
                        else:
                            l = gtk.Label(label)
                            l.set_alignment(0, .5)
                            l.set_use_underline('_' in label)
                            if isinstance(w, gtk.Box):
                                l.set_mnemonic_widget(w.get_children()[0])
                            else:
                                l.set_mnemonic_widget(w)
                            page.attach(l, 1, y, 1, 1)
                            w_x = 2
                            w_w = 1
                            # set widget's tooltip on label too
                            try:
                                tooltip = data['tooltip']
                            except KeyError:
                                pass
                            else:
                                l.set_tooltip_text(tooltip)
                    page.attach(w, w_x, y, w_w, 1)
                    w.set_hexpand(True)
                    w.set_halign(gtk.Align.START)
                if do_spacer:
                    # HACK: there's no way to set a single column's width?
                    i = gtk.Box()
                    page.attach(i, 0, y, 1, 1)
                    i.set_border_width(3) # 2 * 3 + 6 (column spacing) = 12
                    done_spacer = True
                y += 1
        self.show_all()

    def quit (self, *args):
        """Clean up and hide the window."""
        self._end_cb()
        self.hide()
        return True