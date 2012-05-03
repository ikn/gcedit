import sys
from platform import system
from os import path
from gettext import install

# get locale dir: should be in the same dir as this file
if hasattr(sys, 'frozen'):
    # or, if frozen, in gcedit
    module_dir = path.join(path.dirname(sys.executable), 'gcedit')
else:
    module_dir = path.dirname(__file__)
locale_dir = path.join(module_dir, 'locale')
install('gcedit', locale_dir, names = ('ngettext',))