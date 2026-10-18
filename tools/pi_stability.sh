#!/bin/bash
# 树莓派稳定性加固：① 真正开持久日志 ② 装机载黑匣子
# 需要 sudo 运行
set -u

echo "======================================================"
echo " 1. 修持久日志（这是上次丢证据的根因）"
echo "======================================================"
MID=$(cat /etc/machine-id)
echo "  machine-id: $MID"
if [ -d "/var/log/journal/$MID" ]; then
  echo "  /var/log/journal/$MID 已存在"
else
  mkdir -p "/var/log/journal/$MID"
  echo "  ✅ 已创建 /var/log/journal/$MID（之前缺的就是这个目录）"
fi
chown root:systemd-journal "/var/log/journal/$MID"
chmod 2755 "/var/log/journal/$MID"
systemd-tmpfiles --create --prefix /var/log/journal 2>/dev/null || true

echo "  --- 改动前的 journald.conf ---"
grep -vE '^\s*#|^\s*$' /etc/systemd/journald.conf 2>/dev/null | sed 's/^/    /'

if grep -qE '^\s*Storage=' /etc/systemd/journald.conf 2>/dev/null; then
  sed -i 's/^\s*Storage=.*/Storage=persistent/' /etc/systemd/journald.conf
else
  sed -i 's/^\[Journal\]/[Journal]\nStorage=persistent\nSystemMaxUse=200M/' /etc/systemd/journald.conf
fi

echo "  --- 改动后的 journald.conf ---"
grep -vE '^\s*#|^\s*$' /etc/systemd/journald.conf 2>/dev/null | sed 's/^/    /'

systemctl restart systemd-journald
sleep 2
echo "  --- 现在 /var/log/journal 内容 ---"
ls -la /var/log/journal | sed 's/^/    /'
echo "  --- 当前 boot 能否读 ---"
journalctl -b 0 -n 1 --no-pager 2>&1 | head -2 | sed 's/^/    /'

echo ""
echo "======================================================"
echo " 2. 装黑匣子（每 10 秒把健康数据写盘 + sync）"
echo "======================================================"
mkdir -p /var/log/pimon

cat > /usr/local/sbin/pimon.sh <<'EOF'
#!/bin/bash
# 黑匣子：每 10 秒记一行并立即 sync —— 硬断也有最后几秒的数据
LOG=/var/log/pimon/pimon-$(date +%Y%m%d).csv
if [ ! -f "$LOG" ]; then
  echo "ts,uptime_s,throttled,temp_c,core_v,load1,mem_used_mb,wlan_dbm" > "$LOG"
fi
while true; do
  T=$(vcgencmd get_throttled 2>/dev/null | cut -d= -f2)
  TEMP=$(vcgencmd measure_temp 2>/dev/null | tr -dc '0-9.')
  VOLT=$(vcgencmd measure_volts 2>/dev/null | cut -d= -f2 | tr -dc '0-9.')
  UP=$(cut -d' ' -f1 /proc/uptime | cut -d. -f1)
  L1=$(cut -d' ' -f1 /proc/loadavg)
  MEM=$(free -m | awk '/^Mem:/{print $3}')
  DBM=$(/sbin/iw dev wlan0 link 2>/dev/null | awk '/signal:/{print $2}')
  echo "$(date -Iseconds),$UP,$T,$TEMP,$VOLT,$L1,$MEM,$DBM" >> "$LOG"
  sync
  sleep 10
done
EOF
chmod +x /usr/local/sbin/pimon.sh

cat > /etc/systemd/system/pimon.service <<'EOF'
[Unit]
Description=Pi health flight recorder (records the last seconds before a crash)
After=multi-user.target

[Service]
Type=simple
ExecStart=/usr/local/sbin/pimon.sh
Restart=always
RestartSec=2
Nice=-5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now pimon.service
sleep 14
echo "  服务状态: active=$(systemctl is-active pimon.service)  enabled=$(systemctl is-enabled pimon.service)"
echo "  --- 最近 3 行 ---"
tail -3 "/var/log/pimon/pimon-$(date +%Y%m%d).csv" 2>/dev/null | sed 's/^/    /'

echo ""
echo "======================================================"
echo " 3. 黑匣子只保留 7 天，防止写满 SD"
echo "======================================================"
cat > /etc/systemd/system/pimon-prune.service <<'EOF'
[Unit]
Description=Prune pi flight recorder files older than 7 days

[Service]
Type=oneshot
ExecStart=/usr/bin/find /var/log/pimon -name 'pimon-*.csv' -mtime +7 -delete
EOF
cat > /etc/systemd/system/pimon-prune.timer <<'EOF'
[Unit]
Description=Daily prune of pi flight recorder

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now pimon-prune.timer
echo "  timer: active=$(systemctl is-active pimon-prune.timer)  enabled=$(systemctl is-enabled pimon-prune.timer)"

echo ""
echo "======================================================"
echo " 4. 重启（验证持久日志真的生效）"
echo "======================================================"
echo "  重启后我会自己 SSH 进来查「是不是能看到两次启动」"
sync
sleep 2
systemctl reboot
