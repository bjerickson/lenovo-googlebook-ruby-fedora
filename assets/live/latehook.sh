run_latehook() {
    mkdir -p /new_root/opt/ruby-fedora /new_root/etc/modprobe.d /new_root/etc/modules-load.d
    cp -a /lapis-kit/. /new_root/opt/ruby-fedora/ || return 1
    # Console on the coreboot framebuffer; Xe and SOF stay unloaded in the live session.
    printf 'coreboot_table\nframebuffer_coreboot\ncorebootdrm\n' > /new_root/etc/modules-load.d/ruby-framebuffer.conf
    printf 'blacklist xe\nblacklist snd_sof_pci_intel_ptl\noptions xe gsc_firmware_path= enable_panel_replay=0 enable_psr=0 enable_fbc=0 enable_dsb=0 enable_sagv=0 enable_dc=0\n' > /new_root/etc/modprobe.d/ruby-live.conf
    # This image never ships a shared SSH key, Wi-Fi password or machine ID.
    # Remote access remains off unless its owner explicitly configures it.
    ln -sf /dev/null /new_root/etc/systemd/system/sshd.service
    for unit in start quit quit-wait read-write switch-root; do
        ln -sf /dev/null "/new_root/etc/systemd/system/plymouth-$unit.service"
    done
    cat > /new_root/usr/local/bin/omarchy-iso-install <<'EOF'
#!/bin/sh
echo 'This USB installs Fedora, not Omarchy:'
echo '  cd /opt/ruby-fedora && python3 tools/install_fedora_ruby.py --help'
exit 1
EOF
    chmod 755 /new_root/usr/local/bin/omarchy-iso-install
    cat > /new_root/root/.automated_script.sh <<'EOF'
#!/bin/sh
printf '\nFedora installer for the Lenovo Googlebook 15 (Ruby). The internal disk is untouched.\n'
printf 'Connect Wi-Fi with iwctl, then:\n'
printf '  cd /opt/ruby-fedora\n'
printf '  python3 tools/install_fedora_ruby.py --user YOU --name "Your Name" --timezone Area/City --desktop kde\n'
printf '  (--desktop kde, gnome or none; --dry-run to preview; --help for all options)\n'
printf 'Guide: docs/install.md\n\n'
EOF
    chmod 755 /new_root/root/.automated_script.sh
}
