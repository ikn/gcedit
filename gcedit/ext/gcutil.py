"""GameCube file utilities.

Python version: 3.
Release: 16-dev.

Licensed under the GNU General Public License, version 3; if this was not
included, you can find it here:
    http://www.gnu.org/licenses/gpl-3.0.txt

    CLASSES

GCFS
DiskError

    FUNCTIONS

valid_name
read
write
copy
bnr_to_pnm
tree_from_dir
search_tree

    SETTINGS

(Change these as attributes of this module.)

CODEC = 'shift_jis': the string encoding to use for filenames in the disk
                     image.  (Shift JIS seems to be right, but maybe you've
                     got a disk that uses something else.)
BLOCK_SIZE = 0x100000: the maximum amount of data, in bytes, to read and write
                       at a time (0x100000 is 1MiB).
PAUSED_WAIT = .1: in functions that take a progress function, if the action is
                  paused, the function waits this many seconds between
                  subsequent calls to the progress function.

"""

# TODO:
# - read should use struct.unpack for ints (do some timings)
# - put code that gets gaps in fs in a function (used twice)
# - compress should truncate if possible
# RARC: http://hitmen.c02.at/files/yagcd/yagcd/chap15.html#sec15.3
# Yaz0: http://hitmen.c02.at/files/yagcd/yagcd/chap16.html#sec16.2

from sys import byteorder
import os
from os.path import getsize, exists, dirname, basename
from time import sleep
from copy import deepcopy
from array import array
import re
from shutil import rmtree
import tempfile

try:
    _
except NameError:
    _ = lambda s: s

CODEC = 'shift-jis'
BLOCK_SIZE = 0x100000
PAUSED_WAIT = .1

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


