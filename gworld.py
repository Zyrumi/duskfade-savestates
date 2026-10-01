"""
Locates Duskfade's GWorld global via an external (no-injection) AOB
signature scan, so autosplitter.py can detect "a new UWorld was just
created" as a stand-in for "New Game confirmed" -- read-only, only ever
calls ReadProcessMemory.

Signatures ported from GSpots (github.com/Do0ks/GSpots, GOffsets/GOffsets.cpp),
a purpose-built external UE GWorld/GNames/GObjects finder. The RVA this
resolves to is a fixed offset baked into the compiled exe -- stable across
relaunches and across machines running the same game build, even though the
module's base address itself shifts every launch under ASLR.
"""
from __future__ import annotations

import ctypes
import re
import struct
from ctypes import wintypes

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
MAX_MODULE_NAME32 = 255
MAX_PATH = 260

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * MAX_PATH),
    ]


def find_pid(exe_name: str) -> int | None:
    """Pure-ctypes process lookup by exact exe filename (cheap enough to
    call every poll -- no subprocess/powershell spawn)."""
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1 or snap == 0:
        return None
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == exe_name.lower():
                return entry.th32ProcessID
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return None

GWORLD_SIGNATURES = [
    (bytes([0x48, 0x89, 0x05, 0x00, 0x00, 0x00, 0x00, 0x00, 0x8B, 0x00, 0x00, 0x00,
             0xF6, 0x86, 0x3B, 0x01, 0x00, 0x00, 0x40]),
     "xxx?????x???xxxxxxx"),
    (bytes([0x48, 0x89, 0x05, 0x00, 0x00, 0x00, 0x00, 0x00, 0x8B, 0x00, 0x00, 0xF6,
             0x86, 0x3B, 0x01, 0x00, 0x00, 0x40]),
     "xxx?????x??xxxxxxx"),
    (bytes([0x48, 0x89, 0x05, 0x00, 0x00, 0x00, 0x00, 0x00, 0x8B, 0x00, 0x00, 0x00,
             0x00, 0x00, 0xF6, 0x86, 0x00, 0x01, 0x00, 0x00, 0x40]),
     "xxx?????x?????xx?xxxx"),
    (bytes([0x00, 0x8B, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x48, 0x89, 0x05, 0x00,
             0x00, 0x00, 0x00, 0x00, 0x8B, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
             0x00, 0x00, 0x00, 0x00, 0x00]),
     "?x???xx?xxx?????x???xx?????x?"),
    (bytes([0x48, 0x89, 0x05, 0x00, 0x00, 0x00, 0x02, 0x48, 0x8B, 0x8F, 0xA0, 0x00,
             0x00, 0x00]),
     "xxx???xxxxx???"),
    (bytes([0x48, 0x89, 0x05, 0x00, 0x00, 0x00, 0x00, 0x49, 0x8B, 0x00, 0x78, 0xF6,
             0x00, 0x3B, 0x01, 0x00, 0x00, 0x40]),
     "xxx????xx?xx?xx??x"),
    (bytes([0xE8, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x8B, 0x00, 0x78, 0x48, 0x89, 0x05,
             0x00, 0x00, 0x00, 0x00, 0x00, 0x8B, 0x00, 0x78]),
     "x???x?x?xxxx?????x?x"),
    (bytes([0x48, 0x89, 0x05, 0x00, 0x00, 0x00, 0x00, 0x00, 0x8B, 0x00, 0x88, 0x00,
             0x00, 0x00, 0xF6, 0x00, 0x0B, 0x01, 0x00, 0x00, 0x40, 0x75, 0x00]),
     "xxx?????x?x???x?xx??xx?"),
]
GWORLD_PREFIX = bytes([0x48, 0x89, 0x05])

