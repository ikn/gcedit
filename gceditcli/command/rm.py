import os
import gcutil

from . import command


class RmCommand (command.Command):
    name = 'rm'

    def init_args (self, parser):
        command.add_disk_arg(parser)
        parser.add_argument('path', type=str)
        parser.add_argument('-f', '--ignore-missing', action='store_true')
        parser.add_argument('--allow-remove-root', action='store_true')

    def execute (self, args):
        fs = gcutil.GCFS(args.disk)
        path = command.GCPath(args.path)

        tree = fs.tree
        for part in path.parent:
            d = command.tree_dir(tree, part)
            if d is None:
                break
            else:
                tree = tree[d]

        if tree is None and not args.ignore_missing:
            command.err_missing(path)

        if path.name is None:
            if args.allow_remove_root:
                command.empty_tree(tree)
            else:
                command.error('refusing to remove the root directory')

        else:
            d = command.tree_dir(tree, path.name)
            f = command.tree_file(tree, path.name)
            if d is None and f is None and not args.ignore_missing:
                command.err_missing(path)
            if d is not None:
                del tree[d]
            if f is not None:
                command.rm_tree_file(tree, path.name)

        command.fs_write(fs, args)
