import os
import gcutil

from . import command


class LsCommand (command.Command):
    name = 'ls'

    def init_args (self, parser):
        command.add_disk_arg(parser)
        parser.add_argument('path', type=str, nargs='?')
        parser.add_argument('-s', '--include-dir-size', action='store_true')

    def execute (self, args):
        fs = gcutil.GCFS(args.disk)
        path = command.GCPath(()) if args.path is None else command.GCPath(args.path)

        tree = fs.tree
        for part in path:
            d = command.tree_dir(tree, part)
            if d is None:
                command.err_missing(path)
            else:
                tree = tree[d]

        dirs = []
        for name, idx in (k for k in tree if k is not None):
            entry = {'name': name}
            if args.include_dir_size:
                entry['size'] = fs.tree_size(tree[(name, idx)], True)
            dirs.append(entry)

        files = []
        for name, idx in tree[None]:
            files.append({'name': name, 'size': fs.entries[idx][3]})

        command.output_json({'directories': dirs, 'files': files})
