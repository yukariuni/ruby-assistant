"""Mémoire du processus courant, comme la colonne « Mémoire » du Gestionnaire des tâches (jeu de travail privé), en Mo."""
import ctypes
from ctypes import wintypes


class _PMC(ctypes.Structure):  # PROCESS_MEMORY_COUNTERS_EX2
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD), ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t), ("PrivateUsage", ctypes.c_size_t), ("PrivateWorkingSetSize", ctypes.c_size_t),
                ("SharedCommitUsage", ctypes.c_ulonglong)]


def private_mb():
    try:
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = wintypes.HANDLE
        k.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PMC), wintypes.DWORD]
        p = _PMC()
        p.cb = ctypes.sizeof(p)
        k.K32GetProcessMemoryInfo(k.GetCurrentProcess(), ctypes.byref(p), p.cb)
        return int(p.PrivateWorkingSetSize >> 20)
    except Exception:  # pas Windows, ou API indisponible: on n'affiche simplement pas la mesure
        return 0


def trim():
    """Rend à Windows les pages mémoire inutilisées de ce processus (comme il le fait lui-même pour une fenêtre réduite).

    À n'appeler que quand les gros modèles sont déchargés: sinon leurs poids partiraient sur le disque. Les pages dont le moteur a
    vraiment besoin reviennent d'elles-mêmes en quelques millisecondes (mesuré: le moteur à l'écoute n'en utilise que ≈26 Mo)."""
    try:
        k, ps = ctypes.windll.kernel32, ctypes.windll.psapi
        k.GetCurrentProcess.restype = wintypes.HANDLE
        ps.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
        ps.EmptyWorkingSet.restype = wintypes.BOOL
        return bool(ps.EmptyWorkingSet(k.GetCurrentProcess()))
    except Exception:
        return False