def copy (files, progress = None, names = None, overwrite = True,
          can_cancel = False):
    """Copy a file to a file object.

copy(files[, progress, names], overwrite = True, can_cancel = False) -> failed

files: a list of (source, *dests) tuples to copy from source to dest.  source
       is (file, start, size) and each dest is (file, start), where, in each
       case, file is a file object open in binary read/write mode (only needs a
       read/write method), or a filename to open.  If a file object is given to
       write to, it will not be truncated so that it is large enough to be able
       to seek to start.

       start and size may be omitted: start defaults to 0 and size defaults to
       (file_size - start).  If both are omitted, source/dest can be just file.
progress: a function to periodically pass the current progress to.  It takes 3
          arguments: the amount of data that has been copied in bytes, the
          total amount of data to copy in bytes, and the name of the current
          file (in the disk's filesystem) being read/written (str not bytes).

          In higher-level functions that take this argument, there is a period
          of time before any calls are made to this function, in which the
          total amount to copy is unknown.  In, for example, GCFS.write, this
          passed function may never be called - if, for example, all you are
          doing is creating directories or deleting files.

          You can pause the copy by returning 1.  This function will then call
          progress periodically until the return value is no longer 1 (for
          these calls, the arguments are all None).  The progress function is
          only called between every block/file copied - this gives an idea of
          how quickly a running copy can be paused.

          You can try to cancel the copy by returning 2.  If it can still be
          safely cancelled, some cleanup will be performed and the function
          will return True.  If the progress function is called again, you may
          assume that the copy cannot be cancelled.

          You can force cancelling the copy by returning 3.  This can
          potentially lead to a corrupted disk image.
names: a list filenames corresponding to elements of the files list to pass to
       progress as the third argument, or an integer to use the names of the
       src or dest files with that index in each element of files.  If an
       integer (and progress is given), each corresponding file object must
       have a 'name' attribute containing its filename.
overwrite: whether to overwrite any destination files that exist (if False and
           a file exists, it will be in the failed list).  Of course, this only
           makes sense for files where the filename and not the open file is
           given.
can_cancel: whether cancelling this copy operation (by returning 2 from the
            progress function) is allowed.

failed: a list of indices in the given files list for copies that failed.  Or,
        if this function is cancelled (see the progress and can_cancel
        arguments), the return value is the value used to cancel it (2 or 3).

"""
    string = (bytes, str)

    def get_size (f):
        # return the size of the given file (and cache the results)
        size = sizes.get(f, None)
        if size is None:
            try:
                size = getsize(f)
            except OSError:
                size = 0
            # store in cache
            sizes[f] = size
        return size

    # make every src/dest a list and fill in default values
    sizes = {}
    total_size = 0
    to_copy = []
    for src, *dests in files:
        if isinstance(src, string) or hasattr(src, 'read'):
            src = [src]
        else:
            src = list(src)
        if len(src) == 1:
            src.append(0)
        if len(src) == 2:
            src.append(get_size(src[0]) - src[1])
        total_size += src[2]
        f = [src]
        for dest in dests:
            if isinstance(dest, string) or hasattr(dest, 'write'):
                dest = [dest]
            else:
                dest = list(dest)
            if len(dest) == 1:
                dest.append(0)
            f.append(dest)
        to_copy.append(f)
    if progress is not None and isinstance(names, int):
        # fill out names
        i, names = names, []
        for f in to_copy:
            f = f[i][0]
            if not isinstance(f, string):
                f = basename(f.name)
            names.append(f)
    # actual copy
    failed = []
    total_done = 0
    progress_update = BLOCK_SIZE
    for file_i, (src, *dests) in enumerate(to_copy):
        src_f, src_start, size = src
        src_open = isinstance(src_f, string)
        dest_fs = []
        dest_starts = []
        dest_opens = []
        for dest in dests:
            dest_f, dest_start = dest
            dest_fs.append(dest_f)
            dest_starts.append(dest_start)
            dest_opens.append(isinstance(dest_f, string))
        try:
            # open files
            if src_open:
                src_f = open(src_f, 'rb')
            this_failed = False
            for i, (dest_f, dest_open) in enumerate(zip(dest_fs, dest_opens)):
                if dest_open:
                    if not overwrite and exists(dest_f):
                        # exists and don't want to overwrite
                        failed.append(i)
                        this_failed = True
                        break
                    dest_fs[i] = open(dest_f, 'wb')
            if this_failed:
                continue
            # seek
            sames = []
            for dest_f in dest_fs:
                same = src_f is dest_f
                sames.append(same)
                if not same:
                    dest_f.seek(dest_start)
            if not any(sames):
                src_f.seek(src_start)
            # copy
            done = 0
            while size:
                if progress is not None and total_done >= progress_update:
                    # update progress
                    result = progress(total_done, total_size, names[file_i])
                    while result == 1:
                        # paused
                        sleep(PAUSED_WAIT)
                        result = progress(None, None, None)
                    if result == 3:
                        return False
                    if result == 2 and can_cancel:
                        # cancel
                        return True
                    progress_update += BLOCK_SIZE
                # read and write the next block
                amount = min(size, BLOCK_SIZE)
                if any(sames):
                    src_f.seek(src_start + done)
                data = src_f.read(amount)
                for dest_f, dest_start, same in zip(dest_fs, dest_starts,
                                                    sames):
                    if same:
                        dest_f.seek(dest_start + done)
                    dest_f.write(data)
                size -= amount
                done += amount
                total_done += amount
        except IOError:
            failed.append(file_i)
            continue
        finally:
            # clean up
            if src_open and not isinstance(src_f, string):
                src_f.close()
            for dest_f, dest_open in zip(dest_fs, dest_opens):
                if dest_open and not isinstance(dest_f, string):
                    dest_f.close()
    return failed


