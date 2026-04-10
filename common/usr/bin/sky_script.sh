#!/usr/bin/env bash
set -euo pipefail
 
PACKAGES=(
  cpufrequtils
  samba
  iotop-c
  docker.io
  fio
  tree
  acl
  repo
  ripgrep
  openjdk-8-jre-headless
)
 
CPUFREQ_FILE="/etc/default/cpufrequtils"
SYSCTL_FILE="/etc/sysctl.d/99-omci-customize.conf"
GRUB_FILE="/etc/default/grub"
SSH_CONFIG_FILE="/etc/ssh/ssh_config"
SMB_CONF_FILE="/etc/samba/smb.conf"
HUDSON_SERVICE_FILE="/etc/systemd/system/hudson-slave.service"
DOCKER_CERT_DIR="/etc/docker/certs.d/10.118.96.1"
DOCKER_CERT_FILE="${DOCKER_CERT_DIR}/ca.crt"
SYSTEM_CA_FILE="/usr/local/share/ca-certificates/harbor-10.118.96.1.crt"
GRUB_ARGS='zswap.enabled=1 zswap.compressor=zstd zswap.max_pool_percent=15 mitigations=off'
 
DONE_ITEMS=()
SKIPPED_ITEMS=()
RUN_HUDSON="false"
 
add_done() {
  DONE_ITEMS+=("$1")
}
 
add_skipped() {
  SKIPPED_ITEMS+=("$1")
}
 
show_intro() {
  cat <<'MSG_EOF'
This script will:
  - install required packages
  - write sysctl settings
  - configure cpufreq governor
  - add /etc/hosts entry
  - add SSH client settings
  - add Samba global settings
  - install Docker registry certificate
  - update GRUB kernel parameters
  - optionally create and enable hudson-slave.service
 
Hudson service requires:
  - user 'hudson' already exists
  - /home/hudson/slave.jar already exists
 
Input options:
  Y : run all steps
  S : skip hudson service only
  other : abort
MSG_EOF
}
 
prompt_user_choice() {
  local answer
 
  read -r -p "Enter your choice: " answer
 
  case "${answer}" in
    [Yy]) RUN_HUDSON="true" ;;
    [Ss]) RUN_HUDSON="false" ;;
    *)
      echo "Aborted."
      exit 0
      ;;
  esac
}
 
install_packages() {
  echo "Installing packages..."
  sudo apt update
  sudo apt -y install "${PACKAGES[@]}"
  add_done "Installed packages"
}
 
write_sysctl_settings() {
  echo "Writing consolidated sysctl settings..."
  sudo tee "${SYSCTL_FILE}" >/dev/null <<'SYSCTL_EOF'
# Custom system tuning
kernel.apparmor_restrict_unprivileged_userns = 0
kernel.task_delayacct = 1
vm.page-cluster = 0
vm.swappiness = 100
fs.inotify.max_user_watches = 524288
SYSCTL_EOF
  add_done "Wrote ${SYSCTL_FILE}"
}
 
configure_cpu_governor() {
  echo "Configuring CPU governor..."
  sudo tee "${CPUFREQ_FILE}" >/dev/null <<'CPUFREQ_EOF'
GOVERNOR="performance"
CPUFREQ_EOF
  add_done "Wrote ${CPUFREQ_FILE}"
}
 
add_hosts_entry() {
  echo "Adding hosts entry..."
  if ! grep -qE '^[[:space:]]*10\.118\.3\.208[[:space:]]+sw6-builder([[:space:]]|$)' /etc/hosts; then
    echo '10.118.3.208 sw6-builder' | sudo tee -a /etc/hosts >/dev/null
  fi
  add_done "Ensured /etc/hosts contains '10.118.3.208 sw6-builder'"
}
 
add_ssh_client_configuration() {
  echo "Adding SSH client configuration..."
  if ! sudo grep -q '^# BEGIN OMCI CUSTOM SSH CONFIG$' "${SSH_CONFIG_FILE}"; then
    sudo tee -a "${SSH_CONFIG_FILE}" >/dev/null <<'SSH_EOF'
 
# BEGIN OMCI CUSTOM SSH CONFIG
Host sw6-builder.arcadyan.com.tw
    HostKeyAlgorithms +ssh-rsa
    PubkeyAcceptedKeyTypes +ssh-rsa
    KexAlgorithms +diffie-hellman-group14-sha1
# END OMCI CUSTOM SSH CONFIG
SSH_EOF
  fi
  add_done "Ensured ${SSH_CONFIG_FILE} contains OMCI SSH settings"
}
 
configure_samba_global_settings() {
  local tmp
 
  echo "Adding Samba global configuration..."
 
  if [ ! -f "${SMB_CONF_FILE}" ]; then
    echo "Error: ${SMB_CONF_FILE} does not exist."
    exit 1
  fi
 
  tmp="$(mktemp)"
 
  if ! awk '
    function is_section(line, s) {
      s = line
      sub(/^[[:space:]]+/, "", s)
      sub(/[[:space:]]+$/, "", s)
      return (s ~ /^\[[^]]+\]$/)
    }
 
    function trimmed(line, s) {
      s = line
      sub(/^[[:space:]]+/, "", s)
      sub(/[[:space:]]+$/, "", s)
      return s
    }
 
    function is_blank(line) {
      return (line ~ /^[[:space:]]*$/)
    }
 
    function is_managed_begin(line) {
      return (trimmed(line) == "# BEGIN OMCI CUSTOM SAMBA GLOBAL")
    }
 
    function is_managed_end(line) {
      return (trimmed(line) == "# END OMCI CUSTOM SAMBA GLOBAL")
    }
 
    function is_target_setting(line, s, key) {
      s = line
      sub(/^[[:space:]]+/, "", s)
 
      if (s ~ /^[#;]/) {
        return 0
      }
 
      if (s !~ /=/) {
        return 0
      }
 
      key = s
      sub(/[[:space:]]*=.*/, "", key)
      key = tolower(key)
 
      return key == "follow symlinks" || \
             key == "wide links" || \
             key == "unix extensions"
    }
 
    {
      lines[++n] = $0
    }
 
    END {
      global_start = 0
      global_end = 0
 
      for (i = 1; i <= n; i++) {
        if (is_section(lines[i]) && tolower(trimmed(lines[i])) == "[global]") {
          global_start = i
          break
        }
      }
 
      if (global_start > 0) {
        global_end = n
        for (i = global_start + 1; i <= n; i++) {
          if (is_section(lines[i])) {
            global_end = i - 1
            break
          }
        }
 
        for (i = global_start + 1; i <= global_end; i++) {
          keep[i] = 1
        }
 
        for (i = global_start + 1; i <= global_end; i++) {
          if (!keep[i]) {
            continue
          }
 
          if (is_managed_begin(lines[i])) {
            block_start = i
            block_end = 0
 
            for (j = i + 1; j <= global_end; j++) {
              if (is_managed_end(lines[j])) {
                block_end = j
                break
              }
            }
 
            if (block_end > 0) {
              remove_from = block_start
              remove_to = block_end
 
              if (remove_from > global_start + 1 && is_blank(lines[remove_from - 1])) {
                remove_from--
              }
              if (remove_to < global_end && is_blank(lines[remove_to + 1])) {
                remove_to++
              }
 
              for (j = remove_from; j <= remove_to; j++) {
                keep[j] = 0
              }
 
              i = block_end
            }
          }
        }
 
        for (i = global_start + 1; i <= global_end; i++) {
          if (keep[i] && is_target_setting(lines[i])) {
            keep[i] = 0
          }
        }
 
        out_n = 0
 
        for (i = 1; i <= global_start; i++) {
          out[++out_n] = lines[i]
        }
 
        body_n = 0
        for (i = global_start + 1; i <= global_end; i++) {
          if (keep[i]) {
            body[++body_n] = lines[i]
          }
        }
 
        while (body_n > 0 && is_blank(body[body_n])) {
          body_n--
        }
 
        for (i = 1; i <= body_n; i++) {
          out[++out_n] = body[i]
        }
 
        if (out_n == 0 || !is_blank(out[out_n])) {
          out[++out_n] = ""
        }
 
        out[++out_n] = "# BEGIN OMCI CUSTOM SAMBA GLOBAL"
        out[++out_n] = "   follow symlinks = yes"
        out[++out_n] = "   wide links = yes"
        out[++out_n] = "   unix extensions = no"
        out[++out_n] = "# END OMCI CUSTOM SAMBA GLOBAL"
        out[++out_n] = ""
 
        for (i = global_end + 1; i <= n; i++) {
          out[++out_n] = lines[i]
        }
      } else {
        out_n = 0
        out[++out_n] = "[global]"
        out[++out_n] = ""
        out[++out_n] = "# BEGIN OMCI CUSTOM SAMBA GLOBAL"
        out[++out_n] = "   follow symlinks = yes"
        out[++out_n] = "   wide links = yes"
        out[++out_n] = "   unix extensions = no"
        out[++out_n] = "# END OMCI CUSTOM SAMBA GLOBAL"
        out[++out_n] = ""
 
        for (i = 1; i <= n; i++) {
          out[++out_n] = lines[i]
        }
      }
 
      for (i = 1; i <= out_n; i++) {
        print out[i]
      }
    }
  ' "${SMB_CONF_FILE}" > "${tmp}"; then
    rm -f "${tmp}"
    echo "Error: failed to process ${SMB_CONF_FILE}."
    exit 1
  fi
 
  if ! cmp -s "${tmp}" "${SMB_CONF_FILE}"; then
    if ! sudo tee "${SMB_CONF_FILE}" >/dev/null < "${tmp}"; then
      rm -f "${tmp}"
      echo "Error: failed to write ${SMB_CONF_FILE}."
      exit 1
    fi
  fi
 
  rm -f "${tmp}"
  add_done "Ensured ${SMB_CONF_FILE} contains OMCI Samba global settings"
}
 
