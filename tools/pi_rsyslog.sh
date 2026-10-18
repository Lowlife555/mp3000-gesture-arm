#!/bin/bash
# 换路：用 rsyslog 把日志写到磁盘，绕开 journald 的 Storage 问题
# 需要 sudo
set -u

echo "=============================================================="
echo " 0. 先看 /etc/systemd/journald.conf 全文（确认里面没有别的 Storage）"
echo "=============================================================="
echo "  --- 非注释行 ---"
grep -vE '^\s*#|^\s*$' /etc/systemd/journald.conf 2>/dev/null | sed 's/^/    /'
echo "  --- 合并配置里所有 Storage= 出现的位置（按读取顺序）---"
systemd-analyze cat-config systemd/journald.conf 2>/dev/null | grep -n -B2 'Storage=' | sed 's/^/    /'

echo ""
echo "=============================================================="
echo " 1. 再给 journald 一次机会（可能是上次重启与建目录抢跑）"
echo "=============================================================="
systemctl restart systemd-journald
sleep 4
echo "  --- journald 这次的启动日志（关键：有没有 Permanent Journal 那一行）---"
journalctl -b -u systemd-journald --no-pager -n 12 2>/dev/null | tail -12 | sed 's/^/    /'
echo "  --- /var/log/journal/<machine-id> 里有东西了吗 ---"
MID=$(cat /etc/machine-id)
if find "/var/log/journal/$MID" -maxdepth 1 -name '*.journal' 2>/dev/null | grep -q .; then
  find "/var/log/journal/$MID" -maxdepth 1 -name '*.journal' 2>/dev/null | while read -r f; do
    echo "    ✅ $f  ($(stat -c%s "$f") 字节)"
  done
else
  echo "    ❌ 仍然没有 —— 放弃 journald 持久化，改走 rsyslog"
fi

echo ""
echo "=============================================================="
echo " 2. ⭐ 装 rsyslog（日志直接写磁盘，绕开 journald）"
echo "=============================================================="
export DEBIAN_FRONTEND=noninteractive
if dpkg -l rsyslog 2>/dev/null | grep -q '^ii'; then
  echo "  rsyslog 已安装，跳过"
else
  echo "  正在安装 rsyslog ..."
  apt-get update -qq 2>&1 | tail -3 | sed 's/^/    /'
  apt-get install -y -qq rsyslog 2>&1 | tail -8 | sed 's/^/    /'
fi

echo ""
echo "  --- 确认 ForwardToSyslog 生效 ---"
systemd-analyze cat-config systemd/journald.conf 2>/dev/null | grep -i 'ForwardToSyslog' | sed 's/^/    /'

echo ""
echo "  --- 写一条 rsyslog 规则，确保 kernel/daemon/auth 都落盘并轮转 ---"
cat > /etc/rsyslog.d/10-mp3000.conf <<'EOF'
# MP3000: 确保关键日志落到磁盘，并按大小轮转
# 内核消息（Wi-Fi 驱动、mmc、硬件错误都在这里）
kern.*                          -/var/log/mp3000-kern.log
# 服务/守护进程（wpa_supplicant、NetworkManager、systemd）
daemon.*                        -/var/log/mp3000-daemon.log
# 认证（sshd 登录/断开，能看出掉线时间点）
auth,authpriv.*                 -/var/log/mp3000-auth.log
# 全部信息一份（兜底）
*.*;auth,authpriv.none          -/var/log/mp3000-all.log

# 轮转：单文件 20 MB，留 3 份
$outchannel mp_kern,/var/log/mp3000-kern.log,20971520,/usr/local/sbin/rotate-mp-logs.sh mp_kern
$outchannel mp_daemon,/var/log/mp3000-daemon.log,20971520,/usr/local/sbin/rotate-mp-logs.sh mp_daemon
$outchannel mp_auth,/var/log/mp3000-auth.log,20971520,/usr/local/sbin/rotate-mp-logs.sh mp_auth
$outchannel mp_all,/var/log/mp3000-all.log,20971520,/usr/local/sbin/rotate-mp-logs.sh mp_all
EOF

