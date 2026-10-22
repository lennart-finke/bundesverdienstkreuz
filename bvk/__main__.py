import importlib, sys
cmd, *a = sys.argv[1:]
if cmd == 'stats': from .merge import stats; stats()
else: importlib.import_module(f'bvk.src_{a.pop(0)}' if cmd == 'fetch' else f'bvk.{cmd}').run(*a)
