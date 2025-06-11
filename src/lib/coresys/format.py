from rp2 import Flash
from os import umount, mount, VfsLfs2
flash=Flash()
umount('/')
VfsLfs2.mkfs(flash)
mount(flash, '/')