GNAMES_SIGNATURES = [
    (bytes([0x48, 0x8D, 0x0D, 0x00, 0x00, 0x00, 0x00, 0xE8, 0x00, 0x00, 0xFE, 0xFF,
             0x4C, 0x8B, 0xC0, 0xC6, 0x05, 0x00, 0x00, 0x00, 0x00, 0x01]),
     "xxx????x??xxxxxxx????x"),
    (bytes([0x48, 0x8D, 0x0D, 0x00, 0x00, 0x00, 0x03, 0xE8, 0x00, 0x00, 0xFF, 0xFF,
             0x4C, 0x00, 0xC0]),
     "xxx???xx??xxx?x"),
    (bytes([0x48, 0x8D, 0x0D, 0x00, 0x00, 0x00, 0x00, 0xE8, 0x00, 0x00, 0xFF, 0xFF,
             0x48, 0x8B, 0xD0, 0xC6, 0x05, 0x00, 0x00, 0x00, 0x00, 0x01]),
     "xxx????x??xxxxxxx????x"),
    (bytes([0x48, 0x8B, 0x05, 0x00, 0x00, 0x00, 0x02, 0x48, 0x85, 0xC0, 0x75, 0x5F,
             0xB9, 0x08, 0x08, 0x00]),
     "xxx???xxxxxxxxx?"),
]
GNAMES_PREFIXES = (bytes([0x48, 0x8D, 0x0D]), bytes([0x48, 0x8B, 0x05]))

NONE_U32 = struct.unpack("<I", b"None")[0]
COREUOBJ_U64 = struct.unpack("<Q", b"CoreUObj")[0]
BYTE_U32 = struct.unpack("<I", b"Byte")[0]

# Empirically confirmed against a live run this session (decoding UWorld's
# own name at both the main menu and after New Game correctly produced
# "MenuInicio" / "IntroCinematica" / "Tutorial") -- FNamePool block width
# for this game build. Dumper-7 normally auto-derives this via a whole
# separate GObjects cross-check; 16 is simply what this build uses.
NAME_POOL_BLOCK_OFFSET_BITS = 16

MENU_WORLD_NAME = "MenuInicio"


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("th32ModuleID", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("GlblcntUsage", wintypes.DWORD),
        ("ProccntUsage", wintypes.DWORD),
        ("modBaseAddr", ctypes.POINTER(ctypes.c_byte)),
        ("modBaseSize", wintypes.DWORD),
        ("hModule", wintypes.HMODULE),
        ("szModule", ctypes.c_wchar * (MAX_MODULE_NAME32 + 1)),
        ("szExePath", ctypes.c_wchar * MAX_PATH),
    ]


def open_process(pid: int):
    handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    return handle if handle else None


def read_region(handle, base: int, size: int) -> bytes | None:
    buf = ctypes.create_string_buffer(size)
    bytes_read = ctypes.c_size_t(0)
    ok = kernel32.ReadProcessMemory(handle, ctypes.c_void_p(base), buf, size, ctypes.byref(bytes_read))
    if not ok or bytes_read.value == 0:
        return None
    return buf.raw[: bytes_read.value]


def get_module_range(pid: int, name_substr: str):
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, pid)
    if snap == -1 or snap == 0:
        return None
    try:
        entry = MODULEENTRY32W()
        entry.dwSize = ctypes.sizeof(MODULEENTRY32W)
        ok = kernel32.Module32FirstW(snap, ctypes.byref(entry))
        while ok:
            if name_substr.lower() in entry.szModule.lower():
                base = ctypes.cast(entry.modBaseAddr, ctypes.c_void_p).value or 0
                return (base, entry.modBaseSize)
            ok = kernel32.Module32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return None


def _build_mask_regex(pattern: bytes, mask: str):
    parts = [re.escape(bytes([b])) if m == "x" else b"." for b, m in zip(pattern, mask)]
    return re.compile(b"".join(parts), re.DOTALL)


def find_gworld_rva(handle, module_base: int, module_size: int) -> int | None:
    """Returns the GWorld global's RVA (offset from module base), or None."""
    data = read_region(handle, module_base, module_size)
    if data is None:
        return None
    for pattern, mask in GWORLD_SIGNATURES:
        rx = _build_mask_regex(pattern, mask)
        m = rx.search(data)
        if not m:
            continue
        found = m.start()
        adjusted = found
        window_end = min(found + 30, len(data) - 7)
        for j in range(found, window_end + 1):
            if data[j:j + 3] == GWORLD_PREFIX:
                adjusted = j
                break
        if adjusted + 7 > len(data):
            continue
        disp = struct.unpack_from("<i", data, adjusted + 3)[0]
        rva = (adjusted + 7) + disp
        if 0 <= rva < module_size:
            return rva
    return None


