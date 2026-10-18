#!/bin/bash
# ============================================================
# MP3000 · 树莓派 4B 图形界面（浏览器远程桌面）一键安装
#
# 做四件事：
#   1. config.txt 加 hdmi_force_hotplug=1  —— 造一个虚拟显示器
#      （不接 HDMI 时内核报 "Cannot find any crtc or sizes"，
#        没有任何输出可抓，wayvnc / RPi Connect 都会黑屏）
#   2. 配置 /etc/wayvnc/config 并启用 wayvnc.service
#   3. 装 noVNC + websockify，开一个 systemd 服务
#      → 浏览器 http://<pi>:6080/vnc.html 就是桌面
#   4. 重启（hdmi_force_hotplug 必须重启才生效）
#
# 用法： ssh -t niyoujia@<pi> "sudo bash ~/setup_gui.sh"
# ============================================================
set -u

if [ "$(id -u)" -ne 0 ]; then
  echo "❌ 需要用 sudo 运行：ssh -t niyoujia@<pi> \"sudo bash ~/setup_gui.sh\""
  exit 1
fi

echo "=============================================="
echo " MP3000 树莓派 · 浏览器远程桌面 安装"
echo "=============================================="

# ---------- 1. 备份 config.txt ----------
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="/boot/firmware/config.txt.bak.$STAMP"
echo ""
echo "--- 1/6 备份 config.txt ---"
cp -a /boot/firmware/config.txt "$BACKUP"
echo "  已备份: $BACKUP"

# ---------- 2. 虚拟显示器 ----------
echo ""
echo "--- 2/6 加 hdmi_force_hotplug=1 ---"
if grep -q '^hdmi_force_hotplug=' /boot/firmware/config.txt; then
  sed -i 's/^hdmi_force_hotplug=.*/hdmi_force_hotplug=1/' /boot/firmware/config.txt
  echo "  已存在，改成 1"
elif grep -q '^\[all\]' /boot/firmware/config.txt; then
  sed -i '/^\[all\]/a hdmi_force_hotplug=1' /boot/firmware/config.txt
  echo "  已插入 [all] 段后"
else
  printf '\n[all]\nhdmi_force_hotplug=1\n' >> /boot/firmware/config.txt
  echo "  已追加 [all] 段"
fi
echo "  当前相关行："
grep -n -E 'hdmi_force_hotplug|display_auto_detect|dtoverlay=vc4' /boot/firmware/config.txt | sed 's/^/    /'

# ---------- 3. wayvnc 配置 ----------
echo ""
echo "--- 3/6 配置 wayvnc ---"
echo "  版本: $(wayvnc --version 2>&1 | head -1)"
# enable_auth=false：局域网内无需密码（noVNC/websockify 走这条最稳）
# ⚠️ 家用 Wi-Fi 内网可视作可信；如需密码，可改用 TLS+password，见文档
cat > /etc/wayvnc/config <<'VNCEOF'
# 由 MP3000 setup_gui.sh 生成
use_relative_paths=true
address=0.0.0.0
port=5900
enable_auth=false
enable_pam=false
VNCEOF
chmod 644 /etc/wayvnc/config
echo "  已写 /etc/wayvnc/config"
sed 's/^/    /' /etc/wayvnc/config

echo ""
echo "--- 4/6 启用 wayvnc.service ---"
systemctl enable --now wayvnc.service 2>&1 | sed 's/^/    /'
sleep 3
systemctl is-active wayvnc.service | sed 's/^/    active: /'
systemctl is-enabled wayvnc.service | sed 's/^/    enabled: /'
echo "  --- 最近日志 ---"
journalctl -u wayvnc.service -n 15 --no-pager 2>/dev/null | sed 's/^/    /'

# ---------- 4. noVNC ----------
echo ""
echo "--- 5/6 安装 noVNC + websockify（会拉 nodejs，几分钟）---"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq 2>&1 | tail -3 | sed 's/^/    /'
apt-get install -y -qq novnc websockify 2>&1 | tail -5 | sed 's/^/    /'
if [ -d /usr/share/novnc ]; then
  echo "  ✅ /usr/share/novnc 就位"
else
  echo "  ❌ noVNC 没装上，后面会失败"
fi

cat > /etc/systemd/system/novnc.service <<'UNITEOF'
[Unit]
Description=noVNC web frontend for wayvnc
After=wayvnc.service network-online.target
Wants=wayvnc.service

[Service]
Type=simple
ExecStart=/usr/bin/websockify --web=/usr/share/novnc 6080 localhost:5900
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNITEOF
systemctl daemon-reload
systemctl enable --now novnc.service 2>&1 | sed 's/^/    /'
sleep 3
systemctl is-active novnc.service | sed 's/^/    active: /'
journalctl -u novnc.service -n 10 --no-pager 2>/dev/null | sed 's/^/    /'

# ---------- 5. 端口检查 ----------
echo ""
echo "--- 6/6 端口检查 ---"
ss -ltn 2>/dev/null | grep -E ':5900|:6080' | sed 's/^/    /' || echo "    ⚠️ 5900/6080 还没监听（重启后可能才起）"

echo ""
echo "=============================================="
echo " 安装完成，5 秒后重启。"
echo ""
echo " 重启后（等 1-2 分钟）在 Windows 上："
echo "   1) 先确认能 ping 通：  ping 192.168.1.66"
echo "   2) 浏览器打开：        http://192.168.1.66:6080/vnc.html"
echo "      （noVNC 页面里点 Connect 就能看到桌面）"
echo "   3) 万一 6080 不通，先试 http://192.168.1.66:6080"
echo ""
echo " 回滚方法（如需）："
echo "   sudo cp $BACKUP /boot/firmware/config.txt"
echo "=============================================="
sleep 5
sync
reboot
