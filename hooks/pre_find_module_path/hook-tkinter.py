"""Keep tkinter available when the build host cannot initialize a Tk window.

The application bundles its own Tcl/Tk runtime via build.spec and runtime_tk.py,
so PyInstaller must analyze tkinter instead of excluding it based on the host.
"""


def pre_find_module_path(hook_api):
    pass
