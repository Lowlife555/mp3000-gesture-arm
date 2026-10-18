#!/bin/bash
# 修证据链 + 装 Wi-Fi 看门狗
# 需要 sudo
set -u

echo "=============================================================="
echo " ① 真正修好持久日志（绕过树莓派官方的 volatile drop-in）"
echo "=============================================================="
echo "  --- 改动前：谁在把日志按在内存里 ---"
for f in /usr/lib/systemd/journald.conf.d/*.conf /etc/systemd/journald.conf.d/*.conf; do
  [ -f "$f" ] || continue
  echo "    $f"
  grep -vE '^\s*#|^\s*$' "$f" | sed 's/^/      /'
done

MID=$(cat /etc/machine-id)
D="/var/log/journal/$MID"
echo ""
echo "  machine-id : $MID"
echo "  目标目录   : $D"

mkdir -p "$D"
chown root:systemd-journal "$D"
chmod 2755 "$D"
mkdir -p /var/log/journal
chown root:systemd-journal /var/log/journal
chmod 2755 /var/log/journal
setfacl -m "u:systemd-journal:rwx,d:u:systemd-journal:rwx" "$D" 2>/dev/null || true

# 关键：/etc 的 drop-in 优先级高于 /usr/lib，用 90- 盖过 40-
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/90-mp3000-persistent.conf <<'EOF'
# 覆盖树莓派官方的 /usr/lib/systemd/journald.conf.d/40-rpi-volatile-storage.conf
# /etc 下的 drop-in 优先于 /usr/lib，所以这行会生效
[Journal]
Storage=persistent
SystemMaxUse=200M
SystemMaxFileSize=50M
SyncIntervalSec=5s
EOF

echo "  --- 改动后 ---"
echo "    /etc/systemd/journald.conf.d/90-mp3000-persistent.conf"
grep -vE '^\s*#|^\s*$' /etc/systemd/journald.conf.d/90-mp3000-persistent.conf | sed 's/^/      /'

systemctl restart systemd-journald
sleep 3

echo ""
echo "  === 立刻验证（关键）==="
echo "  --- /var/log/journal/$MID 里有没有 .journal 文件 ---"
FOUND=0
while read -r f; do
  [ -z "$f" ] && continue
  echo "    ✅ $f  ($(stat -c%s "$f") 字节)"
  FOUND=1
done <<< "$(find "$D" -maxdepth 1 -name '*.journal' 2>/dev/null)"
if [ "$FOUND" -eq 0 ]; then
  echo "    ❌ 还是没有 .journal 文件 —— 说明覆盖仍未生效"
fi
echo "  --- /run/log/journal（如果还有文件，说明仍在使用内存版）---"
find /run/log/journal -name '*.journal' 2>/dev/null | while read -r f; do echo "    ⚠️ 仍在用内存: $f"; done
echo "  --- journald 实际生效配置 ---"
journalctl --disk-usage 2>&1 | sed 's/^/    /'

echo ""
echo "=============================================================="
echo " ② 装 Wi-Fi 看门狗（掉线自动重连，并记录全过程）"
echo "=============================================================="

cat > /usr/local/sbin/wifi-watchdog.sh <<'EOF'
#!/bin/bash
# Wi-Fi 看门狗：每 30 秒检查关联状态
# 连续失败 → 依次尝试 nmcli 重连 / 重启 NetworkManager / 重载 brcmfmac
LOG=/var/log/wifi-watch.log
LOGMAX=2000000      # 超过 2 MB 就轮转
fails=0
stage=0

log() { echo "$(date -Iseconds) $*" >> "$LOG"; }

[ -f "$LOG" ] || echo "=== wifi-watchdog 启动 $(date -Iseconds) ===" > "$LOG"

while true; do
  # 1. 接口存在吗
  if ! ip link show wlan0 >/dev/null 2>&1; then
    log "STAGE=IF_MISSING  wlan0 接口不存在"
  else
    STATE=$(/sbin/iw dev wlan0 link 2>/dev/null | head -1)
    SIG=$(/sbin/iw dev wlan0 link 2>/dev/null | awk '/signal:/{print $2}')
    FREQ=$(/sbin/iw dev wlan0 link 2>/dev/null | awk '/freq:/{print int($2)}')
    GW=$(ip route 2>/dev/null | awk '/default/{print $3; exit}')
    GWOK="no"
    if [ -n "$GW" ]; then
      if ping -c 1 -W 2 "$GW" >/dev/null 2>&1; then GWOK="yes"; fi
    fi
    if echo "$STATE" | grep -q "Connected to"; then
      log "OK      assoc=yes signal=${SIG:-?} freq=${FREQ:-?} gw=${GW:-?} gwping=$GWOK fails=$fails"
      fails=0
      stage=0
    else
      fails=$((fails+1))
      log "LOST    assoc=NO  freq=${FREQ:-?} gw=${GW:-?} gwping=$GWOK fails=$fails stage=$stage"

      # 连续 2 次（约 60 秒）才动手，避免误伤
      if [ "$fails" -ge 2 ]; then
        case "$stage" in
          0)
            log "ACTION  nmcli connection up"
            timeout 30 nmcli connection up netplan-wlan0-03CityKey >> "$LOG" 2>&1
            stage=1
            ;;
          1)
            log "ACTION  systemctl restart NetworkManager"
            timeout 40 systemctl restart NetworkManager >> "$LOG" 2>&1
            stage=2
            ;;
          2)
            log "ACTION  重载 brcmfmac 驱动（最后手段）"
            modprobe -r brcmfmac 2>>"$LOG"
            sleep 3
            modprobe brcmfmac 2>>"$LOG"
            sleep 8
            timeout 30 nmcli connection up netplan-wlan0-03CityKey >> "$LOG" 2>&1
            stage=3
            ;;
          *)
            log "ACTION  已用尽所有手段（stage=3），等待外部干预"
            ;;
        esac
      fi
    fi
  fi

  # 日志轮转
  if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG")" -gt "$LOGMAX" ]; then
    mv "$LOG" "$LOG.1"
    echo "=== 轮转 $(date -Iseconds) ===" > "$LOG"
  fi

  sleep 30
done
EOF
chmod +x /usr/local/sbin/wifi-watchdog.sh

cat > /etc/systemd/system/wifi-watchdog.service <<'EOF'
[Unit]
Description=Wi-Fi watchdog (auto-reconnect + evidence log)
After=network.target NetworkManager.service
Wants=NetworkManager.service

[Service]
Type=simple
ExecStart=/usr/local/sbin/wifi-watchdog.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now wifi-watchdog.service
sleep 6
echo "  服务: active=$(systemctl is-active wifi-watchdog.service)  enabled=$(systemctl is-enabled wifi-watchdog.service)"
echo "  --- 日志前几行 ---"
tail -5 /var/log/wifi-watch.log 2>/dev/null | sed 's/^/    /'

echo ""
echo "=============================================================="
echo " ③ 验证与汇总"
echo "=============================================================="
echo "  --- 持久日志 ---"
find "/var/log/journal/$(cat /etc/machine-id)" -maxdepth 1 -name '*.journal' 2>/dev/null | sed 's/^/    /' || echo "    （空）"
echo "  --- 服务总览 ---"
for s in wayvnc.service wayvnc-control.service novnc.service pimon.service wifi-watchdog.service; do
  printf "    %-26s active=%-8s enabled=%s\n" "$s" "$(systemctl is-active "$s" 2>/dev/null)" "$(systemctl is-enabled "$s" 2>/dev/null)"
done
export XDG_RUNTIME_DIR=/run/user/1000
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
printf "    %-26s active=%-8s enabled=%s\n" "demo.service(user)" "$(systemctl --user is-active demo.service 2>/dev/null)" "$(systemctl --user is-enabled demo.service 2>/dev/null)"

echo ""
echo "  --- Wi-Fi 现状 ---"
/sbin/iw dev wlan0 link 2>/dev/null | grep -E 'SSID|freq|signal' | sed 's/^/    /'

echo ""
echo "=============================================================="
echo " ⚠️ 现在【不要重启】。下次真的出问题时，这些日志会留在磁盘上。"
echo "=============================================================="
