#!/bin/sh
# Fingerprint reader on Fedora (Ruby): cros_ec_usb via DKMS, then Fedora's libfprint
# rebuilt with the crfpmoc driver and Ruby fixes, then fprintd. Run with sudo.
#
# The RPM is Fedora's libfprint 1.94.100 spec plus assets/packages/libfprint-crfpmoc/
# 000*.patch (release 100.crfpmoc4). dnf is told not to replace it with Fedora's
# unpatched libfprint; when Fedora moves to a newer libfprint, rebuild this.
set -eu
here=$(dirname "$(readlink -f "$0")")
pkg=$here/../assets/packages/libfprint-crfpmoc
tarball=libfprint-v1.94.100.tar.gz
tarball_url=https://gitlab.freedesktop.org/libfprint/libfprint/-/archive/v1.94.100/$tarball
# Identical to the tarball in Fedora's libfprint-1.94.100-1.fc45.src.rpm.
tarball_sha256=edc90e02f330a7595ceaf37f2c6ec32ed43541347fe936d3273b0bb2524fd19c
[ "$(id -u)" = 0 ] || { echo 'Run with sudo' >&2; exit 1; }
[ "$(cat /sys/class/dmi/id/product_name)" = Ruby ] || { echo 'Not a Ruby board' >&2; exit 1; }

echo '==> Kernel driver (cros_ec_usb, DKMS)'
dnf install -y dkms "kernel-devel-$(uname -r)"
sh "$here/install_fingerprint_driver.sh" --autoload

echo '==> Building libfprint with crfpmoc'
dnf install -y rpm-build fprintd
work=$(mktemp -d -p /var/tmp)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/SOURCES" "$work/SPECS"
cp "$pkg"/000*.patch "$work/SOURCES/"
cp "$pkg/libfprint.spec" "$work/SPECS/"
curl -fsSL -o "$work/SOURCES/$tarball" "$tarball_url"
echo "$tarball_sha256  $work/SOURCES/$tarball" | sha256sum -c -
dnf builddep -y "$work/SPECS/libfprint.spec"
rpmbuild --define "_topdir $work" -bb "$work/SPECS/libfprint.spec"
rpm=$(ls "$work"/RPMS/x86_64/libfprint-1.94.100-*.crfpmoc*.x86_64.rpm | grep -v -e devel -e tests -e debug)
dnf install -y "$rpm"
rpm -q libfprint fprintd

# Keep Fedora's unpatched libfprint from replacing this build.
conf=/etc/dnf/dnf.conf
if ! grep -q '^excludepkgs=.*libfprint' "$conf"; then
    if grep -q '^excludepkgs=' "$conf"; then
        sed -i 's/^excludepkgs=\(.*\)/excludepkgs=\1,libfprint/' "$conf"
    else
        sed -i '/^\[main\]/a excludepkgs=libfprint' "$conf"
    fi
fi
echo "dnf will not update libfprint ($conf); rebuild with this script when Fedora ships a newer one."

echo '==> Loading the driver'
modprobe cros_ec_usb || echo 'modprobe cros_ec_usb failed; see dmesg'
ls -l /dev/cros_fp 2>/dev/null || modprobe -a cros_ec_dev cros_ec_chardev || true
# fprintd enumerates devices when it starts; make it rediscover.
systemctl stop fprintd.service 2>/dev/null || true
cat <<'EOF'

Next, as your user (not root):
  fprintd-enroll        # right index finger by default; -f <finger> for another
  fprintd-verify
To use it for sudo, login and the KDE lock screen:
  sudo authselect enable-feature with-fingerprint
EOF
