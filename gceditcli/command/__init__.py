from . import info, ls, rm, import_, dump

all_commands = [
    info.InfoCommand, ls.LsCommand,
    rm.RmCommand, import_.ImportCommand, dump.DumpCommand
]