cat > /usr/local/sbin/rotate-mp-logs.sh <<'EOF'
#!/bin/bash
# rsyslog outchannel 的轮转脚本
f="/var/log/${1}.log"
[ -f "$f" ] || exit 0
mv -f "$f" "$f.1" 2>/dev/null
EOF
chmod +x /usr/local/sbin/rotate-mp-logs.sh

systemctl enable --now rsyslog 2>&1 | sed 's/^/    /'
systemctl restart rsyslog
sleep 3
echo "  rsyslog 状态: active=$(systemctl is-active rsyslog)  enabled=$(systemctl is-enabled rsyslog)"

echo ""
echo "=============================================================="
echo " 3. ⭐ 验证：日志真的在写盘吗"
echo "=============================================================="
sleep 3
for f in /var/log/syslog /var/log/kern.log /var/log/mp3000-kern.log /var/log/mp3000-daemon.log /var/log/mp3000-all.log; do
  if [ -f "$f" ]; then
    echo "  ✅ $f  ($(stat -c%s "$f") 字节, 行数 $(wc -l < "$f"))"
  else
    echo "  ⚠️ $f 还没生成"
  fi
done

echo ""
echo "  --- 造一条内核消息，看它落不落盘 ---"
echo "mp3000-rsyslog-test-$(date +%s)" > /dev/kmsg 2>/dev/null || echo "  （写 /dev/kmsg 失败，正常）"
sleep 3
if [ -f /var/log/mp3000-kern.log ] && grep -q 'mp3000-rsyslog-test' /var/log/mp3000-kern.log 2>/dev/null; then
  echo "  ✅ 测试消息已落盘 -> /var/log/mp3000-kern.log"
  grep 'mp3000-rsyslog-test' /var/log/mp3000-kern.log | tail -1 | sed 's/^/    /'
elif [ -f /var/log/kern.log ] && grep -q 'mp3000-rsyslog-test' /var/log/kern.log 2>/dev/null; then
  echo "  ✅ 测试消息已落盘 -> /var/log/kern.log"
else
  echo "  ⚠️ 测试消息没找到（可能 rsyslog 还在加载规则，稍后我复查）"
fi

echo ""
echo "  --- syslog 里最近 5 行（看看有没有在写）---"
tail -5 /var/log/syslog 2>/dev/null | sed 's/^/    /' || echo "    没有 /var/log/syslog"

echo ""
echo "=============================================================="
echo " 4. 汇总"
echo "=============================================================="
echo "  证据链现状："
if find "/var/log/journal/$MID" -maxdepth 1 -name '*.journal' 2>/dev/null | grep -q .; then
  echo "    journald 持久化 : ✅ 生效了"
else
  echo "    journald 持久化 : ❌ 仍在内存"
fi
echo "    rsyslog 文本日志: $(systemctl is-active rsyslog)"
for f in /var/log/mp3000-kern.log /var/log/mp3000-daemon.log /var/log/mp3000-auth.log /var/log/mp3000-all.log; do
  [ -f "$f" ] && echo "      ✅ $f" || echo "      ⚠️ $f 未生成"
done
echo ""
echo "  服务总览："
for s in rsyslog wayvnc.service wayvnc-control.service novnc.service pimon.service wifi-watchdog.service; do
  printf "    %-26s active=%-8s enabled=%s\n" "$s" "$(systemctl is-active "$s" 2>/dev/null)" "$(systemctl is-enabled "$s" 2>/dev/null)"
done
echo ""
echo "  ⚠️ 不要重启机器。下次真的出问题时："
echo "     /var/log/mp3000-*.log 会留在 SD 卡上，我能查到死前最后几秒。"
echo "=== 结束 ==="
