import os
import gcutil

from . import command


def follow_path (tree, path, clear=False):
    created = False

    for part in path:
        if command.check_tree_file(tree, part, clear) is not None:
            return None

        d = command.tree_dir(tree, part)
        if d is None:
            new_tree = {None: []}
            tree[(part, None)] = new_tree
            created = True
        else:
            new_tree = tree[d]

        tree = new_tree

    return (tree, created)


class ImportCommand (command.Command):
    name = 'import'

    def init_args (self, parser):
        command.add_disk_arg(parser)
        parser.add_argument('source', type=str)
        parser.add_argument('dest', type=str)
        parser.add_argument('-f', '--overwrite', action='store_true')
        parser.add_argument('-l', '--follow-symlinks', action='store_true')

    def execute (self, args):
        fs = gcutil.GCFS(args.disk)
        dest = command.GCPath(args.dest)
        overwrite = args.overwrite

        if os.path.isdir(args.source):
            dest_tree, created = follow_path(fs.tree, dest, overwrite)
            if dest_tree is None:
                command.err_overwrite(dest)
            if not created:
                if overwrite:
                    command.empty_tree(dest_tree)
                else:
                    command.err_overwrite(dest)
            dest_tree.update(gcutil.tree_from_dir(args.source,
                                                  args.follow_symlinks))

        else:
            if dest.name is None:
                command.error('cannot write a file as the disk root')
            dest_tree = follow_path(fs.tree, dest.parent, overwrite)[0]
            if dest_tree is None:
                command.err_overwrite(dest)
            if command.check_tree_dir(
                dest_tree, dest.name, overwrite
            ) is not None:
                command.err_overwrite(dest)
            if command.check_tree_file(
                dest_tree, dest.name, overwrite
            ) is not None:
                command.err_overwrite(dest)
            dest_tree[None].append((dest.name, args.source))

        command.fs_write(fs, args)
