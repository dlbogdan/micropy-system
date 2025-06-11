import uctypes

# http://www.gnu.org/software/tar/manual/html_node/Standard.html
TAR_HEADER = {
    "name": (uctypes.ARRAY | 0, uctypes.UINT8 | 100),
    "size": (uctypes.ARRAY | 124, uctypes.UINT8 | 12),
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
        sz = len(data)
        self.content_len -= sz
        return data

    def readinto(self, buf):
        if self.content_len == 0:
            return 0
        if len(buf) > self.content_len:
            buf = memoryview(buf)[:self.content_len]
        sz = self.f.readinto(buf)
        self.content_len -= sz
        return sz

    def skip(self):
        self.f.read(self.content_len + self.align)

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

            h = uctypes.struct(uctypes.addressof(buf), TAR_HEADER, uctypes.LITTLE_ENDIAN) # type: ignore

            # Empty block means end of archive
            if h.name[0] == 0:
                return None

            d = TarInfo()
            # Name and size are null-terminated strings
            d.name = str(h.name, "utf-8").rstrip("\0")
            try:
                d.size = int(bytes(h.size).rstrip(b"\0").strip(), 8)
            except ValueError:
                # Handle cases where size might be non-numeric or badly formatted
                # Or if the field is all nulls, int conversion might fail
                # Depending on strictness, could raise error or set default
                d.size = 0 # Or raise an exception

            # Type is determined by the last character of the name
            if d.name and d.name[-1] == "/":
                d.type = DIRTYPE
                # Directories have size 0
                d.size = 0
            else:
                d.type = REGTYPE
            
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