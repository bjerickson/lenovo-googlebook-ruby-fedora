# cros_ec_ishtp from Linux v7.2.15 (drivers/platform/chrome/), unmodified, with its private
# cros_ec.h, for kernels built without CONFIG_CROS_EC_ISHTP (Fedora). It connects the
# Integrated Sensor Hub's ChromeOS EC to cros_ec, so cros-ec-sensorhub and cros-ec-light
# expose the ambient light sensor.
obj-m := cros_ec_ishtp.o

KVER ?= $(shell uname -r)
KDIR ?= /lib/modules/$(KVER)/build

all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) modules
clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean
