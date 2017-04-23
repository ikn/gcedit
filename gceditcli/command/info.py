import gcutil

from . import command


class InfoCommand (command.Command):
    name = 'info'

    def init_args (self, parser):
        command.add_disk_arg(parser)

    def execute (self, args):
        fs = gcutil.GCFS(args.disk)
        entries = fs.tree_size(fs.tree)
        size = fs.tree_size(fs.tree, True)
        info = fs.get_info()

        bnrs = {}
        for name, idx in fs.tree[None]:
            if name.endswith('.bnr'):
                bnr = fs.get_bnr_info(idx)
                bnrs[name] = {
                    'name': bnr['name'],
                    'full_name': bnr['full name'],
                    'developer': bnr['developer'],
                    'full_developer': bnr['full developer'],
                    'description': bnr['description'],
                }

        command.output_json({
            'files': {
                'number': fs.num_entries,
                'number_reachable': entries + 1, # including root
                'total_size': size
            },
            'game': {
                'code': info['code'],
                'version': info['version'],
                'name': info['name']
            },
            'apploader_version': info['apploader version'],
            'banners': bnrs
        })
