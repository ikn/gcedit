"""GameCube file utilities.

Python version: 3.
Release: 7-dev.

Licensed under the GNU General Public License, version 3; if this was not
included, you can find it here:
    http://www.gnu.org/licenses/gpl-3.0.txt

    CLASSES

GCFS

    FUNCTIONS

read
write
copy
tree_from_dir

    SETTINGS

(Change these as attributes of this module.)

CODEC = 'shift_jis': the string encoding to use for filenames in the disk
                     image.  (Shift JIS seems to be right, but maybe you've
                     got a disk that uses something else.)
BLOCK_SIZE = 0x100000: the maximum amount of data, in bytes, to read and write
                       at a time (0x100000 is 1MiB).

[NOT IMPLEMENTED]

THREADED = None: whether to use threads to read and write data simultaneously.
                 Possible values are:
    True: always have one thread reading and one writing.
    False: just use one thread.
    None: have as many threads as possible where each is reading from or
          writing to a different physical disk.
PAUSED_WAIT = .5: in functions that take a progress function, if the action is
                  paused, the function waits this many seconds between
                  subsequent calls to the progress function.

"""

# TODO:
# - decompress function
# - BNR support
# - pause/cancel in copy (return value on cancel?)
# - remaining time estimation
# - when write and add files (and maybe other places), sort files by position
#   on disk before adding (should be quicker, and else is sorted by filesize so
#   appears to slow down towards end when doing loads of small files)
# - threaded

import os
from os.path import getsize, exists, dirname, basename
from copy import deepcopy
from shutil import rmtree
import tempfile

CODEC = 'shift-jis'
BLOCK_SIZE = 0x100000
THREADED = None
PAUSED_WAIT = .5

_decode = lambda b: b.decode(CODEC)
_encode = lambda s: s.encode(CODEC)
_decoded = lambda s: _decode(s) if isinstance(s, bytes) else s
_sep = lambda s: _encode(os.sep) if isinstance(s, bytes) else os.sep

def _join (*dirs):
    """Like os.path.join, but handles mismatched bytes/str args."""
    return os.sep.join(_decode(d) if isinstance(d, bytes) else d for d in dirs)

def valid_name (name):
    """Check whether a file/directory name is valid.

Takes the name to check, which can be str or bytes, and returns whether it is
valid.  A valid name can be safely added to the tree of a GCFS instance.

"""
    if (b'\0', '\0')[isinstance(name, str)] in name:
        return False
    try:
        (_encode if isinstance(name, str) else _decode)(name)
    except (UnicodeEncodeError, UnicodeDecodeError):
        return False
    else:
        return True

def read (f, start, size = None, num = False, until = None, block_size = 0x10):
    """Read data from a file object.

read(f, start[, size], num = False[, until, block_size = 0x10]) -> data

f: the file object to read from (open in binary mode).
start: position to start reading from.
size: amount of data to read.  until must be passed if this is not.  Even if
      you pass until, it's a good idea to give some upper limit here in case
      there's an error and the character is never found (to avoid reading in
      the whole file).
num: if True, treat the whole of the data read as a base 256 integer and
     convert it to base 10.
until: if this character (length-1 bytes object) is found, truncate the result
       and stop reading; or a function that gets passed a string of read bytes
       (with length block_size) and returns True to continue reading, else an
       integer to stop reading and keep that many bytes from the string.
block_size: amount to read between checks for this character.

Data is always measured in bytes.

"""
    f.seek(start)
    if until is None:
        if size is None:
            raise ValueError('expected size argument')
        data = f.read(size)
    else:
        # truncate until to one char
        if isinstance(until, bytes):
            until = until[:1]
        data = b''
        left = size or -1
        while left:
            # left < 0 means just keep going until the character is found
            new = block_size if left < 0 else min(block_size, left)
            new_data = f.read(new)
            if isinstance(until, bytes):
                char = new_data.find(until)
                if char == -1:
                    data += new_data
                    if len(new_data) < new:
                        # didn't get all the bytes we asked for: EOF
                        left = 0
                    else:
                        left -= new
                else:
                    # found character: stop reading
                    data += new_data[:char]
                    left = 0
            else:
                # until should be a function
                do = until(new_data)
                if isinstance(do, int):
                    # keep this many characters and stop
                    new_data = new_data[:min(max(do, 0), new)]
                    left = 0
                elif do is not True:
                    raise ValueError('until should only return True or an int')
    if num:
        size = len(data)
        data = sum(j * 256 ** (size - i - 1) for i, j in enumerate(data))
    return data

