"""gcedit configuration module.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

    FUNCTIONS

set
get
store
retrieve

"""

import os
import json

HOME = os.path.expanduser('~')
CONF = os.path.join(HOME, '.config', 'gcedit')
SHARE = os.path.join(HOME, '.local', 'gcedit')

UPDATE_ON_CHANGE = True

"""

widgets is a data structure defining settings to automatically build the
preferences widgets; it is a dict with setting_ID keys and
    (setting_type[, type_args][, update_cb][, update_on_close])
values.

setting_ID: ID used in the settings data structure.
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
                 when the preferences is closed); defaults to UPDATE_ON_CHANGE.

Setting types are:

button: takes the label, which is assumed to be stock if it starts with 'gtk-';
        otherwise, it is assumed to use underline if it contains '_'.  This
        type has no value.
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

CB = None
widgets = {
    # interface
    'sel_on_drag': ('bool', None, CB),
    'warnings': ('button', 'Re-enable all warnings', CB),
    # trash
    'trash_enabled': ('bool', None, CB, False),
    'trash_location': ('dir', None, CB, False),
    'trash_size': ('int', (1, 1023, 1, ('KiB', 'MiB', 'GiB')), CB, False),
    # backend
    'tmp_dir': ('dir',),
    'simul_rw': ('choice', ('automatic', 'always', 'never')),
    'block_size': ('int', (1, 1023, 1, ('B', 'KiB', 'MiB')))
}

defaults = {
    # interface
    'win_size': (400, 450),
    'win_max': False,
    'import_path': HOME,
    'extract_path': HOME,
    'sel_on_drag': True,
    'warnings': {},
    # trash
    'trash_enabled': True,
    'trash_location': os.path.join(SHARE, 'trash'),
    'trash_size': 50 * 1024 ** 2, # 50MiB
    # backend
    'tmp_dir': '', # empty string means use tempfile module
    'simul_rw': 'automatic',
    'block_size': 1024 ** 2 # 1MiB
}

types = {
    # interface
    'win_size': list,
    'win_max': bool,
    'import_path': str,
    'extract_path': str,
    'sel_on_drag': bool,
    'warnings': dict,
    # trash
    'trash_enabled': bool,
    'trash_location': str,
    'trash_size': int,
    # backend
    'tmp_dir': str,
    'simul_rw': str,
    'block_size': int
}

class SettingsManager (dict):
    """A dict subclass for handling settings.

Takes file to store settings in and a dict of default values for settings.  All
possible settings are assumed to be in this dict.

"""

    def __init__ (self, fn, defaults):
        self.fn = fn
        self.defaults = defaults
        try:
            with open(self.fn) as f:
                settings = json.load(f)
        except (IOError, ValueError):
            settings = {}
        settings = dict((k, settings.get(k, v)) for k, v in defaults.items())
        dict.__init__(self, settings)

    def __getitem__ (self, k):
        v = dict.__getitem__(self, k)
        try:
            v = types[k](v)
        except (TypeError, ValueError):
            v = self.defaults[k]
        return v

    def __setitem__ (self, k, v):
        v = types[k](v)
        if v == self[k]:
            # no change
            return
        dict.__setitem__(self, k, v)
        try:
            with open(self.fn, 'w') as f:
                json.dump(self, f, indent = 4)
        except IOError:
            pass

settings_manager = SettingsManager(CONF, defaults)