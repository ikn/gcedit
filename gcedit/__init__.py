import sys
from os import path
from gettext import install

# get locale dir: should be gcedit/locale
if not hasattr(sys, 'frozen'):
    # under this file's dir
    pkg_dir = path.dirname(__file__)
else:
    # or, if frozen, under the gcedit in the executable's dir
    pkg_dir = path.join(path.dirname(sys.executable), 'gcedit')
locale_dir = path.join(pkg_dir, 'locale')
install('gcedit', locale_dir, names = ('ngettext',))