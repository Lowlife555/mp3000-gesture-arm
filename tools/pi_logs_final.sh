#!/bin/bash
# 日志取证收尾：删掉坏规则、加同步写取证文件、做一次真实的内核消息落盘测试
# 需要 sudo
set -u

echo "=============================================================="
echo " 1. 删掉我那条坏的 rsyslog 规则（它一行没写，且与官方规则重复）"
echo "=============================================================="
if [ -f /etc/rsyslog.d/10-mp3000.conf ]; then
  cp /etc/rsyslog.d/10-mp3000.conf /etc/rsyslog.d/10-mp3000.conf.disabled
  rm -f /etc/rsyslog.d/10-mp3000.conf
  echo "  ✅ 已删除 /etc/rsyslog.d/10-mp3000.conf（备份为 .disabled）"
else
  echo "  已不存在"
fi
echo "  --- 现在 /etc/rsyslog.d/ 内容 ---"
ls -la /etc/rsyslog.d/ | sed 's/^/    /'
echo "  --- 顺带清掉之前生成的半成品文件 ---"
for f in /var/log/mp3000-daemon.log /var/log/mp3000-auth.log /var/log/mp3000-all.log; do
  [ -f "$f" ] && { rm -f "$f"; echo "    已删 $f"; }
done

echo ""
echo "=============================================================="
echo " 2. ⭐ 写一个【同步刷盘】的取证规则（硬死时最后几秒也不丢）"
echo "=============================================================="
cat > /etc/rsyslog.d/20-mp3000-crash.conf <<'EOF'
# MP3000 崩溃取证：同步写、不缓冲、立即刷盘
# 目的：树莓派突然断电/硬死时，最后几秒的日志也已经在 SD 卡上
# 代价：每条日志一次写盘，I/O 略增；取证结束后可删除本文件回到缓冲模式

$OMFileFlushOnTXEnd on
$OMFileAsyncWriting off

# 注意：路径前【没有 '-'】= 不使用 omit-sync，强制同步落盘
# 这是与 /var/log/syslog（带 '-'，走页缓存）的关键区别
*.*                     /var/log/mp3000-crash.log

# 单独再保一份内核的（Wi-Fi 驱动 / mmc / 掉压都在内核里）
kern.*                  /var/log/mp3000-crash-kern.log

# 认证单独一份（能看出 SSH 是干净断开还是整机消失）
auth,authpriv.*         /var/log/mp3000-crash-auth.log
EOF

echo "  ✅ 已写 /etc/rsyslog.d/20-mp3000-crash.conf"
grep -vE '^\s*#|^\s*$' /etc/rsyslog.d/20-mp3000-crash.conf | sed 's/^/    /'

echo ""
echo "=============================================================="
echo " 3. 关掉限流（崩溃瞬间可能瞬间爆量，限流会丢）"
echo "=============================================================="
cat > /etc/rsyslog.d/05-mp3000-nolimit.conf <<'EOF'
# 关掉 imuxsock 的速率限制，避免崩溃瞬间的消息被丢弃
$SystemLogRateLimitInterval 0
$SystemLogRateLimitBurst 0
EOF

mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/91-mp3000-nolimit.conf <<'EOF'
# journald 侧也关掉限流
[Journal]
RateLimitIntervalSec=0
RateLimitBurst=0
EOF

echo "  ✅ rsyslog: \$SystemLogRateLimitInterval 0"
echo "  ✅ journald: RateLimitIntervalSec=0 / RateLimitBurst=0"

echo ""
echo "=============================================================="
echo " 4. 重启 rsyslog 并验证"
echo "=============================================================="
systemctl restart rsyslog
sleep 4
echo "  rsyslog: active=$(systemctl is-active rsyslog)"
echo "  --- rsyslog 有没有报错（新配置语法对不对）---"
journalctl -b -u rsyslog --no-pager -n 20 2>/dev/null | grep -iE 'error|warn|invalid|unknown|failed' | tail -8 | sed 's/^/    /' || echo "    ✅ 无报错"

echo ""
echo "=============================================================="
echo " 5. ⭐ 真实测试：造一条内核消息，确认它同步落到 mp3000-crash-kern.log"
echo "=============================================================="
TESTMSG="mp3000-crash-test-$(date +%s)"
echo "$TESTMSG" > /dev/kmsg 2>/dev/null && echo "  已写入 /dev/kmsg: $TESTMSG" || echo "  ⚠️ 写 /dev/kmsg 失败"
sleep 3

OK=0
for f in /var/log/mp3000-crash-kern.log /var/log/mp3000-crash.log /var/log/kern.log; do
  if [ -f "$f" ] && grep -q "$TESTMSG" "$f" 2>/dev/null; then
    echo "  ✅ 测试消息命中 $f"
    grep "$TESTMSG" "$f" | tail -1 | sed 's/^/    /'
    OK=1
  fi
done
[ "$OK" -eq 0 ] && echo "  ❌ 三个文件都没命中 —— 内核消息转发有问题，我下一步查"

echo ""
echo "=============================================================="
echo " 6. 最终文件清单"
echo "=============================================================="
for f in /var/log/kern.log /var/log/syslog /var/log/auth.log \
         /var/log/mp3000-crash.log /var/log/mp3000-crash-kern.log /var/log/mp3000-crash-auth.log \
         /var/log/wifi-watch.log; do
  if [ -f "$f" ]; then
    printf "  ✅ %-38s %8s 字节  %5s 行\n" "$f" "$(stat -c%s "$f")" "$(wc -l < "$f")"
  else
    printf "  ⚠️ %-38s 未生成\n" "$f"
  fi
done
echo ""
echo "  黑匣子 CSV:"
ls -la /var/log/pimon/ 2>/dev/null | tail -3 | sed 's/^/    /'

echo ""
echo "=============================================================="
echo " 7. 服务总览 + 演示页"
echo "=============================================================="
for s in rsyslog wayvnc.service wayvnc-control.service novnc.service pimon.service wifi-watchdog.service; do
  printf "  %-24s %s\n" "$s" "$(systemctl is-active "$s" 2>/dev/null)"
done
echo ""
echo "  ⚠️ 现在不要重启。日志已经全部在 SD 卡上，下次出事我直接读。"
echo "  取证结束后（比如周四），删掉 /etc/rsyslog.d/20-mp3000-crash.conf 恢复缓冲写即可。"
echo "=== 结束 ==="
