import uctypes

# http://www.gnu.org/software/tar/manual/html_node/Standard.html
TAR_HEADER = {
    "name": (uctypes.ARRAY | 0, uctypes.UINT8 | 100),
    "size": (uctypes.ARRAY | 124, uctypes.UINT8 | 12),
    "checksum": (uctypes.ARRAY | 148, uctypes.UINT8 | 8),
    "typeflag": (uctypes.ARRAY | 156, uctypes.UINT8 | 1),
    "prefix": (uctypes.ARRAY | 345, uctypes.UINT8 | 155),
}

DIRTYPE = "dir"
REGTYPE = "file"

def roundup(val, align):
    return (val + align - 1) & ~(align - 1)

class FileSection:

    def __init__(self, f, content_len, aligned_len):
        self.f = f
        self.content_len = content_len
        self.align = aligned_len - content_len

    def read(self, sz=65536):
        if self.content_len == 0:
            return b""
        if sz > self.content_len:
            sz = self.content_len
        data = self.f.read(sz)
        if not data:
            raise ValueError("Truncated TAR file body")
        sz = len(data)
        self.content_len -= sz
        return data

    def readinto(self, buf):
        if self.content_len == 0:
            return 0
        if len(buf) > self.content_len:
            buf = memoryview(buf)[:self.content_len]
        sz = self.f.readinto(buf)
        if not sz:
            raise ValueError("Truncated TAR file body")
        self.content_len -= sz
        return sz

    def skip(self):
        remaining = self.content_len + self.align
        while remaining:
            data = self.f.read(min(remaining, 512))
            if not data:
                raise ValueError("Truncated TAR file body or padding")
            remaining -= len(data)
        self.content_len = 0
        self.align = 0

class TarInfo:

    def __init__(self, name="", type=REGTYPE, size=0):
        self.name = name
        self.type = type
        self.size = size
        self.subf = None  # Will be initialized as FileSection when needed

    def __str__(self):
        return "TarInfo(%r, %s, %d)" % (self.name, self.type, self.size)

class TarFile:

    def __init__(self, name=None, fileobj=None):
        self._owns_file = fileobj is None
        if fileobj:
            self.f = fileobj
        elif name is not None:
            self.f = open(name, "rb")
        else:
            raise ValueError("Either name or fileobj must be provided to TarFile")
        self.subf = None

    def next(self):
            if self.subf:
                self.subf.skip()
            buf = self.f.read(512)
            if not buf:
                return None
            if len(buf) != 512:
                raise ValueError("Truncated TAR header")

            h = uctypes.struct(uctypes.addressof(buf), TAR_HEADER, uctypes.LITTLE_ENDIAN) # type: ignore

            # Empty block means end of archive
            if h.name[0] == 0:
                if any(buf):
                    raise ValueError("Invalid TAR end block")
                return None

            try:
                expected_checksum = int(bytes(h.checksum).rstrip(b"\0 ").strip(), 8)
            except ValueError:
                raise ValueError("Invalid TAR header checksum field")
            checksum_buf = bytearray(buf)
            checksum_buf[148:156] = b"        "
            if sum(checksum_buf) != expected_checksum:
                raise ValueError("Invalid TAR header checksum")

            d = TarInfo()
            # Name and size are null-terminated strings
            name = str(h.name, "utf-8").rstrip("\0")
            prefix = str(h.prefix, "utf-8").rstrip("\0")
            d.name = prefix + "/" + name if prefix else name
            try:
                d.size = int(bytes(h.size).rstrip(b"\0").strip(), 8)
            except ValueError:
                # Handle cases where size might be non-numeric or badly formatted
                # Or if the field is all nulls, int conversion might fail
                # Depending on strictness, could raise error or set default
                raise ValueError("Invalid TAR size field")

            typeflag = bytes(h.typeflag)
            if typeflag == b"5":
                d.type = DIRTYPE
                if d.size != 0:
                    raise ValueError("TAR directory has non-zero size")
            elif typeflag in (b"0", b"\0"):
                d.type = REGTYPE
            else:
                raise ValueError("Unsupported TAR entry type")
            
            self.subf = d.subf = FileSection(self.f, d.size, roundup(d.size, 512)) # type: ignore
            return d

    def __iter__(self):
        return self

    def __next__(self):
        v = self.next()
        if v is None:
            raise StopIteration
        return v

    def extractfile(self, tarinfo):
        return tarinfo.subf

    def close(self):
        if self._owns_file and self.f:
            self.f.close()
        self.f = None
