#!/bin/bash
# 把树莓派长期钉到 2.4G 那个 03CityKey BSSID（ch1 / 2412 MHz，无 DFS）
#
# 与 pi_pin_24g.sh 的区别：这个版本【不装兜底定时器】。
#   理由：切换机制已验证（几秒完成、IP 不变、网关可达），
#   而 200 秒定时器会把成功的结果也一起回滚掉。
#   安全由两点保证：① 原配置一字不改，失败时立即切回；② 随时可手动回滚。
#
# 回滚方法：sudo bash /usr/local/sbin/pin24-revert.sh
set -u

ORIG="netplan-wlan0-03CityKey"
NEW="03CityKey-24g"
BSSID="34:DB:9C:DA:C7:03"      # ch1, 2412 MHz
REVERT=/usr/local/sbin/pin24-revert.sh

echo "=============================================================="
echo " 0. 前置检查"
echo "=============================================================="
if [ "$(id -u)" != "0" ]; then echo "❌ 需要 root（用 sudo 跑）"; exit 1; fi
if ! nmcli -t -f NAME connection show | grep -qx "$ORIG"; then
  echo "❌ 找不到原连接 $ORIG，中止（不动任何东西）"; exit 1
fi
echo "  ✅ 原连接存在: $ORIG"
nmcli -t -f NAME,UUID,DEVICE connection show > /root/pin24-before.txt 2>/dev/null
echo "  ✅ 原状态已存 /root/pin24-before.txt"
echo "  ✅ 本脚本不装定时器（失败会立即回滚）"

echo ""
echo "=============================================================="
echo " 1. 准备回滚脚本（保留给以后手动用）"
echo "=============================================================="
cat > "$REVERT" <<'EOS'
#!/bin/bash
logger -t pin24 "手动回滚：删除 03CityKey-24g，切回 netplan-wlan0-03CityKey"
nmcli connection delete 03CityKey-24g 2>/dev/null
nmcli connection up netplan-wlan0-03CityKey 2>/dev/null
EOS
chmod 755 "$REVERT"
echo "  ✅ 回滚脚本: $REVERT"

echo ""
echo "=============================================================="
echo " 2. 取出原配置的 SSID / 密码（不回显密码）"
echo "=============================================================="
SSID=$(nmcli -g 802-11-wireless.ssid connection show "$ORIG" 2>/dev/null)
PSK=$(nmcli -s -g 802-11-wireless-security.psk connection show "$ORIG" 2>/dev/null)
if [ -z "$SSID" ]; then echo "❌ 取不到 SSID，中止"; exit 1; fi
echo "  SSID = $SSID"
echo "  目标 BSSID = $BSSID   （ch1 / 2412 MHz / 无 DFS）"
echo "  密码已取到: $([ -n "$PSK" ] && echo 是 || echo 否)"

echo ""
echo "=============================================================="
echo " 3. 新建（或重建）钉住 BSSID 的连接"
echo "=============================================================="
nmcli connection delete "$NEW" >/dev/null 2>&1
nmcli connection add type wifi ifname wlan0 con-name "$NEW" ssid "$SSID" \
  -- 802-11-wireless.bssid "$BSSID" \
     802-11-wireless-security.key-mgmt wpa-psk \
     802-11-wireless-security.psk "$PSK" \
     ipv4.method auto \
     ipv6.method auto \
     connection.autoconnect yes \
     connection.autoconnect-priority 100 \
     connection.autoconnect-retries 0 >/dev/null 2>&1
if nmcli -t -f NAME connection show | grep -qx "$NEW"; then
  echo "  ✅ 已创建 $NEW"
  echo "     钉住的 BSSID : $(nmcli -g 802-11-wireless.bssid connection show "$NEW" 2>/dev/null)"
  echo "     自动连接优先级: $(nmcli -g connection.autoconnect-priority connection show "$NEW" 2>/dev/null)（原配置是 0，所以本配置优先）"
else
  echo "  ❌ 创建失败，中止（原配置未改动）"
  exit 1
fi

echo ""
echo "=============================================================="
echo " 4. 切过去（这一步会短暂断网）"
echo "=============================================================="
nmcli connection up "$NEW" 2>&1 | sed 's/^/    /'
sleep 8

echo ""
echo "=============================================================="
echo " 5. 验证"
echo "=============================================================="
LINK=$(iw dev wlan0 link 2>/dev/null)
echo "  --- iw dev wlan0 link ---"
echo "$LINK" | sed 's/^/    /'
FREQ=$(echo "$LINK" | awk '/freq:/{print $2}')
FREQ_INT=${FREQ%%.*}
CONNECTED_BSSID=$(echo "$LINK" | awk '/Connected to/{print $3}')
GW=$(ip route | awk '/default/{print $3; exit}')
IPADDR=$(ip -4 addr show wlan0 | awk '/inet /{print $2}')

echo ""
echo "  连上的 BSSID : ${CONNECTED_BSSID:-?}"
echo "  频率         : ${FREQ:-?} MHz"
echo "  IP           : ${IPADDR:-?}"
echo "  网关         : ${GW:-?}"

GWOK=no
if [ -n "$GW" ]; then
  if ping -c 2 -W 2 "$GW" >/dev/null 2>&1; then GWOK=yes; fi
fi
echo "  网关 ping    : $([ "$GWOK" = yes ] && echo '✅ 通' || echo '❌ 不通')"

echo ""
echo "  判定: 频率整数位=${FREQ_INT:-?}（目标 2412）  网关可达=$GWOK"
if [ "$FREQ_INT" = "2412" ] && [ "$GWOK" = yes ]; then
  echo ""
  echo "  🎉 成功：已钉在 2412 MHz（ch1 / 2.4G / 无 DFS），网关可达"
  echo "     本配置已设为开机自动连接（优先级 100），重启后仍然生效"
  echo "     想立刻改回：sudo bash $REVERT"
  echo "PIN24_RESULT=OK"
else
  echo ""
  echo "  ❌ 失败（预期 2412 MHz + 网关可达，实际 ${FREQ_INT:-未知} MHz / 网关 $GWOK）"
  echo "     立即回滚"
  bash "$REVERT"
  echo "     已回滚，原配置生效"
  echo "PIN24_RESULT=FAIL"
fi
