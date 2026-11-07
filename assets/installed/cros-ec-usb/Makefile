# SPDX-License-Identifier: GPL-2.0
# Kbuild for the out-of-tree cros_ec_usb module. DKMS runs
#   make -C /usr/lib/modules/$kernelver/build M=$PWD [LLVM=1]
# itself; the targets below are for a manual build of a patched copy.
ifneq ($(KERNELRELEASE),)
obj-m := cros_ec_usb.o
else
KVER ?= $(shell uname -r)
KDIR ?= /usr/lib/modules/$(KVER)/build
# A clang-built kernel needs LLVM=1 for its modules; Fedora's gcc-built kernel does not.
LLVM_ARG := $(if $(shell grep -s '^CONFIG_CC_IS_CLANG=y' $(KDIR)/.config),LLVM=1)

modules:
	$(MAKE) -C $(KDIR) M=$(CURDIR) $(LLVM_ARG) modules

clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) $(LLVM_ARG) clean
endif
