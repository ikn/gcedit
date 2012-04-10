"""gcedit configuration module.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

    DATA

settings: dict-like object to handle settings.

"""

import os
import json

from gi.repository import Gtk as gtk

# TODO: different values on Windows
HOME = os.path.expanduser('~')
CONF = os.path.join(HOME, '.config', 'gcedit')
SHARE = os.path.join(HOME, '.local', 'gcedit')

APPLICATION = 'GCEdit'
IDENTIFIER = 'gcedit'
UPDATE_ON_CHANGE = True
SLEEP_INTERVAL = .02
INVALID_FN_CHARS = ({b'/'}, {'/'})

_defaults = {
    # interface
    'win_size': (400, 450),
    'win_max': False,
    'import_path': HOME, # use, set
    'extract_path': HOME, # use, set
    'sel_on_drag': True, # set
    'warnings': {}, # use, set
    # trash
    'trash_enabled': True, # use, set
    'trash_location': os.path.join(SHARE, 'trash'), # use, set
    'trash_size': (50, 1), # 50MiB # use, set
    # advanced
    'set_tmp_dir': False, # use
    'tmp_dir': HOME, # use
    'simul_rw': 0, # use
    'block_size': (1, 2) # 1MiB # use
}

_types = {
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
    'trash_size': list,
    # advanced
    'set_tmp_dir': bool,
    'tmp_dir': str,
    'simul_rw': int,
    'block_size': list
}


class _SettingsManager (dict):
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
            v = _types[k](v)
        except (TypeError, ValueError):
            v = self.defaults[k]
        return v

    def __setitem__ (self, k, v):
        v = _types[k](v)
        if v == self[k]:
            # no change
            return
        dict.__setitem__(self, k, v)
        try:
            with open(self.fn, 'w') as f:
                json.dump(self, f, indent = 4)
        except IOError:
            pass


settings = _SettingsManager(CONF, _defaults)