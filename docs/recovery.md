# Recovery

## The firmware is never modified

Nothing in this project writes the firmware. Whatever happens to the internal disk, the developer screen still offers **Boot from external drive**, so the installer USB is always a way back in.

## The installer stopped with an error

The boot partitions are written last, only after Fedora is installed and the boot set has passed the Android loader check. Fix the cause shown and run `install_fedora_ruby.py` again from the top. It rewrites the partition table and reformats, so it does not matter how far the previous run got.

## Fedora does not boot after a kernel update

Boot the installer USB and roll slot A back to the previous kernel:

```sh
cryptsetup open /dev/nvme0n1p1 fedora-root
mount -o subvol=@ /dev/mapper/fedora-root /mnt
arch-chroot /mnt python3 /opt/lapis-kit/tools/kernel_update_fedora.py rollback
umount /mnt; cryptsetup close fedora-root
```

## Getting into the installed system from the USB

The same `cryptsetup open` and `mount` give you the root at `/mnt`; add `mount -o subvol=@home /dev/mapper/fedora-root /mnt/home` for home. `arch-chroot /mnt` runs commands inside it (dnf works there with network).

## Going back to Googlebook OS

Use Google's [Device Recovery Utility](https://chromewebstore.google.com/detail/device-recovery-utility/pocpnlppkickgojjlmhdmidojbmbodfm) and the [Googlebook recovery instructions](https://support.google.com/googlebook/answer/17452429) from any computer with Chrome, with a separate USB drive of 32 GB or more. Select **Googlebook**, manufacturer **Lenovo**, product **Lenovo Googlebook 15**. The recovery image restores the whole disk, including the partitions this installer removed. Relock the bootloader afterwards if you want verified boot back. A factory restore has not been tested on a Fedora-installed laptop.
