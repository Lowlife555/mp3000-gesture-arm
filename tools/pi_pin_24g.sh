#!/bin/bash
# 把树莓派钉到 2.4G 那个 03CityKey BSSID（ch1 / 2412 MHz，无 DFS）
# 目的：A/B 实验 —— 如果掉线是 DFS 换信道 + BSSID 漫游引起的，钉住就当场解决
# 安全：不动原配置；新建独立 profile；带 200 秒自动回滚定时器；网关不通立刻回滚
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

echo ""
echo "=============================================================="
echo " 1. 装回滚脚本 + 起 200 秒自动回滚定时器（保险）"
echo "=============================================================="
cat > "$REVERT" <<'EOS'
#!/bin/bash
logger -t pin24 "回滚：删除 03CityKey-24g，切回 netplan-wlan0-03CityKey"
nmcli connection delete 03CityKey-24g 2>/dev/null
nmcli connection up netplan-wlan0-03CityKey 2>/dev/null
EOS
chmod 755 "$REVERT"
systemctl stop pin24-revert.timer 2>/dev/null
systemctl reset-failed pin24-revert.timer pin24-revert.service 2>/dev/null
systemd-run --on-active=200 --unit=pin24-revert --description="pin24 auto-revert" \
  "$REVERT" >/dev/null 2>&1
echo "  ✅ 已定时：200 秒后若未确认成功，自动切回原配置"
echo "     取消命令：systemctl stop pin24-revert.timer"

echo ""
echo "=============================================================="
echo " 2. 取出原配置的 SSID / 密码（不回显密码）"
echo "=============================================================="
SSID=$(nmcli -g 802-11-wireless.ssid connection show "$ORIG" 2>/dev/null)
PSK=$(nmcli -s -g 802-11-wireless-security.psk connection show "$ORIG" 2>/dev/null)
if [ -z "$SSID" ]; then echo "❌ 取不到 SSID，中止"; exit 1; fi
if [ -z "$PSK" ]; then echo "⚠️ 取不到密码，这条 profile 可能连不上（会靠定时器回滚）"; fi
echo "  SSID = $SSID"
echo "  目标 BSSID = $BSSID   （ch1 / 2412 MHz / 无 DFS）"
echo "  密码已取到: $([ -n "$PSK" ] && echo 是 || echo 否)"

echo ""
echo "=============================================================="
echo " 3. 新建钉住 BSSID 的连接"
echo "=============================================================="
nmcli connection delete "$NEW" >/dev/null 2>&1
if [ -n "$PSK" ]; then
  nmcli connection add type wifi ifname wlan0 con-name "$NEW" ssid "$SSID" \
    -- 802-11-wireless.bssid "$BSSID" \
       802-11-wireless-security.key-mgmt wpa-psk \
       802-11-wireless-security.psk "$PSK" \
       ipv4.method auto \
       ipv6.method auto \
       connection.autoconnect yes \
       connection.autoconnect-priority 100 >/dev/null 2>&1
else
  nmcli connection add type wifi ifname wlan0 con-name "$NEW" ssid "$SSID" \
    -- 802-11-wireless.bssid "$BSSID" \
       802-11-wireless-security.key-mgmt wpa-psk \
       ipv4.method auto \
       connection.autoconnect yes \
       connection.autoconnect-priority 100 >/dev/null 2>&1
fi
if nmcli -t -f NAME connection show | grep -qx "$NEW"; then
  echo "  ✅ 已创建 $NEW"
  echo "     确认钉住了 BSSID: $(nmcli -g 802-11-wireless.bssid connection show "$NEW" 2>/dev/null)"
else
  echo "  ❌ 创建失败，中止（原配置未改动）"
  systemctl stop pin24-revert.timer >/dev/null 2>&1
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
FREQ_INT=${FREQ%%.*}      # iw 返回的是 "2412.0"，去掉小数点再比较
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
  echo "  🎉 成功：钉在 2412 MHz（ch1 / 2.4G / 无 DFS），网关可达"
  echo "     取消自动回滚：systemctl stop pin24-revert.timer"
  echo "     想立刻改回  ：sudo bash $REVERT"
  echo "PIN24_RESULT=OK"
else
  echo "  ❌ 失败（预期 2412 MHz + 网关可达，实际 ${FREQ:-未知} MHz / 网关 $GWOK）"
  echo "     立刻回滚，不等定时器"
  bash "$REVERT"
  systemctl stop pin24-revert.timer >/dev/null 2>&1
  echo "     已回滚"
  echo "PIN24_RESULT=FAIL"
fi
