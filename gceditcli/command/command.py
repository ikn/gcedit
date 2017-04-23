import abc
import sys
import json


class Command (metaclass=abc.ABCMeta):
    name = None

    @abc.abstractmethod
    def init_args (self, parser):
        pass

    def init (self, subparsers):
        parser = subparsers.add_parser(self.name)
        parser.set_defaults(execute=self.execute)
        self.init_args(parser)

    @abc.abstractmethod
    def execute (self, args):
        pass


class GCPath:
    def __init__ (self, path):
        parts = path.split('/') if isinstance(path, str) else path
        self._path = [p for p in parts if p]

    def __getitem__ (self, i):
        return self._path[i]

    def __iter__ (self):
        return iter(self._path)

    def __str__ (self):
        return '/' + '/'.join(self)

    def __repr__ (self):
        return '<Path {}>'.format(str(self))

    @property
    def parent (self):
        return GCPath(self._path[:-1])

    @property
    def name (self):
        return self._path[-1] if self._path else None


def error (*msg):
    print('error:', *msg, file=sys.stderr)
    sys.exit(1)


def err_missing (path):
    error('no such path in disk:', repr(str(path)))


def err_overwrite (dest_path):
    error('not overwriting existing path in disk:', repr(str(dest_path)))


def add_disk_arg (parser):
    parser.add_argument('disk', type=str)


def output_json (obj):
    json.dump(obj, sys.stdout, indent=4, sort_keys=True)
    print()


def tree_dir (tree, test_name):
    for name, idx in (k for k in tree if k is not None):
        if name == test_name:
            return (name, idx)


def check_tree_dir (tree, test_name, clear):
    d = tree_dir(tree, test_name)
    if d is not None:
        if clear:
            del tree[d]
        else:
            return d


def tree_file (tree, test_name):
    for name, idx in tree[None]:
        if name == test_name:
            return (name, idx)


def rm_tree_file (tree, rm_name):
    tree[None] = [(name, idx) for name, idx in tree[None] if name != rm_name]


def check_tree_file (tree, test_name, clear):
    if clear:
        rm_tree_file(tree, test_name)
    else:
        return tree_file(tree, test_name)


def empty_tree (tree):
    tree.clear()
    tree[None] = []


def progress_fn (args):
    last_len = 0

    def progress (done, total, fn):
        nonlocal last_len
        r = '{:.0f}'.format(100 * done / total).rjust(3, ' ')
        s = ' {}% ({})'.format(r, fn)
        this_len = len(s)
        # \r moves back to the start of the line, even on Windows cmd
        print('\r' + s.ljust(last_len, ' '), end='', file=sys.stderr)
        last_len = this_len

    return progress if args.display_progress else None


def fs_write (fs, args):
    fs.write(progress=progress_fn(args))
    print(file=sys.stderr)
