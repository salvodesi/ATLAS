"""A folder sent to the Recycle Bin of Windows, or to the trash of the Linux desktop (it can be restored from
there), not deleted for good."""
import sys
from pathlib import Path

FO_DELETE = 3
FOF_ALLOWUNDO = 0x40  # to the Recycle Bin
FOF_NOCONFIRMATION = 0x10  # the tool has already asked
FOF_SILENT = 0x4
FOF_NOERRORUI = 0x400


class TrashError(OSError):
    pass


def move_to_trash(path):
    """Send `path` (a folder or a file) to the trash. Raises TrashError if the system does not do it."""
    path = Path(path).resolve()
    if not path.exists():
        return
    if sys.platform == "win32":
        _to_recycle_bin(path)
    else:
        _to_desktop_trash(path)


def _to_recycle_bin(path):
    import ctypes
    from ctypes import wintypes

    class _SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_uint16),
                    ("fAnyOperationsAborted", wintypes.BOOL), ("hNameMappings", ctypes.c_void_p),
                    ("lpszProgressTitle", wintypes.LPCWSTR)]

    operation = _SHFILEOPSTRUCTW(wFunc=FO_DELETE, pFrom=f"{path}\0\0",  # double NUL: list of paths
                                 fFlags=FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI)
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    if result != 0 or operation.fAnyOperationsAborted or path.exists():
        raise TrashError(f"Windows non ha spostato {path} nel Cestino (codice {result}): un file potrebbe essere "
                         "aperto in un altro programma.")


def _to_desktop_trash(path):
    from PySide6.QtCore import QFile

    # Qt follows the freedesktop.org specification: ~/.local/share/Trash, restorable from the file manager.
    moved = QFile.moveToTrash(str(path))
    if not (moved[0] if isinstance(moved, tuple) else moved) or path.exists():
        raise TrashError(f"Non è stato possibile spostare {path} nel cestino.")
