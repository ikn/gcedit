import sys
import os
import gcutil

from . import command


class DumpCommand (command.Command):
    name = 'dump'

    def init_args (self, parser):
        command.add_disk_arg(parser)
        parser.add_argument('dest', type=str)
        parser.add_argument('-f', '--overwrite', action='store_true')

    def execute (self, args):
        fs = gcutil.GCFS(args.disk)
        failed = fs.extract([
            (-1, args.dest)
        ], args.overwrite, command.progress_fn(args))
        print(file=sys.stderr)

        if failed:
            print('error: the following could not be created:', failed,
                  file=sys.stderr)