def bnr_to_pnm (img_data):
    """This function converts BNR image data to PNM (PPM, to be exact).

BNR files use little-endian 1RGB5 (1RRRRRGGGGGBBBBB) or 0A3RGB4
(0AAARRRRGGGGBBBB) (each pixel may vary) with an assumed black background and
pixels arranged in 4x4 blocks.  The argument is an iterable containing this
data (probably as bytes), and the returned image is bytes.

"""
    w, h = 96, 32
    target_bits = 8
    # create header
    header = 'P6 {} {} {} '.format(w, h, 2 ** target_bits - 1).encode('ascii')
    # create destination array
    dest = bytearray(w * h * 3)
    # split image data into 2-byte integers
    src = array('H')
    src.fromstring(img_data)
    if byteorder == 'little':
        # switch endianness
        src.byteswap()
    src = iter(src)
    # iterate over pixels
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            for iy in range(4):
                for ix in range(4):
                    index = 3 * ((y + iy) * w + x + ix)
                    pixel = next(src)
                    # unpack colours and place in output
                    # we want (RRRRR, GGGGG, BBBBB)
                    if pixel >> 15:
                        # got (ARRRRRGG, GGGBBBBB)
                        bit_counts = (5, 5, 5)
                        alpha = 1
                        pwr = 15
                    else:
                        # got (0AAARRRR, GGGGBBBB)
                        bit_counts = (4, 4, 4)
                        alpha = (pixel >> 12) / 8
                        pwr = 12
                    pixel %= (2 ** pwr)
                    for i, n_bits in enumerate(bit_counts):
                        pwr -= n_bits
                        mod = 2 ** pwr
                        # get this colour's value
                        c = alpha * (pixel // mod)
                        # scale to target bits
                        c *= (2 ** target_bits - 1) / (2 ** n_bits - 1)
                        # round and add
                        dest[index + i] = int(round(c))
                        # remove from pixel
                        pixel %= mod
    return header + dest


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


def tree_names (tree):
    """Get the top-level names in a tree (including files and directories)."""
    return [x[0] for x in list(tree.keys()) + tree[None] if x is not None]


def _match (term, name, case_sensitive, whole_name, regex):
    """Used by search_tree to check if a name matches.

_match(term, name, case_sensitive, whole_name, regex) -> matches

term, case_sensitive, whole_name, regex: as taken by search_tree.
name: the file/directory name to match against.

matches: whether name is a match for term.

If case_sensitive is False, term should be lower-case.

"""
    if regex:
        flags = 0 if case_sensitive else re.I
        if whole_name:
            match = re.match(term, name, flags)
            return match is not None and match.end() == len(name)
        else:
            return re.search(term, name, flags) is not None
    else:
        if not case_sensitive:
            name = name.lower()
        if whole_name:
            return term == name
        else:
            return name.find(term) != -1


def search_tree (tree, term = '', case_sensitive = False, whole_name = False,
                 regex = False, dirs = True, files = True, current_dir = None,
                 matches = None):
    """Search within a tree.

search_tree(tree, term = '', case_sensitive = False, whole_name = False,
            regex = False, dirs = True, files = True) -> matches

tree: the tree to search (same format as the tree attribute of GCFS objects).
term: the string to search for.
case_sensitive: whether the match should be case-sensitive.
whole_name: whether to only return results where the term matches the whole of
            the file/directory name.
regex: whether to perform RegEx-based matching.
dirs: whether to include directories in the results.
files: whether to include files in the results.

matches: a list of (is_dir, parent_path, key) tuples for matching files and
         directories, where:
    is_dir: whether this is a directory.
    parent_path: a list of keys for each parent directory, starting from the
                 root directory.  This is empty for items in the root
                 directory.
    key: the item's (name, index) tuple as found in the tree.

"""
    if current_dir is None:
        current_dir = []
        matches = []
        if not case_sensitive:
            term = term.lower()
    for d_key, this_tree in tree.items():
        if d_key is None:
            # files
            if files:
                for f_key in this_tree:
                    if _match(term, f_key[0], case_sensitive, whole_name,
                              regex):
                        matches.append((False, current_dir, f_key))
        else:
            # dir
            if dirs:
                if _match(term, d_key[0], case_sensitive, whole_name, regex):
                    matches.append((True, current_dir, d_key))
            # search this dir (its results get added to matches)
            search_tree(this_tree, term, case_sensitive, whole_name, regex,
                        dirs, files, current_dir + [d_key], matches)
    return matches


class GCFS:
    """Read from and make changes to a GameCube image's filesystem.

To make changes to the tree, edit data in the tree attribute directly.  To undo
all changes, call the build_tree method.  The entries and names attributes
reflect what is actually in the image, and will only change when the write
method is called.

To import a directory tree from the real filesystem, use the tree_from_dir
function in this module and place the result in the tree attribute, or
replace the whole tree if you want to import an entire GameCube filesystem.

All methods that read from the disk image (apart from write) don't handle an
IOError; you should handle this yourself.

    CONSTRUCTOR

GCFS(fn, sanity = True)

fn: file path to the image file.
sanity: perform some sanity checks when loading the filesystem.  If any fail,
        DiskError is raised.  This is to protect against crashes or hangs in
        the case of invalid files.  Passing False is not recommended, but may
        be necessary if there happens to be a valid disk that falls outside
        these checks.

    METHODS

build_tree
tree_size
flatten_tree
update
disk_changed
changed
get_info
get_bnr_info
get_extra_files
read_file
extract_extra_files
extract
write
compress
decompress

    ATTRIBUTES

fn, max_name_size: as given.
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

      Note: bad things happen if you have an object (dict or list) in more than
      one place in the tree.

"""

    def __init__ (self, fn, sanity = True):
        self.fn = str(fn)
        self.sanity = sanity
        # read data from the disk
        self.update()

    def _init (self):
        """Read and store data from the disk."""
        sanity = self.sanity
        with open(self.fn, 'rb') as f:
            if sanity:
                # check DVD magic word
                if read(f, 0x1c, 0x4, True) != 0xc2339f3d:
                    raise DiskError(_('DVD magic word missing'))
                end = f.seek(0, 2)
            self.fs_start = fs_start = read(f, 0x424, 0x4, True)
            self.fst_size = fst_size = read(f, 0x428, 0x4, True)
            fst_end = fs_start + fst_size
            if sanity:
                # check FST position and size
                if fs_start < 0x2440: # this is where the Apploader starts
                    raise DiskError(_('filesystem starts too early'))
                elif fs_start > 0x4000000: # 64MiB
                    raise DiskError(_('filesystem starts too late'))
                if fst_size > 0x400000: # 4MiB
                    raise DiskError(_('filesystem table too large'))
                if fst_end > end:
                    raise DiskError(_('filesystem ends too late'))
            self.num_entries = n = read(f, fs_start + 0x8, 0x4, True)
            if sanity:
                if n == 0:
                    raise DiskError(_('no root directory entry'))
                if n > 10 ** 5:
                    raise DiskError(_('too many files in the filesystem'))
                if fst_size < n * 0xc:
                    raise DiskError(_('filesystem table too small'))
            self.str_start = str_start = fs_start + n * 0xc
            # string table should start within FST
            if sanity and self.str_start > fst_end:
                raise DiskError(_('filesystem table ends too early'))
            # get file data
            self.entries = entries = []
            for i in range(1, n):
                # get entry offset
                entry_offset = fs_start + i * 0xc
                # is_dir, str_offset, start, size
                args = ((0x0, 0x1), (0x1, 0x3), (0x4, 0x4), (0x8, 0x4))
                data = [read(f, entry_offset + offset, size, True)
                        for offset, size in args]
                data[0] = d = bool(data[0])
                if sanity:
                    # string table must be contained within FST
                    if str_start + data[1] > fst_end:
                        msg = _('found a file whose name starts too late')
                        raise DiskError(msg)
                    if d:
                        if data[2] >= n:
                            msg = _('found a directory with an invalid parent')
                            raise DiskError(msg)
                        if data[3] > n:
                            msg = _('found an invalid directory entry')
                            raise DiskError(msg)
                    # don't limit file offset/size
                entries.append(tuple(data))
            # get filenames
            self.names = names = []
            for entry in entries:
                name = read(f, str_start + entry[1], 0x200, False, b'\0', 0x20)
                if len(name) == 0x200: # 512B
                    raise DiskError(_('too long a filename'))
                names.append(_decode(name))

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

    def tree_size (self, tree, file_size = False, recursive = False,
                   key = None, sizes = None, done = None):
        """Get the number of children in or total filesize of a tree.

tree_size(tree, file_size = False, recursive = False, key = None) -> size

tree: the tree.
file_size: whether to return the total file size of the children in the tree
        instead.  Imported files are respected (if they cannot be accessed,
        they are ignored).
recursive: whether to return a dict of numbers for every child in the tree
        instead.  The keys of this dict are the the same as in the tree
        ((name, index) for each directory and file).  The key for the whole
        tree is the key argument. If file_size is False, files are omitted
        (always have number of children 0).
key: if recursive is True, this is the key for the whole tree in the returned
    dict (and must, therefore, be hashable).

size: the number of children in the tree or the total file size, or a dict of
    such numbers if recursive is True.

"""
        if recursive and sizes is None:
            sizes = {}
        if done is None:
            done = {}
        # infinite recursion prevention: return if already counted
        tree_id = id(tree)
        if tree_id in done:
            done[tree_id].append(key)
            return sizes if recursive else 0
        # done stores lists of keys for the same tree, as detected above
        done[tree_id] = []
        size = 0
        for d_key, this_tree in tree.items():
            if d_key is None:
                # files
                if file_size:
                    entries = self.entries
                    for f_key in this_tree:
                        i = f_key[1]
                        if isinstance(i, int):
                            this_size = entries[i][3]
                        else:
                            try:
                                this_size = getsize(i)
                            except OSError:
                                this_size = 0
                        size += this_size
                        if recursive:
                            sizes[f_key] = this_size
                else:
                    size += len(this_tree)
            else:
                # dir
                if not file_size:
                    size += 1
                this_size = self.tree_size(this_tree, file_size, recursive,
                                           d_key, sizes, done)
                # if not in sizes now, recursion
                size += sizes.get(d_key, 0) if recursive else this_size
        if recursive:
            sizes[key] = size
            others = done[tree_id]
            if others:
                for k in others:
                    sizes[k] = size
            # this tree might be somewhere else as well, but we've checked all
            # children now, so consider that (and possible infinite recursions)
            # separately
            del done[tree_id]
            return sizes
        else:
            return size

    def flatten_tree (self, tree = None, files = True, dirs = True, path = []):
        """Get a list of files in the given tree with their parent trees.

flatten_tree([tree], files = True, dirs = True) -> items

tree: the tree to look in; defaults to this instance's tree attribute.
files, dirs: whether to include files/directories.

items: list of (is_dir, item, parent, index, path) tuples, where, if is_dir,
       parent[index] == item (and item is a tree), else
       parent[None][index] == item.  If files or dirs is False, is_dir is
       omitted.  path is a list of parent directories containing this item, the
       last its direct parent.  items never includes the root directory.

"""
        if tree is None:
            tree = self.tree
        items = []
        # files
        if files:
            for i, f in enumerate(tree[None]):
                items.append(((False,) if dirs else ()) + (f, tree, i, path))
        # dirs
        for k, t in tree.items():
            if k is not None:
                if dirs:
                    items.append(((True,) if files else ()) + \
                                 (t, tree, k, path))
                items += self.flatten_tree(t, files, dirs, path + [k[0]])
        return items

    def update (self):
        """Re-read data from the disk.  Discards all changes to the tree.

May raise DiskError (see constructor).

"""
        self._init()
        # build tree
        self.build_tree()

    def disk_changed (self, update = False):
        """Return whether changes have been made to the disk.

This checks the filesystem table, but not the files themselves.  May raise
DiskError (see constructor).

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
'apploader version'.

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
                this_data = read(f, *args)
                if isinstance(this_data, bytes):
                    this_data = _decode(this_data)
                data[name] = this_data
        return data

    def get_bnr_info (self, index = None):
        """Get game information from a BNR file.

With no arguments, looks for opening.bnr, else takes the index of the file in
this GCFS instance's entries attribute.  Raises ValueError if the file doesn't
exist or is invalid.

Returns a dict with 'img' (bytes), 'name', 'developer', 'full name',
'full developer', 'description'.

"""
        if index is None:
            # find file
            matches = [f for f in self.tree[None] if f[0] == 'opening.bnr']
            if matches:
                index = matches[0][1]
            else:
                raise ValueError('disk has no \'opening.bnr\' file')
        # get file details
        try:
            is_dir, str_start, offset, size = self.entries[index]
        except (TypeError, IndexError):
            raise ValueError('there is no file with index {0}'.format(index))
        if is_dir:
            raise ValueError('given file index corresponds to a directory')
        # read data
        fields = (
            ('img', 0x20, 0x1800),
            ('name', 0x1820, 0x20, False, b'\0', 0x20),
            ('developer', 0x1840, 0x20, False, b'\0', 0x20),
            ('full name', 0x1860, 0x40, False, b'\0', 0x40),
            ('full developer', 0x18a0, 0x40, False, b'\0', 0x40),
            ('description', 0x18e0, 0x80, False, b'\0', 0x80),
        )
        data = {}
        with open(self.fn, 'rb') as f:
            # check for magic word
            if read(f, offset, 0x4) not in (b'BNR1', b'BNR2'):
                raise ValueError('invalid BNR file')
            for name, start, *args in fields:
                this_data = read(f, offset + start, *args)
                if name != 'img':
                    this_data = _decode(this_data)
                data[name] = this_data
        return data

    def get_extra_files (self):
        """Get a list of files in the image that aren't in the filesystem.

Each file is a (name, start, size) tuple.

"""
        with open(self.fn, 'rb') as f:
            appldr_size = read(f, 0x2454, 0x4, True)
        return [('boot.bin', 0x0, 0x440), ('bi2.bin', 0x440, 0x2000),
                ('appldr.bin', 0x2440, 0x2440 + appldr_size)]

    def read_file (self, index):
        """Read a file from the disk image.

Takes the index of the file in this GCFS instance's entries attribute and
returns the entire file contents as bytes.

"""
        try:
            is_dir, str_start, start, size = self.entries[index]
        except (TypeError, IndexError):
            raise ValueError('there is no file with index {0}'.format(index))
        if is_dir:
            raise ValueError('given file index corresponds to a directory')
        with open(self.fn, 'rb') as f:
            return read(f, start, size)

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
                try:
                    start, size = all_files[name]
                except KeyError:
                    # unknown file
                    failed.append(i)
                else:
                    to_copy = [((f, start, size), dest)]
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

       Or, if this function is cancelled (through the progress function), the
       return value is the value used to cancel (2 or 3); in this case, the
       destinations of files that have already been extracted are not removed.

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
            total += self.tree_size(j, True)
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
                        to_copy.append(((f, start, size), dest))
                        to_copy_names.append(names[i])
                    else:
                        # copy
                        to_copy.append((i, dest))
                        to_copy_names.append(i)
                    failed_pool.append((orig_i, dest))
            # extract files
            failed = copy(to_copy, progress, to_copy_names, overwrite, True)
            if isinstance(failed, int):
                # cancelled
                return failed
        return [failed_pool[i] for i in failed]

    def _align_4B (self, x):
        """Align the given number to the next multiple of 4."""
        x, r = divmod(x, 4)
        if r > 0:
            x += 1
        return x * 4

    def write (self, tmp_dir = None, progress = None):
        """Write the current tree to the image.

write([tmp_dir][, progress]) -> cancelled

tmp_dir: a directory to store temporary files in for some operations.
progress: a function to call to indicate progress.  See the same argument to
          the write method for details.  If this function is successfully
          cancelled, the disk and this GCFS instance (including the tree
          attribute) will be left unaltered (for all intents and purposes,
          anyway).

cancelled: whether the write was cancelled (through the progress function).  If
           so, this is the value used to cancel it (2 or 3).

This function looks at the current state of the tree and amends the filesystem
in the GameCube image to be the same, copying files from the real filesystem as
necessary.  The algorithm tries not to increase the size of the disk image, but
it may be necessary.

If an exception is raised, its 'handled' attribute is set to True if the disk
and this instance (including the tree attribute) are left unaltered (for all
intents and purposes, anyway).  Exceptions without this setting should be
treated with care: both the disk image and the data in this instance might be
broken.

It's probably a good idea to back up first...

Note on internals: files may be moved within the disk by replacing their
entries index with (index, new_start) before writing.  If you do this, you must
guarantee the move will not overwrite any other files and that new_start is
4-byte-aligned.  This is only supported in this method.  New files should not
be imported in the same call to this function.

"""
        old_entries = self.entries
        old_names = self.names
        tree = deepcopy(self.tree)
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
            children = children + [k for k in tree if k is not None]
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
                        err = _('\'{}\' is not a valid file')
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
                next_index = len(entries) + 2 + self.tree_size(tree)
                entries.append((True, str_start, parent, next_index))
                parent_indices[id(tree)] = len(entries)
            # terminate with a null byte
            str_start += len(_encode(name)) + 1
        # get start of actual file data
        # str_start is now the string table size
        data_start = self.fs_start + (1 + len(entries)) * 0xc + str_start

        def cleanup_tmp_dir ():
            # delete temp dir
            if tmp_dir is not None:
                try:
                    rmtree(tmp_dir)
                except OSError:
                    pass

        def cleanup (f = None):
            cleanup_tmp_dir()
            # return disk image to original size if expanded
            if truncated:
                if f is None:
                    try:
                        with open(self.fn, 'r+b') as f:
                            f.truncate(orig_disk_size)
                    except IOError:
                        pass
                else:
                    f.truncate(orig_disk_size)

        def error (msg, f = None, cls = IOError):
            cleanup(f)
            # raise error
            e = cls(msg)
            e.handled = True
            raise e

        truncated = False
        if moving_files:
            orig_disk_size = getsize(self.fn)
            # copy files within disk image
            try:
                with open(self.fn, 'r+b') as f:
                    # if we will be seeking beyond the image end, expand it
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
                        to_copy.append(((f, old_start, size), (f, start)))
                        to_copy_names.append(names[i])
                        # put in old_files
                        old_files.append((start, i, old_i, size))
                    failed = copy(to_copy, progress, names, can_cancel = True)
                    if isinstance(failed, int):
                        # cancelled
                        cleanup(f)
                        return failed
                    elif failed:
                        msg = _('couldn\'t read from and write to the disk '
                                'image')
                        error(msg, f)
            except IOError as e:
                cleanup()
                e.handled = True
                raise
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
                to_extract.append((start, (old_i, fn)))
                # change entry
                entries[i] = (False, entries[i][1], fn, size)
            # sort by position
            to_extract.sort()
            # extract
            failed = self.extract([f[1] for f in to_extract], True)
            if failed is True:
                # cancelled
                cleanup()
                return True
            elif failed:
                msg = _('couldn\'t extract to a temporary file ({})')
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
                new_files[file_i] = (start, size, start + size, i)
            # split into files that do/don't overwrite existing files
            # sort both lists
            new_files.sort()
            old_files_all = iter(sorted((st, sz, st + sz) for d, ss, st, sz \
                                        in old_entries if not d))
            # also sum up sizes for progress calculations
            nf_clean = []
            total_clean = 0
            nf_dirty = []
            total_dirty = 0
            # get first old file
            try:
                f_start, f_size, f_end = next(old_files_all)
            except StopIteration:
                f_start = None
            for start, size, end, i in new_files:
                clean = True
                while f_start is not None: # else no old files left
                    if f_end <= start:
                        # old before new: get next old file
                        try:
                            f_start, f_size, f_end = next(old_files_all)
                        except StopIteration:
                            f_start = None
                    elif f_start >= end:
                        # old after new: no more old files will overlap
                        break
                    else:
                        # overlap
                        clean = False
                        break
                if clean:
                    total_clean += size
                    nf_clean.append((start, i))
                else:
                    total_dirty += size
                    nf_dirty.append((start, i))
            # sort by start for the potential speedup of not seeking as much
            nf_clean.sort()
            nf_dirty.sort()
            # actually copy
            clean = True
            try:
                with open(self.fn, 'r+b') as f:
                    # if we will be seeking beyond the image end, expand it
                    end = f.seek(0, 2)
                    last_start = max(start for start, i in nf_clean + nf_dirty)
                    if end < last_start:
                        f.truncate(last_start)
                    # split up the progress function
                    total = total_clean + total_dirty
                    p_clean = lambda d, t, n: progress(d, total, n)
                    def p_dirty (d, t, n):
                        if d is not None:
                            d += total_clean
                        return progress(d, total, n)
                    # perform the copy
                    fn = self.fn
                    for clean in (True, False):
                        to_copy = []
                        to_copy_names = []
                        for start, i in (nf_clean if clean else nf_dirty):
                            is_dir, str_start, this_fn, size = entries[i]
                            to_copy.append(((this_fn, 0, size), (f, start)))
                            to_copy_names.append(names[i])
                            entries[i] = (False, str_start, start, size)
                        failed = copy(to_copy, p_clean if clean else p_dirty,
                                      to_copy_names, can_cancel = clean)
                        if isinstance(failed, int):
                            # cancelled
                            cleanup(f)
                            return failed
                        elif failed:
                            msg = _('either couldn\'t read from \'{}\' or '
                                    'couldn\'t write to the disk image')
                            msg = msg.format(to_copy[failed[0]][0][0])
                            if clean:
                                error(msg, f)
                            else:
                                cleanup(f)
                                raise IOError(msg)
            except IOError as e:
                cleanup()
                if clean:
                    e.handled = True
                raise

        cleanup_tmp_dir()
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
        return False

    def _quick_compress (self):
        """Quick compress of the image.

Returns (changed, orig_size, new_size), where

changed: whether any changes were made to the tree.
orig_size, new_size: the size of the disk image file in bytes before and after
                     compression; these are None if there are no files in the
                     disk.

See compress for more details.

"""
        # get files, sorted by reverse position
        files = self.flatten_tree(dirs = False)
        if not files:
            return (False, None, None)
        entries = self.entries
        files = [[entries[i][2], entries[i][3], i, name, parent[None], tree_i]
                 for (name, i), parent, tree_i, path in files]
        files.sort(reverse = True)
        orig_size = sum(files[0][:2])
        # get start of file data
        data_start, i = max((e[1], i) for i, e in enumerate(entries))
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
        # repeatedly try to move every file earlier until none can
        changed = False
        this_changed = True
        while this_changed:
            this_changed = False
            # starting with the last file,
            n = 0
            for f_data in files:
                pos, size, i, name, d, d_i = f_data
                # put each file in the earliest possible gap
                for gap_i, (start, gap) in enumerate(free):
                    if gap >= size and start < pos:
                        # mark file moved
                        d[d_i] = (name, (i, start))
                        f_data[0] = start
                        # change gap entry
                        end = start + gap
                        start = align(start + size)
                        gap = end - start
                        if gap > 0:
                            free[gap_i] = (start, gap)
                            free.sort()
                        else:
                            free.pop(gap_i)
                        this_changed = True
                        changed = True
                        n += 1
                        break
            # resort files
            files.sort(reverse = True)
        # move last file to end of previous file if possible
        start = align(sum(files[1][:2]) if len(files) > 1 else data_start)
        pos, size, i, name, d, d_i = files[0]
        if pos > start:
            d[d_i] = (name, (i, start))
            files[0][0] = pos
            changed = True
        return (changed, orig_size, sum(files[0][:2]))

    def _slow_compress (self, tmp_dir, progress = None):
        """Slow compress of the image.

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

    def compress (self, progress = None, tree_ready = False):
        """Compress the image.

compress([progress]) -> cancelled

progress: a function to call to indicate progress.  See the same argument to
          the write method for details.

cancelled: whether the action was cancelled (through the progress function).
           If so, this is the value used to cancel it (2 or 3).

This function removes all free space in the image's filesystem to make it
smaller.  GameCube images often have a load of free space between the
filesystem string table and the file data, sometimes hundreds of MiB.  This
will also remove free space between files that may have been opened up by
deletions or other editing.

This method calls the write method; see its documentation for information on
exceptions.

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
should also be faster and doesn't use any extra disk space (or memory, if
you're thinking of a ramdisk).  This should be good enough for most people.

As implied above, a full compress may use some extra disk space.  While
unlikely, this may be as much as the size of this disk image.  More
importantly, if tmp_dir is not given, the directory used might be on a ramdisk,
so we could end up running out of memory.  Be careful.

This method calls the write method; see its documentation for information on
exceptions.

IMPORTANT: any changes that have been made to the tree are discarded before
compressing.  Make sure you write everything you want to keep first.

"""
        # discard changes
        if not tree_ready:
            self.build_tree()
        if tree_ready or self._quick_compress()[0]:
            try:
                rtn = self.write(progress = progress)
            except Exception as e:
                if hasattr(e, 'handled') and e.handled is True:
                    # didn't finish: clean up tree
                    self.build_tree()
                raise
            if rtn is True:
                # cancelled: clean up tree
                self.build_tree()
            return rtn
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

    def decompress (self, progress = None):
        """Decompress the disk image to exactly 1459978240 bytes.

decompress([progress]) -> cancelled

progress: a function to call to indicate progress.  See the same argument to
          the write method for details.

cancelled: whether the action was cancelled (through the progress function).
           If so, this is the value used to cancel it (2 or 3).

If the disk is larger than the required size, compression is attempted first.
If it can be compressed to become small enough, it is compressed and then
decompressed; otherwise, ValueError is raised (and has a 'handled' attribute
which is True).

        """
        target_size = 1459978240
        size = max(0, *(
            start + size for is_dir, str_start, start, size in self.entries
        ))
        if size > target_size:
            # too large: try compressing
            changed, orig_size, new_size = self._quick_compress()
            if changed and new_size <= target_size:
                # can get small enough by compressing
                cancelled = self.compress(progress, True)
                if cancelled:
                    return cancelled
            else:
                # restore tree
                self.build_tree()
                msg = _('the disk is too large to fit in 1459978240 bytes')
                e = ValueError(msg)
                e.handled = True
                raise e
        elif size == target_size:
            return False
        # else small enough
        # if we got here, we want to just truncate
        with open(self.fn, 'r+b') as f:
            f.truncate(target_size)
        return False


class DiskError (EnvironmentError):
    """Exception subclass raised for invalid disk images."""
    pass
