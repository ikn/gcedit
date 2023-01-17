GCEdit 0.4.3.

A GameCube disk editor.

http://ikn.org.uk/app/gcedit

# License

Distributed under the terms of the
[GNU General Public License, version 3](http://www.gnu.org/licenses/gpl-3.0.txt).

# Installation

Build dependencies:
- [Setuptools](https://setuptools.readthedocs.io/en/latest/)
- [Bash](https://www.gnu.org/software/bash/)

There is no installation method on Windows.

Run `make`, `make install`.  The usual `DESTDIR`, etc. arguments to `make` are
supported.

# Dependencies

- [Python 3](http://www.python.org) (>= 3.2)
- [PyGObject 3](https://live.gnome.org/PyGObject) (>= 3.11)

# Usage

On Unix-like OSs, once installed, just run `gcedit` (installed to
/usr/local/bin/ by default).

On Windows, in the source directory, run `python3 run_gcedit`, where `python3`
is the Python 3 interpreter.

# Files

GCEdit creates some files during operation.  On Unix-like OSs:

- ~/
    - .config/gcedit/
        - conf: configuration
        - accels: saved keyboard shortcuts
    - .local/share/gcedit/
        - disk_history: recently opened disks
        - search_history: saved searches

On Windows:

- %APPDATA%/
    - gcedit/
        - conf: configuration
        - accels: saved keyboard shortcuts
        - disk_history: recently opened disks
        - search_history: saved searches
