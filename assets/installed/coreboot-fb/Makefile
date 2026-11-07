# Google coreboot firmware drivers, unmodified from Linux v7.3.3
# (drivers/firmware/google/), for kernels built without CONFIG_GOOGLE_FIRMWARE
# such as Fedora's. Without CONFIG_DRM_COREBOOTDRM, framebuffer-coreboot
# registers a simple-framebuffer device that the built-in simpledrm drives,
# so the LUKS prompt is visible before Xe loads.
obj-m := coreboot_table.o framebuffer-coreboot.o vpd-sysfs.o
vpd-sysfs-y := vpd.o vpd_decode.o

KVER ?= $(shell uname -r)
KDIR ?= /lib/modules/$(KVER)/build

all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) modules
clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean
