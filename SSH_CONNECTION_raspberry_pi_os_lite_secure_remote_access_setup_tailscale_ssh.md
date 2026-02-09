# Raspberry Pi OS Lite – Secure Remote Access Setup

This document describes how to set up a **headless Raspberry Pi (32-bit Raspberry Pi OS Lite)** for **secure remote access over different networks** using **Tailscale and SSH**.

The setup assumes:
- No GUI
- No public IP / no port forwarding
- Raspberry Pi is on a company or restricted network
- Client machine is Windows (but works similarly on Linux/macOS)

---

## 1. Initial System Setup

### 1.1 Enable SSH
```bash
sudo systemctl enable ssh
sudo systemctl start ssh
```

Verify:
```bash
ss -tlnp | grep :22
```

---

### 1.2 Set Timezone and Enable NTP

Correct system time is required for TLS and Tailscale.

```bash
sudo timedatectl set-timezone Europe/Ljubljana
sudo timedatectl set-ntp true
```

Verify:
```bash
timedatectl
```

---

### 1.3 Update System
```bash
sudo apt update
sudo apt upgrade -y
sudo reboot
```

---

## 2. Install and Configure Tailscale

### 2.1 Install Tailscale
```bash
curl -fsSL https://tailscale.com/install.sh | sh
```

Verify:
```bash
tailscale version
```

---

### 2.2 Authenticate Device
```bash
sudo tailscale up
```

- Open the provided login URL on your computer
- Log in with your Tailscale account
- Approve the Raspberry Pi

Verify connection:
```bash
tailscale status
```

---

### 2.3 Ensure Tailscale Starts on Boot
```bash
systemctl status tailscaled
sudo systemctl enable tailscaled
```

---

## 3. Secure SSH Configuration

### 3.1 Disable Password Authentication and Root Login

Edit SSH configuration:
```bash
sudo nano /etc/ssh/sshd_config
```

Ensure the following lines exist:
```text
PasswordAuthentication no
PermitRootLogin no
```

---

### 3.2 Validate SSH Configuration
```bash
sudo sshd -T | grep -E "passwordauthentication|permitrootlogin"
```

Expected output:
```text
passwordauthentication no
permitrootlogin no
```

---

### 3.3 Restart SSH
```bash
sudo systemctl restart ssh
```

Keep your existing SSH session open until reconnection is confirmed.

---

## 4. (Optional) Enable Tailscale SSH

This allows SSH access using Tailscale identity instead of SSH keys.

```bash
sudo tailscale up --ssh
```

Then connect from client:
```bash
ssh pi@raspberrypi
```

---

## 5. Windows Client Setup

### 5.1 Install Tailscale on Windows
- Download from https://tailscale.com/download
- Log in using the **same account** as the Raspberry Pi

Verify:
```powershell
tailscale status
```

---

### 5.2 Connect via SSH (Windows 10/11)

Windows includes OpenSSH by default.

```powershell
ssh pi@raspberrypi
```

Or using Tailscale IP:
```powershell
ssh pi@100.x.y.z
```

---

## 6. Final Result

- Secure SSH access across networks
- No port forwarding
- No public IP exposure
- Survives reboots
- Suitable for company and academic networks

---

## 7. Common Troubleshooting

- Check outbound connectivity:
```bash
ping 8.8.8.8
```

- Check Tailscale DNS:
```powershell
tailscale ping raspberrypi
```

- If hostname fails, use Tailscale IP

---