def find_gnames_rva(handle, module_base: int, module_size: int) -> int | None:
    data = read_region(handle, module_base, module_size)
    if data is None:
        return None
    for pattern, mask in GNAMES_SIGNATURES:
        rx = _build_mask_regex(pattern, mask)
        m = rx.search(data)
        if not m:
            continue
        found = m.start()
        adjusted = found
        window_end = min(found + 30, len(data) - 7)
        for j in range(found, window_end + 1):
            if data[j:j + 3] in GNAMES_PREFIXES:
                adjusted = j
                break
        if adjusted + 7 > len(data):
            continue
        disp = struct.unpack_from("<i", data, adjusted + 3)[0]
        rva = (adjusted + 7) + disp
        if 0 <= rva < module_size:
            return rva
    return None


class NamePool:
    """Ported from Dumper-7's NameArray.cpp/.h (github.com/Encryqed/Dumper-7)
    -- discovers a UE5 FNamePool's internal layout live (chunk-table start,
    per-entry header size/stride, header length-field shift) and resolves
    an FName comparison-index to its real string. Read-only."""

    def __init__(self, handle, pool_base: int):
        self.handle = handle
        self.pool_base = pool_base
        self.chunks_start = None
        self.stride = None
        self.header_offset = None
        self.string_offset = None
        self.shift_count = None
        self._chunk_ptr_cache: dict[int, int] = {}

    def _read(self, addr, size):
        return read_region(self.handle, addr, size)

    def initialize(self) -> bool:
        header = self._read(self.pool_base, 8 + 0x10000 + 0x20)
        if header is None:
            return False
        for i in range(0, 0x20, 4):
            possible = struct.unpack_from("<i", header, i)[0]
            if possible <= 0 or possible > 0x10000:
                continue
            not_null_count = 0
            found_first_ptr = False
            chunks_start_candidate = None
            num_invalid = 0
            j = 0
            while j < 0x10000:
                chunk_off = i + 8 + j + (i % 8)
                if chunk_off + 8 > len(header):
                    break
                ptr = struct.unpack_from("<Q", header, chunk_off)[0]
                if ptr != 0:
                    not_null_count += 1
                    num_invalid = 0
                    if not found_first_ptr:
                        found_first_ptr = True
                        chunks_start_candidate = chunk_off
                else:
                    num_invalid += 1
                    if num_invalid == 0x500:
                        break
                j += 8
            if possible == (not_null_count - 1):
                self.chunks_start = chunks_start_candidate
                break
        if self.chunks_start is None:
            return False

        first_chunk_ptr_bytes = self._read(self.pool_base + self.chunks_start, 8)
        if first_chunk_ptr_bytes is None:
            return False
        first_chunk_ptr = struct.unpack("<Q", first_chunk_ptr_bytes)[0]
        chunk_bytes = self._read(first_chunk_ptr, 0x1000)
        if chunk_bytes is None:
            return False

        header_size = None
        found_core = False
        for i in range(0, len(chunk_bytes) - 8):
            if header_size is None and struct.unpack_from("<I", chunk_bytes, i)[0] == NONE_U32:
                header_size = i
            if struct.unpack_from("<Q", chunk_bytes, i)[0] == COREUOBJ_U64:
                found_core = True
                break
        if not found_core or header_size is None:
            return False

        self.stride = 2 if header_size == 2 else 4
        self.string_offset = header_size
        self.header_offset = 4 if header_size == 6 else 0

        assumed = first_chunk_ptr + self.string_offset + 4  # NoneStrLen = 4
        for _fudge in range(4):
            assumed_bytes = self._read(assumed, self.string_offset + 4)
            if assumed_bytes is not None and len(assumed_bytes) >= self.string_offset + 4:
                if struct.unpack_from("<I", assumed_bytes, self.string_offset)[0] == BYTE_U32:
                    break
            assumed += 1

        header_bytes = self._read(assumed, 2 + self.header_offset)
        if header_bytes is None or len(header_bytes) < self.header_offset + 2:
            return False
        bp_header = struct.unpack_from("<H", header_bytes, self.header_offset)[0]
        shift = 0
        while bp_header != 0xC and shift < 16:
            shift += 1
            bp_header >>= 1
        if shift >= 16:
            return False
        self.shift_count = shift
        return True

    def _chunk_ptr(self, chunk_idx: int) -> int | None:
        if chunk_idx in self._chunk_ptr_cache:
            return self._chunk_ptr_cache[chunk_idx]
        data = self._read(self.pool_base + 0x10 + chunk_idx * 8, 8)
        if data is None:
            return None
        ptr = struct.unpack("<Q", data)[0]
        self._chunk_ptr_cache[chunk_idx] = ptr
        return ptr

    def decode(self, comparison_index: int, block_offset_bits: int = NAME_POOL_BLOCK_OFFSET_BITS, _depth=0) -> str | None:
        if _depth > 3 or comparison_index < 0:
            return None
        chunk_idx = comparison_index >> block_offset_bits
        in_chunk_off = (comparison_index & ((1 << block_offset_bits) - 1)) * self.stride
        chunk_ptr = self._chunk_ptr(chunk_idx)
        if not chunk_ptr:
            return None
        addr = chunk_ptr + in_chunk_off
        raw = self._read(addr, self.header_offset + 2 + 512)
        if raw is None:
            return None
        header = struct.unpack_from("<H", raw, self.header_offset)[0]
        name_len = header >> self.shift_count
        is_wide = header & 0x1
        if name_len == 0:
            entry_id_off = self.string_offset + (2 if self.string_offset == 6 else 0)
            if entry_id_off + 8 > len(raw):
                return None
            next_idx = struct.unpack_from("<i", raw, entry_id_off)[0]
            number = struct.unpack_from("<i", raw, entry_id_off + 4)[0]
            base = self.decode(next_idx, block_offset_bits, _depth + 1)
            if base is None:
                return None
            return f"{base}_{number - 1}" if number > 0 else base
        try:
            if is_wide:
                n = name_len * 2
                return raw[self.string_offset:self.string_offset + n].decode("utf-16-le")
            return raw[self.string_offset:self.string_offset + name_len].decode("ascii")
        except (UnicodeDecodeError, IndexError):
            return None


