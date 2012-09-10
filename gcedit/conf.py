"""gcedit configuration module.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

    FUNCTIONS

read_lines
write_lines

    DATA

settings: dict-like object to handle settings.

"""

from platform import system
import os
from os.path import join as join_path
import json

from gi.repository import Gtk as gtk

IDENTIFIER = 'gcedit'

if system() == 'Windows':
    HOME = os.environ['USERPROFILE']
    SHARE = join_path(os.environ['APPDATA'], IDENTIFIER)
    CONF_DIR = SHARE
    CONF = join_path(CONF_DIR, 'conf')
else:
    HOME = os.path.expanduser('~')
    SHARE = join_path(HOME, '.local', 'share', IDENTIFIER)
    CONF_DIR = join_path(HOME, '.config', IDENTIFIER)
    CONF = join_path(CONF_DIR, 'conf')

for d in set((SHARE, CONF_DIR)):
    try:
        os.makedirs(d, exist_ok = True)
    except OSError:
        print('warning: can\'t create directory: \'{}\''.format(d))

APPLICATION = _('GCEdit')
VERSION = '0.4.0'
UPDATE_ON_CHANGE = True
SLEEP_INTERVAL = .02
INVALID_FN_CHARS = ({b'/'}, {'/'})
PROGRESS_SPEED_SMOOTHING = .7
PROGRESS_SPEED_UPDATE_INTERVAL = 3

_defaults = {
    # automatic/interface
    'win_size_main': (450, 450),
    'win_max_main': False,
    'import_path': HOME,
    'extract_path': HOME,
    # automatic/interface/loader
    'win_size_loader': (600, 300),
    'win_max_loader': False,
    'loader_path': HOME,
    # automatic/interface/search
    'win_size_search': (600, 300),
    'win_max_search': False,
    'search_options_hidden': True,
    'case_sensitive': False,
    'whole_name': False,
    'dirs': True,
    'files': True,
    'regex': False,
    # exposed/interface
    'sel_on_drag': True,
    'autoclose_progress': False,
    'close_search': False,
    'disabled_warnings': set(),
    # exposed/trash
    'trash_enabled': True,
    'trash_location': join_path(SHARE, 'trash'),
    'trash_size': (50, 1), # 50MiB
    # exposed/advanced
    'set_tmp_dir': False,
    'tmp_dir': HOME,
    'block_size': (1, 2), # 1MiB
    'search_hist_limited': True,
    'search_hist_size': 100
}

_types = {
    # automatic/interface
    'win_size_main': list,
    'win_max_main': bool,
    'import_path': str,
    'extract_path': str,
    # automatic/interface/loader
    'win_size_loader': list,
    'win_max_loader': bool,
    'loader_path': str,
    # automatic/interface/search
    'win_size_search': list,
    'win_max_search': bool,
    'search_options_hidden': bool,
    'case_sensitive': bool,
    'whole_name': bool,
    'dirs': bool,
    'files': bool,
    'regex': bool,
    # exposed/interface
    'autoclose_progress': bool,
    'sel_on_drag': bool,
    'close_search': bool,
    'disabled_warnings': set,
    # exposed/trash
    'trash_enabled': bool,
    'trash_location': str,
    'trash_size': list,
    # exposed/advanced
    'set_tmp_dir': bool,
    'tmp_dir': str,
    'block_size': list,
    'search_hist_limited': bool,
    'search_hist_size': int
}

def read_lines (fn):
    """Read a file's lines into a list of strings.

Takes the filename under conf.SHARE.

"""
    l = []
    try:
        with open(join_path(SHARE, fn)) as f:
            m = f.readlines()
    except IOError:
        pass
    else:
        for s in m:
            s = s.strip()
            if s:
                l.append(s)
    return l

def write_lines (fn, l):
    """Read a list of strings to a file as separate lines.

Takes the filename under conf.SHARE and the list of strings.

"""
    fn = join_path(SHARE, fn)
    print('info: writing to file: \'{}\''.format(fn))
    try:
        with open(fn, 'w') as f:
            f.write('\n'.join(l))
    except IOError:
        print('warning: can\'t write to file: \'{}\''.format(fn))

def mru_add (l, x):
    """Add an item to a most-recently-used list.

mru_add(l, x) -> (changed, new)

If x is in l, it is moved to the end; if not, it is appended.

changed: whether was l changed.
new: whether x was not already in l.

"""
    changed = False
    new = False
    try:
        i = l.index(x)
    except ValueError:
        # new
        l.append(x)
        changed = True
        new = True
    else:
        # already in the list: move to end to indicate recent use
        if i != len(l) - 1:
            l.append(l.pop(i))
            changed = True
    return (changed, new)


class _JSONEncoder (json.JSONEncoder):
    """Extended json.JSONEncoder with support for sets."""

    def default (self, o):
        if isinstance(o, set):
            return list(o)
        else:
            return json.JSONEncoder.default(self, o)


class _SettingsManager (dict):
    """A dict subclass for handling settings.

Takes file to store settings in and a dict of default values for settings.  All
possible settings are assumed to be in this dict.  Setting a value may raise
TypeError or ValueError if the value is invalid.

To restore a setting to its default value, set it to None.

"""

    def __init__ (self, fn, defaults):
        self.fn = fn
        self.defaults = defaults
        settings = {}
        try:
            with open(self.fn) as f:
                settings = json.load(f)
        except IOError:
            pass
        except ValueError:
            print('warning: invalid settings file')
        settings = dict((k, settings.get(k, v)) for k, v in defaults.items())
        dict.__init__(self, settings)

    def __getitem__ (self, k):
        v = dict.__getitem__(self, k)
        try:
            v = _types[k](v)
        except (KeyError, TypeError, ValueError):
            v = self.defaults[k]
        return v

    def __setitem__ (self, k, v):
        # restore to default if None
        if v is None:
            v = self.defaults[k]
        else:
            v = _types[k](v)
            if v == self[k]:
                # no change
                return
        print('info: saving setting: \'{}\''.format(k))
        dict.__setitem__(self, k, v)
        try:
            with open(self.fn, 'w') as f:
                json.dump(self, f, indent = 4, cls = _JSONEncoder)
        except IOError:
            print('warning: can\'t write to file: \'{}\''.format(self.fn))


settings = _SettingsManager(CONF, _defaults)
