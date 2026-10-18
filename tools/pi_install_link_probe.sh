#!/bin/bash
# 安装「入向探针」：解决今天查不出根因的关键盲区
#
# 现有观测全是"出向"的（ping 网关成功、信号正常），但故障是"入向不通"。
# 本探针每 30 秒记录三样能区分责任方的东西：
#   1. wlan0 的 RX/TX 字节计数 → RX 停滞而 TX 增长 = AP 不再投递
#   2. 从树莓派 arping 笔记本(.52) → 无线↔无线这一段是否被拦
#   3. iw link 的关联状态 / 信号 / 重传
#
# 只读观测 + 局域网内 ARP 探测，不改任何配置。
set -u

LOG=/var/log/link-probe.log
SCRIPT=/usr/local/sbin/link-probe.sh
PEER=192.168.1.52          # 笔记本
GW=192.168.1.1
INTERVAL=30

echo "=============================================================="
echo " 1. 写探针脚本到 $SCRIPT"
echo "=============================================================="
cat > "$SCRIPT" <<'EOS'
#!/bin/bash
LOG=/var/log/link-probe.log
PEER=192.168.1.52
GW=192.168.1.1

if [ ! -f "$LOG" ]; then
  echo "ts,assoc,freq,signal,rx_bytes,tx_bytes,rx_bytes_delta,arping_peer,gw_ping,retries" > "$LOG"
fi

prev_rx=""
while true; do
  TS=$(date +%Y-%m-%dT%H:%M:%S%z)

  LINK=$(iw dev wlan0 link 2>/dev/null)
  if [ -n "$LINK" ]; then
    ASSOC=yes
    FREQ=$(echo "$LINK" | awk '/freq:/{print $2}')
    SIG=$(echo "$LINK" | awk '/signal:/{print $2}')
  else
    ASSOC=NO; FREQ=""; SIG=""
  fi

  # 收发字节数（从 /sys 读，最省事）
  RX=$(cat /sys/class/net/wlan0/statistics/rx_bytes 2>/dev/null || echo 0)
  TX=$(cat /sys/class/net/wlan0/statistics/tx_bytes 2>/dev/null || echo 0)
  if [ -n "$prev_rx" ]; then DELTA=$((RX - prev_rx)); else DELTA=0; fi
  prev_rx=$RX

  # ★ 关键：从树莓派主动 arping 笔记本。回包必须由 AP 转发才能收到，
  #   所以这测的正是"入向"这条路。
  if timeout 4 arping -c 2 -w 3 -I wlan0 "$PEER" >/dev/null 2>&1; then APEER=ok; else APEER=FAIL; fi

  if ping -c 1 -W 2 "$GW" >/dev/null 2>&1; then GWOK=ok; else GWOK=FAIL; fi

  RETRIES=$(iw dev wlan0 station dump 2>/dev/null | awk '/tx retries:/{print $3; exit}')

  echo "$TS,$ASSOC,$FREQ,$SIG,$RX,$TX,$DELTA,$APEER,$GWOK,${RETRIES:-}" >> "$LOG"

  # 2 MB 轮转
  if [ "$(stat -c%s "$LOG")" -gt 2097152 ]; then
    mv -f "$LOG" "$LOG.1"
  fi

  sleep 30
done
EOS
chmod 755 "$SCRIPT"
echo "  ✅ 已写入"

echo ""
echo "=============================================================="
echo " 2. 装 systemd 服务"
echo "=============================================================="
cat > /etc/systemd/system/link-probe.service <<EOS
[Unit]
Description=Inbound reachability probe (RX/TX counters + arping peer)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$SCRIPT
Restart=always
RestartSec=5
Nice=10

[Install]
WantedBy=multi-user.target
EOS
systemctl daemon-reload
systemctl enable --now link-probe.service >/dev/null 2>&1 || echo "  ⚠️ enable 返回非零，继续检查状态"
sleep 6
echo "  服务状态: $(systemctl is-active link-probe.service)"

echo ""
echo "=============================================================="
echo " 3. 前 2 行样本"
echo "=============================================================="
sleep 20
head -1 "$LOG" | sed 's/^/  /'
tail -1 "$LOG" | sed 's/^/  /'

echo ""
echo "=============================================================="
echo " 4. 顺手修掉 pimon 的 mem 列（zh_CN locale 让 free 输出变中文）"
echo "=============================================================="
echo "  改前 MEM 行: $(grep -m1 'MEM=' /usr/local/sbin/pimon.sh 2>/dev/null)"
if grep -q '^export LC_ALL=C' /usr/local/sbin/pimon.sh 2>/dev/null; then
  echo "  ✅ 已经有 LC_ALL=C，无需改动"
else
  cp -a /usr/local/sbin/pimon.sh /root/pimon.sh.bak-locale 2>/dev/null || true
  sed -i '1a export LC_ALL=C' /usr/local/sbin/pimon.sh
  echo "  改后第 2 行: $(sed -n '2p' /usr/local/sbin/pimon.sh)"
  echo "  验证 free 能解析: $(LC_ALL=C free -m | awk '/^Mem:/{print $3}') MB"
  systemctl restart pimon.service 2>/dev/null || true
  sleep 3
  echo "  pimon 状态: $(systemctl is-active pimon.service)"
  echo "  最新一行: $(tail -1 /var/log/pimon/pimon-$(date +%Y%m%d).csv 2>/dev/null)"
fi

echo ""
echo "=============================================================="
echo " 完成"
echo "=============================================================="
echo "  日志: $LOG"
echo "  查看: tail -f $LOG"
echo "  停止: sudo systemctl disable --now link-probe.service"
echo "LINK_PROBE=OK"