create_hudson_service() {
  echo "Creating hudson slave service..."
  sudo tee "${HUDSON_SERVICE_FILE}" >/dev/null <<'SERVICE_EOF'
[Unit]
Description=hudson slave Service
After=network.target
 
[Service]
Type=simple
User=hudson
ExecStart=/usr/bin/java -jar /home/hudson/slave.jar -jnlpUrl http://sw6-builder:8080/slaveJnlp?name=builder-omci6
Restart=on-abort
 
[Install]
WantedBy=multi-user.target
SERVICE_EOF
 
  sudo systemctl enable hudson-slave.service
  add_done "Created and enabled hudson-slave.service"
}
 
handle_hudson_service() {
  if [[ "${RUN_HUDSON}" == "true" ]]; then
    create_hudson_service
  else
    add_skipped "Skipped hudson-slave.service creation and enablement"
  fi
}
 
install_docker_registry_certificate() {
  echo "Installing Docker registry certificate..."
  sudo mkdir -p "${DOCKER_CERT_DIR}"
 
  echo -n | openssl s_client -showcerts -connect 10.118.96.1:443 2>/dev/null \
    | sed -ne '/-BEGIN CERTIFICATE-/,/-END CERTIFICATE-/p' \
    | sudo tee "${DOCKER_CERT_FILE}" >/dev/null
 
  if [ ! -s "${DOCKER_CERT_FILE}" ]; then
    echo "Failed to fetch Docker registry certificate."
    exit 1
  fi
 
  sudo cp "${DOCKER_CERT_FILE}" "${SYSTEM_CA_FILE}"
  sudo update-ca-certificates
  add_done "Installed Docker registry CA certificate"
}
 
update_grub_kernel_parameters() {
  echo "Updating GRUB kernel parameters..."
  if grep -q '^GRUB_CMDLINE_LINUX_DEFAULT=' "${GRUB_FILE}"; then
    sudo sed -i \
      "s|^GRUB_CMDLINE_LINUX_DEFAULT=.*|GRUB_CMDLINE_LINUX_DEFAULT=\"${GRUB_ARGS}\"|" \
      "${GRUB_FILE}"
  else
    echo "GRUB_CMDLINE_LINUX_DEFAULT=\"${GRUB_ARGS}\"" | sudo tee -a "${GRUB_FILE}" >/dev/null
  fi
 
  sudo update-grub
  add_done "Updated ${GRUB_FILE} and ran update-grub"
}
 
print_summary() {
  cat <<'SUMMARY_EOF'
 
================ Summary ================
SUMMARY_EOF
 
  echo "Completed:"
  for item in "${DONE_ITEMS[@]}"; do
    echo "  - ${item}"
  done
 
  if [ "${#SKIPPED_ITEMS[@]}" -gt 0 ]; then
    echo
    echo "Skipped:"
    for item in "${SKIPPED_ITEMS[@]}"; do
      echo "  - ${item}"
    done
  fi
 
  echo
  echo "Done. Please reboot now."
}
 
show_intro
prompt_user_choice
install_packages
write_sysctl_settings
configure_cpu_governor
add_hosts_entry
add_ssh_client_configuration
configure_samba_global_settings
handle_hudson_service
install_docker_registry_certificate
update_grub_kernel_parameters
print_summary