def write (data, f, pos, size = None):
    """Copy data to a file object.

write(data, f, pos[, size])

data: the data to copy.  This can be a bytes object, or an int to convert to
      base 256, ie. a bytes object.
f: the file object to write to (open in binary/write mode).
pos: position to start writing to.
size: if converting from an int, pad it to this size in bytes by prepending by
      0s.  The data will not be truncated if longer than this.

"""
    if isinstance(data, int):
        # convert to bytes
        i = data
        data = []
        while i:
            data.insert(0, i % 256)
            i //= 256
        data = b'\0' * max(size - len(data), 0) + bytes(data)
    f.seek(pos)
    f.write(data)

def copy (files, progress = None, names = None, overwrite = True):
    """Copy a file to a file object.

copy(files[, progress, names], overwrite = True) -> failed

files: a list of (source, dest) tuples to copy from source to dest.  source is
       (filename, file, start, size) and dest is (filename, file, start),
       where, in each case, file is a file object file_obj open in binary
       read/write mode, or None if this function should open the file.  If a
       file object is given to write to, it will not be truncated so that it is
       large enough to be able to seek to start.

       file, start and size may be omitted: file defaults to None, start
       defaults to 0 and size defaults to (file_size - start).  If all three
       are omitted, source/dest can be just filename.
progress: a function to periodically pass the current progress to.  It takes 3
          arguments: the amount of data that has been copied in bytes, the
          total amount of data to copy in bytes, and the name of the current
          file (in the disk's filesystem) being read/written (str not bytes).

          In higher-level functions that take this argument, there is a period
          of time before any calls are made to this function, in which the
          total amount to copy is unknown.  In, for example, GCFS.write, this
          passed function may never be called - if, for example, all you are
          doing is creating directories or deleting files.

          [NOT IMPLEMENTED]
          You can pause the copy by returning 1.  This function will then call
          progress periodically until the return value is no longer 1.  The
          progress function is only called between every block/file copied -
          this gives an idea of how quickly a running copy can be paused.

          [NOT IMPLEMENTED]
          You can try to cancel the copy by returning 2.  If it can still be
          safely canceled, some cleanup will be performed and the function
          will return.
names: a list filenames corresponding to elements of the files list to pass to
       progress as the third argument, or 0 or 1 to use the names of the src or
       dest files respectively.
overwrite: whether to overwrite any destination files that exist (if False and
           a file exists, it will be in the failed list).  Of course, this only
           makes sense for files where only the filename and not the open file
           is given.

failed: a list of indices in the given files list for copies that failed.

"""
    string = (bytes, str)
    if progress is None and isinstance(names, int):
        # fill out names
        names = [basename(f[names][0]) for f in files]
    # make every src/dest a list
    to_copy = []
    for src, dest in files:
        if isinstance(src, string):
            src = [src]
        else:
            src = list(src)
        if isinstance(dest, string):
            dest = [dest]
        else:
            dest = list(dest)
        to_copy.append((src, dest))
    # get file sizes/locations
    files = {(f[0], i // 2) for i, f in enumerate(sum(to_copy, ()))}
    sizes = {}
    locations = {}
    sep = os.sep
    for f, i in files:
        try:
            stat = os.stat(f)
        except OSError:
            sizes[f] = 0
            # use first existing parent for location instead
            p = os.path.abspath(f)
            while True:
                try:
                    p = dirname(p)
                    stat = os.stat(p)
                except OSError:
                    if not p.strip(sep):
                        # ...no parent exists, somehow
                        # it'll just fail later, so location doesn't matter
                        print(f)
                        locations[f] = -1
                        break
                else:
                    locations[f] = stat.st_dev
                    break
        else:
            sizes[f] = stat.st_size
            locations[f] = stat.st_dev
    # fill in default values
    total_size = 0
    for src, dest in to_copy:
        if len(src) == 1:
            src.append(None)
        if len(src) == 2:
            src.append(0)
        if len(src) == 3:
            src.append(sizes[src[0]] - src[2])
        total_size += src[3]
        if len(dest) == 1:
            dest.append(None)
        if len(dest) == 2:
            dest.append(0)
    # actual copy
    THREADED = False
    failed = []
    if THREADED:
        pass
    else:
        total_done = 0
        progress_update = BLOCK_SIZE
        for i, (src, dest) in enumerate(to_copy):
            src_fn, src_f, src_start, size = src
            src_open = src_f is None
            dest_fn, dest_f, dest_start = dest
            dest_open = dest_f is None
            try:
                # open files
                if src_open:
                    src_f = open(src_fn, 'rb')
                if dest_open:
                    if not overwrite and exists(dest_fn):
                        # exists and don't want to overwrite
                        failed.append(i)
                        continue
                    dest_f = open(dest_fn, 'wb')
                # seek
                same = src_f is dest_f
                if not same:
                    src_f.seek(src_start)
                    dest_f.seek(dest_start)
                # copy
                done = 0
                while size:
                    if progress is not None and total_done >= progress_update:
                        progress(total_done, total_size, names[i])
                        progress_update += BLOCK_SIZE
                    amount = min(size, BLOCK_SIZE)
                    if same:
                        src_f.seek(src_start + done)
                    data = src_f.read(amount)
                    if same:
                        dest_f.seek(dest_start + done)
                    dest_f.write(data)
                    size -= amount
                    done += amount
                    total_done += amount
            except IOError:
                failed.append(i)
                continue
            finally:
                # clean up
                if src_open and src_f is not None:
                    src_f.close()
                if dest_open and dest_f is not None:
                    dest_f.close()
    return failed

def tree_from_dir (root, walk_iter = None):
    """Build a tree from a directory on the real filesystem.

This returns a dict in the same format as the tree attribute of GCFS objects.
That is, you can place it directly in such a tree to import lots of files.

"""
    tree = {}
    if walk_iter is None:
        walk_iter = os.walk(root)
    try:
        path, dirs, files = next(walk_iter)
    except StopIteration:
        # seems to indicate a dir we don't have read access to
        tree[None] = []
    else:
        # files
        tree[None] = [(f, _join(path, f)) for f in files]
        # dirs
        for d in dirs:
            tree[(d, None)] = tree_from_dir(d, walk_iter)
    return tree


class GCFS:
    """Read from and make changes to a GameCube image's filesystem.

To make changes to the tree, edit data in the tree attribute directly.  To undo
all changes, call the build_tree method.  The entries and names attributes
reflect what is actually in the image, and will only change when the write
method is called.

To import a directory tree from the real filesystem, use the tree_from_dir
function in this module and place the result in the tree attribute, or
replace the whole tree if you want to import an entire GameCube filesystem.

    CONSTRUCTOR

GCFS(fn)

fn: file path to the image file.

    METHODS

build_tree
update
disk_changed
changed
get_info
get_file_tree_locations
get_extra_files
extract_extra_files
extract
write
compress

    ATTRIBUTES

fn: as given.
fs_start: position in the image at which the filesystem starts.
fst_size: image's filesystem table (includes string table) size in bytes.
num_entries: number of entries in the filesystem.
str_start: position in the image at which the string table starts.
entries: a list of file table entries; each is an
         (is_dir, str_start, start, size) tuple, where:
    is_dir: whether this is a directory.
    str_start: offset of this entry's name in the string table.
    start: offset of this file in the filesystem, or position of this
           directory's parent directory in the table (first entry is 1, root
           directory is 0).
    size: file size in bytes, or for a directory, position of the next
          file/directory in the table that is not a child (or child of a child,
          etc.) of this one.  The root entry is not included.  Files (and
          directories) follow the directory they are in.
names: a list of filenames corresponding to the entries.
tree: a dict representing the root directory.  Each directory is a dict whose
      keys are directory identifiers for child directories, and with None the
      key for a list of file identifiers.  That is:

    {id1: {id2: {...}, ...}, ..., None: [id3, ...]}

      In each case, an identifier is (name, index), where:
    name: the directory/file's (current) name.  Any names added to the tree
          must be shift-JIS-encoded bytes instances, or str instances that can
          be encoded with shift-JIS (see the valid_name function).
    index: the index in the entries list if the file/directory is already in
           the image's filesystem, else (for items yet to be added) None for a
           directory, or the real filesystem path for a file.
"""

    def __init__ (self, fn):
        self.fn = str(fn)
        # read data from the disk
        self.update()

    def _init (self):
        """Read and store data from the disk."""
        with open(self.fn, 'rb') as f:
            self.fs_start = fs_start = read(f, 0x424, 0x4, True)
            self.fst_size = read(f, 0x428, 0x4, True)
            self.num_entries = read(f, self.fs_start + 0x8, 0x4, True)
            self.str_start = str_start = self.fs_start + self.num_entries * 0xc
            # get file data
            self.entries = entries = []
            for i in range(1, self.num_entries):
                # get entry offset
                entry_offset = fs_start + i * 0xc
                # is_dir, str_offset, start, size
                args = ((0x0, 0x1), (0x1, 0x3), (0x4, 0x4), (0x8, 0x4))
                data = [read(f, entry_offset + offset, size, True)
                        for offset, size in args]
                data[0] = bool(data[0])
                entries.append(tuple(data))
            # get filenames
            self.names = names = []
            for entry in entries:
                # only read 512 chars for safety
                name = read(f, str_start + entry[1], 0x200, False, b'\0', 0x20)
                names.append(_decode(name))

    def _tree_size (self, tree, file_size = False):
        """Get the number of children in a tree.

_tree_size(tree, file_size = False)

tree: the tree.
file_size: whether to return the total file size of the children in the tree
           instead.  Imported files are respected (if they cannot be accessed,
           they are ignored).

"""
        size = 0
        for k, v in tree.items():
            if k is None:
                # files
                if file_size:
                    entries = self.entries
                    for name, i in v:
                        if isinstance(i, int):
                            size += entries[i][3]
                        else:
                            try:
                                size += getsize(i)
                            except OSError:
                                pass
                else:
                    size += len(v)
            else:
                # dir
                if not file_size:
                    size += 1
                size += self._tree_size(v, file_size)
        return size

    def build_tree (self, store = True, start = 0, end = None):
        """Build the directory tree from the current entries list.

build_tree(store = True, start = 0[, end]) -> tree

store: whether to store the built tree in the tree attribute.
start: the entry to start at.
end: the index of the entry to stop at (this one is not included).  Defaults to
     len(entries).

tree: the built tree.

"""
        entries = list(self.entries)
        names = self.names
        start = max(start, 0)
        if end is None:
            end = len(entries)
        end = min(end, len(entries))
        # create tree with empty file list
        children = []
        tree = {None: children}
        # populate it
        i = start
        while i < end:
            is_dir, str_offset, start, size = entries[i]
            name = names[i]
            if is_dir:
                # build as a separate tree
                tree[(name, i)] = self.build_tree(False, i + 1, size - 1)
                i = size - 1
            else:
                # add file list
                children.append((name, i))
                i += 1
        if store:
            self.tree = tree
        return tree

    def update (self):
        """Re-read data from the disk.  Discards all changes to the tree."""
        self._init()
        # build tree
        self.tree = self.build_tree()

    def disk_changed (self, update = False):
        """Return whether changes have been made to the disk.

This checks the filesystem table, but not the files themselves.

"""
        attrs = ('fs_start', 'fst_size', 'num_entries', 'str_start', 'entries',
                 'names')
        # store data
        for attr in attrs:
            setattr(self, '_' + attr, getattr(self, attr))
        # read new data
        self._init()
        # compare
        changed = False
        for attr in attrs:
            if getattr(self, attr) != getattr(self, '_' + attr):
                changed = True
                break
        # revert old data
        for attr in attrs:
            setattr(self, attr, getattr(self, '_' + attr))
            delattr(self, '_' + attr)
        return changed

    def changed (self):
        """Return whether changes have been made since the last write.

This checks whether the this instance's tree attribute still corresponds to the
most recently loaded filesystem data.

"""
        return self.tree != self.build_tree(False)

    def get_info (self):
        """Get basic information about a GameCube image.

Returns a dict containing 'code', 'version' (int), 'name' and
'apploader version'.  Strings are bytes objects.

"""
        fields = (
            ('code', 0x0, 0x4),
            ('version', 0x7, 0x1, True),
            # unlikely to have a game name longer than 256 characters
            ('name', 0x20, 0x100, False, b'\0', 0x30),
            ('apploader version', 0x2440, 0xa)
        )
        data = {}
        with open(self.fn, 'rb') as f:
            for name, *args in fields:
                data[name] = read(f, *args)
        return data

    def get_file_tree_locations (self, tree = None):
        """Get a list of files in the given tree with their parent trees.

get_file_tree_locations([tree]) -> files

tree: the tree to look in; defaults to this instance's tree attribute.

files: list of (file, tree, index) tuples, where tree[None][index] == file.

"""
        if tree is None:
            tree = self.tree
        files = []
        # files
        for i, f in enumerate(tree[None]):
            files.append((f, tree, i))
        # dirs
        for k, t in tree.items():
            if k is not None:
                files += self.get_file_tree_locations(t)
        return files

    def get_extra_files (self):
        """Get a list of files in the image that aren't in the filesystem.

Each file is a (name, start, size) tuple.

"""
        with open(self.fn, 'rb') as f:
            appldr_size = read(f, 0x2454, 0x4, True)
        return [('boot.bin', 0x0, 0x440), ('bi2.bin', 0x440, 0x2000),
                ('appldr.bin', 0x2440, 0x2440 + appldr_size)]

    def _extract (self, f, start, size, dest, overwrite = False):
        """Copy data from the disk image to a file.

_extract(f, start, size, dest, overwrite = False) -> success

f: the disk image opened in binary mode.
start: position to start reading from.
size: amount of data to read.
dest: file to extract to; may also be a file object to write to (open in binary
      mode).
overwrite: whether to overwrite the file if it exists (if False and the file
           exists, success will be False).

success: whether the file could be created.

"""
        if not overwrite and exists(dest):
            return False
        f.seek(start)
        try:
            if isinstance(dest, (str, bytes)):
                f_dest = open(dest, 'wb')
            else:
                f_dest = dest
            # copy data
            while size > 0:
                amount = min(size, BLOCK_SIZE)
                data = f.read(amount)
                size -= amount
                f_dest.write(data)
            if isinstance(dest, (str, bytes)):
                f_dest.close()
        except IOError:
            return False
        else:
            return True

    def extract_extra_files (self, files, overwrite = False):
        """Extract files from the image that aren't in the filesystem.

extract_extra_files(files, overwrite = False) -> failed

files: a list of the files to extract, each a (name, target) tuple, where:
    name: the file's name as returned by get_extra_files.
    target: the path on the real filesystem to extract this file to.
overwrite: whether to overwrite files if they exist (if False and a file
           exists, its returned success will be False).

failed: a list of indices in the given files list for files that could not be
        created.  Failure can occur if the name is unknown, the destination
        file already exists (depends on overwrite), or the target path is
        invalid (includes the case where the target path's parent directory
        doesn't exist).

"""
        all_files = {f[0]: f[1:] for f in self.get_extra_files()}
        failed = []
        with open(self.fn, 'rb') as f:
            for i, (name, dest) in enumerate(files):
                print(i, name, dest)
                try:
                    start, size = all_files[name]
                except KeyError:
                    # unknown file
                    failed.append(i)
                else:
                    to_copy = [((self.fn, f, start, size), dest)]
                    if copy(to_copy, None, None, overwrite):
                        failed.append(i)
        return failed

    def extract (self, files, overwrite = False, progress = None):
        """Extract files from the filesystem.

extract(files, overwrite = False[, progress]) -> failed

files: a list of the files and directories to extract, each an (index, target)
       tuple, where:
    index: the index of the file/directory in this GCFS instance's entries
           attribute.  Use -1 (or any other number less than 0) for the root
           directory.  Alternatively, this can be a tree in the same format as
           the tree attribute to recreate on the real filesystem; imported
           files are respected, and will be copied as necessary.
    target: the path on the real filesystem to extract this file/directory to.
overwrite: whether to overwrite files if they exist and ignore existing
           directories (if False and a file/directory exists, it will be in the
           failed list).
progress: a function to call to indicate progress.  See the same argument to
          the write method for details.

failed: a list of files and directories that could not be created.  This is in
        the same format as the given files, but may include ones not given (if
        a given directory could be created, but not one of its children).
        Failure can occur if:
    - the file/directory already exists and overwrite is False
    - extracting a file to a path that exists as a directory (no matter the
      value of overwrite)
    - the target path is invalid or otherwise can't be written to (includes the
      case where the target path's parent directory doesn't exist)
    - an imported file in a given tree could not be read
    - an imported file in a given tree is being extracted back out to itself

Like the entries attribute itself, this method does not take into account
modifications made to the tree attribute that have not been written to the
image (using the write method).  To do that, pass trees instead of entries
indexes.

Directories are extracted recursively.

"""
        entries = self.entries
        names = self.names
        # build trees for dirs
        _files = files
        files = []
        total = 0
        for i, dest in _files:
            if isinstance(i, int):
                if i < 0:
                    # root
                    j = self.build_tree(False)
                elif entries[i][0]:
                    # dir
                    j = self.build_tree(False, i, i + 1)
                else:
                    # file
                    j = i
            else:
                # i already a tree
                j = i
            files.append((i, dest, j))
            # add to total amount of data to copy
            if not isinstance(j, dict):
                j = {None: [('', j)]}
            total += self._tree_size(j, True)
        to_copy = []
        to_copy_names = []
        failed_pool = []
        disk_fn = self.fn
        with open(disk_fn, 'rb') as f:
            # create directory trees and compile files to copy
            while files:
                orig_i, dest, i = files.pop(0)
                # remove trailing separator
                sep = _sep(dest)
                while dest.endswith(sep):
                    dest = dest[:-1]
                # get entry data
                if isinstance(i, dict):
                    # create dir
                    try:
                        os.mkdir(dest)
                    except OSError as e:
                        if not overwrite or e.errno != 17:
                            # unknown error
                            failed.append((orig_i, dest))
                            continue
                        # else already exists and we want to ignore this
                    # add children to extract list: files
                    for name, j in i[None]:
                        files.append((j, _join(dest, name), j))
                    # dirs
                    for k, child_tree in i.items():
                        if k is not None:
                            name, j = k
                            files.append((j, _join(dest, name), child_tree))
                else:
                    # file
                    if isinstance(i, int):
                        # extract
                        start, size = entries[i][2:]
                        to_copy.append(((disk_fn, f, start, size), dest))
                        to_copy_names.append(names[i])
                    else:
                        # copy
                        to_copy.append((i, dest))
                        to_copy_names.append(i)
                    failed_pool.append((orig_i, dest))
            # extract files
            failed = copy(to_copy, progress, to_copy_names, overwrite)
        return [failed_pool[i] for i in failed]

    def _align_4B (self, x):
        """Align the given number to the next multiple of 4."""
        x, r = divmod(x, 4)
        if r > 0:
            x += 1
        return x * 4

    def write (self, tmp_dir = None, progress = None,
               paused_check_interval = .5):
        """Write the current tree to the image.

write([tmp_dir][, progress])

tmp_dir: a directory to store temporary files in for some operations.
progress: a function to call to indicate progress.  See the same argument to
          the write method for details.  If this function is successfully
          canceled, the disk and this GCFS instance (including the tree
          attribute) will be left unaltered (for all intents and purposes,
          anyway).

This function looks at the current state of the tree and amends the filesystem
in the GameCube image to be the same, copying files from the real filesystem as
necessary.  The algorithm tries not to increase the size of the disk image, but
it may be necessary.

If an exception is raised, its 'handled' attribute is set to True if the disk
and this instance (including the tree attribute) are left unaltered (for all
intents and purposes, anyway).  Exceptions without this setting should be
treated with care: both the disk image and the data in this instance might be
broken.

Note on internals: files may be moved within the disk by replacing their
entries index with (index, new_start) before writing.  If you do this, you must
guarantee the move will not overwrite any other files and that new_start is
4-byte-aligned.  This is only supported in this method.  New files should not
be imported in the same call to this function.

It's probably a good idea to back up first...

"""
        old_entries = self.entries
        old_names = self.names
        tree, self.tree = self.tree, deepcopy(self.tree)
        # compile new filesystem/string tables
        tree[None] = [f + (True,) for f in tree[None]]
        entries = []
        old_files = []
        moving_files = []
        new_files = []
        names = []
        str_start = 0
        dirs = []
        parent_indices = {id(tree): 0}
        done = False
        sort_key = lambda c: c[0].upper()
        while True:
            while len(tree) == 1 and not tree[None]:
                # go up one dir
                if dirs:
                    tree = dirs.pop()
                else:
                    done = True
                    break
            if done:
                break
            # find next file or dir alphabetically
            children = tree[None]
            # += causes the original list to be modified
            children = children + list(k for k in tree if k is not None)
            child = min(children, key = sort_key)
            if len(child) == 3:
                # file
                name, old_i = child[:2]
                names.append(_decoded(name))
                i = len(entries)
                if isinstance(old_i, int):
                    # existing file
                    start, size = old_entries[old_i][2:]
                    old_files.append((start, i, old_i, size))
                elif isinstance(old_i, (str, bytes)):
                    # new file: get size
                    fn = old_i
                    start = fn
                    if not os.path.isfile(fn):
                        err = '\'{}\' is not a valid file'
                        e = ValueError(err.format(fn))
                        e.handled = True
                        raise e
                    size = getsize(fn)
                    # put in new file list
                    new_files.append((size, i))
                else:
                    # existing file to move within the image
                    old_i, start = old_i
                    old_start, size = old_entries[old_i][2:]
                    moving_files.append((old_i, i, old_start, start, size))
                entries.append((False, str_start, start, size))
                # update tree
                tree[None].remove(child)
            else:
                assert len(child) == 2
                # dir
                new_tree = tree[child]
                dirs.append(tree)
                parent = parent_indices[id(tree)]
                del tree[child]
                tree = new_tree
                tree[None] = [f + (True,) for f in tree[None]]
                name = _decoded(child[0])
                names.append(name)
                next_index = len(entries) + 2 + self._tree_size(tree)
                entries.append((True, str_start, parent, next_index))
                parent_indices[id(tree)] = len(entries)
            # terminate with a null byte
            str_start += len(_encode(name)) + 1
        # get start of actual file data
        # str_start is now the string table size
        data_start = self.fs_start + (1 + len(entries)) * 0xc + str_start

        def error (msg, f = None, cls = IOError):
            # return disk image to original size if expanded
            if truncated:
                if f is None:
                    with open(self.fn, 'r+b') as f:
                        f.truncate(orig_disk_size)
                else:
                    f.truncate(orig_disk_size)
            # delete temp dir
            if tmp_dir is not None:
                try:
                    rmtree(tmp_dir)
                except OSError:
                    pass
            # raise error
            e = cls(msg)
            e.handled = True
            raise e

        truncated = False
        if moving_files:
            orig_disk_size = getsize(self.fn)
            # copy files within disk image
            with open(self.fn, 'r+b') as f:
                # if we will be seeking beyond the image end, expand the file
                end = f.seek(0, 2)
                last_start = max(f[3] for f in moving_files)
                if end < last_start:
                    truncated = True
                    f.truncate(last_start)
                # copy
                fn = self.fn
                to_copy = []
                to_copy_names = []
                for old_i, i, old_start, start, size in moving_files:
                    to_copy.append(((fn, f, old_start, size), (fn, f, start)))
                    to_copy_names.append(names[i])
                    # put in old_files
                    old_files.append((start, i, old_i, size))
                failed = copy(to_copy, progress, names)
                if failed:
                    msg = 'couldn\'t read from and write to the disk image'
                    error(msg, f)
        # sort existing files by position
        old_files.sort()
        # get existing files overwritten by the filesystem/string tables and
        # extract them to a temp dir
        # don't bother including this in the progress calculations, because
        # unless we're adding a crazy amount of files with crazily long names,
        # it won't take any time at all
        # get number of files to extract
        n = 0
        for i, f in enumerate(old_files):
            if f[0] >= data_start:
                n = i
                break
        if n > 0:
            tmp_dir = tempfile.mkdtemp(prefix = 'gcutil', dir = tmp_dir)
            to_extract = []
            for j in range(n):
                # move from old_files to new_files
                start, i, old_i, size = old_files.pop(0)
                new_files.append((size, i))
                # get temp file to extract to
                f = tempfile.NamedTemporaryFile(prefix = '', dir = tmp_dir,
                                                delete = False)
                fn = f.name
                f.close()
                to_extract.append((old_i, fn))
                # change entry
                entries[i] = (False, entries[i][1], fn, size)
            # extract
            failed = self.extract(to_extract, True)
            if failed:
                msg = 'couldn\'t extract to a temporary file ({})'
                error(msg.format(failed[0][1]))

        # copy new files to the image
        if new_files:
            # track progress
            total = sum(size for size, i in new_files)
            copied = 0
            # get free space in the filesystem
            free = []
            l = [(data_start, None, None, 0)] + old_files
            align = self._align_4B
            for j in range(len(l) - 1):
                start = align(l[j][0] + l[j][3])
                end = l[j + 1][0]
                gap = end - start
                if gap > 0:
                    free.append((gap, start))
            # fit new files to gaps: sort both by size
            if old_files:
                last_file = old_files[-1]
                end = last_file[0] + last_file[3]
            else:
                end = data_start
            end = align(end)
            new_files.sort(reverse = True)
            free.sort(reverse = True)
            # take the largest file
            for file_i, (size, i) in enumerate(new_files):
                # and put it in the smallest possible gap
                gap_i = -1
                for gap_i, (gap, gap_start) in enumerate(free):
                    if gap < size:
                        gap_i -= 1
                        break
                if gap_i < 0:
                    # either no gaps or won't fit in any: place at the end
                    start = end
                    end = align(end + size)
                else:
                    # alter the gap entry
                    gap, gap_start = free[gap_i]
                    start = gap_start
                    gap_end = gap_start + gap
                    gap_start = align(gap_start + size)
                    gap = gap_end - gap_start
                    if gap > 0:
                        free[gap_i] = (gap, gap_start)
                        free.sort(reverse = True)
                    else:
                        free.pop(gap_i)
                new_files[file_i] = (start, i)
            # actually copy
            with open(self.fn, 'r+b') as f:
                # if we will be seeking beyond the image end, expand the file
                end = f.seek(0, 2)
                last_start = max(start for start, i in new_files)
                if end < last_start:
                    f.truncate(last_start)
                # perform the copy
                to_copy = []
                to_copy_names = []
                fn = self.fn
                for start, i in new_files:
                    is_dir, str_start, this_fn, size = entries[i]
                    to_copy.append(((this_fn, None, 0, size), (fn, f, start)))
                    to_copy_names.append(names[i])
                    entries[i] = (False, str_start, start, size)
                failed = copy(to_copy, progress, to_copy_names)
                if failed:
                    msg = 'either couldn\'t read from \'{}\' or couldn\'t ' \
                          'write to the disk image'
                    error(msg.format(to_copy[failed[0]][0][0]), f)

        # clean up temp dir
        if tmp_dir is not None:
            try:
                rmtree(tmp_dir)
            except OSError:
                pass
        # get new fst_size, num_entries, str_start
        self.fst_size = data_start - self.fs_start
        self.num_entries = len(entries) + 1
        self.str_start = self.fs_start + self.num_entries * 0xc
        # write new fst_size and filesystem/string tables to the image
        self.entries = entries
        self.names = names
        with open(self.fn, 'r+b') as f:
            write(self.fst_size, f, 0x428, 0x4)
            root = (True, 0, 0, self.num_entries)
            args = ((0x0, 0x1), (0x1, 0x3), (0x4, 0x4), (0x8, 0x4))
            offset = self.fs_start
            for k, entry in enumerate([root] + self.entries):
                for data, (pos, size) in zip(entry, args):
                    write(int(data), f, offset + pos, size) # is_dir is bool
                offset += 0xc
            pos = self.str_start
            for name in names:
                name = _encode(name)
                write(name + b'\0', f, pos)
                pos += len(name) + 1
            # truncate image to new size if necessary
            ends = [st + sz for d, ss, st, sz in entries if not d]
            end = max([data_start] + ends)
            if end < f.seek(0, 2):
                f.truncate(end)
        # build new tree
        self.build_tree()

    def _quick_compress (self):
        """Quick compress of the image.

Returns whether any changes were made to the tree.

See compress for more details.

"""
        # get files, sorted by reverse position
        files = self.get_file_tree_locations()
        entries = self.entries
        files = [(entries[i][2], entries[i][3], i, name, tree[None], tree_i)
                 for (name, i), tree, tree_i in files]
        files.sort(reverse = True)
        # get start of file data
        data_start, i = max((0, -1),
                            *((e[1], i) for i, e in enumerate(entries)))
        if i != -1:
            data_start += len(_encode(self.names[i])) + 1
        data_start += self.str_start
        # get free space in the filesystem, sorted by position, aligned to
        # 4-bytes blocks
        free = []
        l = [(data_start, 0)] + list(reversed(files))
        align = self._align_4B
        for j in range(len(l) - 1):
            start = align(l[j][0] + l[j][1])
            end = l[j + 1][0]
            gap = end - start
            if gap > 0:
                free.append((start, gap))
        free.sort()
        # repeatedly put the last file in earliest possible gap
        changed = False
        for file_i, (pos, size, i, name, d, d_i) in enumerate(files):
            placed = False
            for gap_i, (start, gap) in enumerate(free):
                if gap >= size and start < pos:
                    # mark file moved
                    d[d_i] = (name, (i, start))
                    # change gap entry
                    end = start + gap
                    start = align(start + size)
                    gap = end - start
                    if gap > 0:
                        free[gap_i] = (start, gap)
                        free.sort()
                    else:
                        free.pop(gap_i)
                    placed = True
                    changed = True
                    break
            if not placed:
                # no gap: move to end of previous file if possible
                if file_i != 0:
                    start = files[file_i - 1][0] + files[file_i - 1][1]
                    if pos - start > size:
                        # got enough space to move without extracting anything
                        d[d_i] = (name, (i, start))
                        changed = True
                # finished - no point trying to move any other files earlier
                break
        return changed

    def _slow_compress (self, tmp_dir, progress = None):
        """Quick compress of the image.

_slow_compress(tmp_dir[, progress]) -> changed

changed: whether any changes were made to the tree.

tmp_dir is required and must exist.

See compress for more details.

"""
        # TODO
        # - place files at start of data in entries order
        # - copy any that are already in new region to temp dir
        # - replace tree entries to reflect changes
        # - write()
        pass

    def compress (self, progress = None):
        """Compress the image.

compress([progress])

progress: a function to call to indicate progress.  See the same argument to
          the write method for details.

This function removes all free space in the image's filesystem to make it
smaller.  GameCube images often have a load of free space between the
filesystem string table and the file data, sometimes hundreds of MiB.  This
will also remove free space between files that may have been opened up by
deletions or other editing.

IMPORTANT: any changes that have been made to the tree are discarded before
compressing.  Make sure you write everything you want to keep first.

"""
        """

Replacement docstring for if I ever do full compress:

compress(quick = True[, tmp_dir][, progress])

quick: whether to do a quick compress (see below).
tmp_dir: a directory to store temporary files.  If this does not exist, it is
         created and deleted before returning; if not given, Python's tempfile
         package is used.  If quick is True, this is ignored.
progress: a function to call to indicate progress.  See the same argument to
          the write method for details.

This function removes all free space in the image's filesystem to make it
smaller.  GameCube images often have a load of free space between the
filesystem string table and the file data, sometimes hundreds of MiB.  This
will also remove free space between files that may have been opened up by
deletions or other editing.

A quick compress may not remove all free space, but does well enough.  It
should also be faster and doesn't use any extra disk space (or memory, if you're
thinking of a ramdisk).  Unless you're obsessive-compulsive, this should be
good enough.

As implied above, a full compress may use some extra disk space.  While
unlikely, this may be as much as the size of this disk image.  More
importantly, if tmp_dir is not given, the directory used might be on a ramdisk,
so we could end up running out of memory.  Be careful.

IMPORTANT: any changes that have been made to the tree are discarded before
compressing.  Make sure you write everything you want to keep first.

"""
        # discard changes
        self.tree = self.build_tree()
        if self._quick_compress():
            self.write(progress = progress)
        #if quick:
            #if self._quick_compress():
                #self.write(tmp_dir, progress)
        #else:
            #tmp_dir = tempfile.mkdtemp(prefix = 'gcutil', dir = tmp_dir)
            #self._slow_compress(tmp_dir, progress)
            #try:
                #rmtree(tmp_dir)
            #except OSError:
                #pass