class GWorldWatcher:
    """Resolves GWorld's RVA once per process attach (cheap re-scan only
    when the target process's PID changes, e.g. the game was restarted),
    then lets the caller cheaply re-read the live UWorld* on every poll."""

    def __init__(self, exe_name_substr: str = "Duskfade-Win64-Shipping"):
        self.exe_name_substr = exe_name_substr
        self._pid = None
        self._handle = None
        self._gworld_addr = None
        self._name_pool = None

    def _attach(self, pid: int) -> bool:
        self._pid = pid
        if self._handle is not None:
            kernel32.CloseHandle(self._handle)
        self._handle = open_process(pid)
        self._name_pool = None
        if self._handle is None:
            return False
        mod = get_module_range(pid, self.exe_name_substr + ".exe")
        if mod is None:
            return False
        mod_base, mod_size = mod
        rva = find_gworld_rva(self._handle, mod_base, mod_size)
        if rva is None:
            return False
        self._gworld_addr = mod_base + rva

        names_rva = find_gnames_rva(self._handle, mod_base, mod_size)
        if names_rva is not None:
            pool = NamePool(self._handle, mod_base + names_rva)
            if pool.initialize():
                self._name_pool = pool
        # A missing/failed name pool isn't fatal -- poll_name() just
        # returns None and callers should treat that as "unknown".
        return True

    def read_uworld_ptr(self, pid: int) -> int | None:
        """Returns the current live UWorld* value, or None if the target
        process isn't attached / readable right now (e.g. game not
        running, or between process restarts)."""
        if pid != self._pid or self._gworld_addr is None:
            if not self._attach(pid):
                return None
        data = read_region(self._handle, self._gworld_addr, 8)
        if data is None:
            # Handle may have gone stale (e.g. game closed and relaunched
            # with a reused PID coincidentally) -- force a re-attach next time.
            self._pid = None
            return None
        return struct.unpack("<Q", data)[0]

    def poll(self) -> int | None:
        """Looks up the game process itself too -- returns the live
        UWorld* value, or None if Duskfade isn't running / not readable
        right now."""
        pid = find_pid(self.exe_name_substr + ".exe")
        if pid is None:
            self._pid = None
            return None
        return self.read_uworld_ptr(pid)

    def poll_name(self) -> str | None:
        """Returns the current UWorld's own decoded level name (e.g.
        "MenuInicio", "Tutorial", "Forest1"), or None if the game isn't
        running or the name couldn't be read/decoded right now."""
        uworld_ptr = self.poll()
        if not uworld_ptr or self._name_pool is None:
            return None
        name_bytes = read_region(self._handle, uworld_ptr + 0x18, 8)
        if name_bytes is None:
            return None
        comp_idx, _number = struct.unpack("<ii", name_bytes)
        return self._name_pool.decode(comp_idx)
