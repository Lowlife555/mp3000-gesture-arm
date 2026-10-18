#!/bin/bash
# 重启后取证：把 16:51:3x 那次停机的原因挖出来
# 不需要 sudo（读日志用 adm 组权限；若读不到会自动提示）
echo "=============================================================="
echo " 0. 本次启动信息"
echo "=============================================================="
date '+  now: %Y-%m-%d %H:%M:%S %Z'
echo "  boot_id : $(cat /proc/sys/kernel/random/boot_id)"
echo "  uptime -s: $(uptime -s)"
uptime | sed 's/^/  /'
echo "  throttled: $(vcgencmd get_throttled 2>/dev/null)"
echo "  温度: $(vcgencmd measure_temp 2>/dev/null)"

echo ""
echo "=============================================================="
echo " 1. ⭐⭐⭐ 上一个 boot 的日志（持久日志首次可用）"
echo "=============================================================="
echo "  --- 能看到几个 boot ---"
journalctl --list-boots --no-pager 2>/dev/null | sed 's/^/    /'
echo ""
echo "  --- 上一个 boot 的最后 60 行（停机前最后说的话）---"
if journalctl -b -1 -n 60 --no-pager >/dev/null 2>&1; then
  journalctl -b -1 -n 60 --no-pager 2>/dev/null | sed 's/^/    /'
else
  echo "    ❌ 取不到 -b -1"
fi

echo ""
echo "=============================================================="
echo " 2. ⭐⭐ 上一个 boot 里的错误级消息"
echo "=============================================================="
if journalctl -b -1 -p err --no-pager >/dev/null 2>&1; then
  journalctl -b -1 -p err --no-pager 2>/dev/null | tail -40 | sed 's/^/    /'
else
  echo "    ❌ 取不到"
fi

echo ""
echo "=============================================================="
echo " 3. ⭐⭐⭐ 内核最后的话（同步刷盘的那个文件）"
echo "=============================================================="
for f in /var/log/mp3000-crash-kern.log /var/log/mp3000-crash.log; do
  if [ -f "$f" ]; then
    echo "  --- $f 最后 40 行 ---"
    tail -40 "$f" 2>/dev/null | sed 's/^/    /'
  else
    echo "  ⚠️ $f 不存在"
  fi
done

echo ""
echo "  --- 上一个 boot 的内核错误（panic/oops/thermal/undervoltage/mmc）---"
journalctl -b -1 -k --no-pager 2>/dev/null | grep -iE 'panic|oops|BUG:|lockup|stall|watchdog|thermal|throttl|under-voltage|mmc0|I/O error|EXT4-fs error|brcmfmac|firmware' | tail -40 | sed 's/^/    /' || echo "    （无匹配或取不到）"

echo ""
echo "=============================================================="
echo " 4. ⭐⭐ Wi-Fi 看门狗日志（它有没有试图自救）"
echo "=============================================================="
if [ -f /var/log/wifi-watch.log ]; then
  echo "  --- 16:48 之后的所有记录 ---"
  grep -E 'T16:(4[89]|5[0-9])' /var/log/wifi-watch.log 2>/dev/null | tail -40 | sed 's/^/    /'
  echo "  --- 总行数 / 最后 10 行 ---"
  echo "    行数: $(wc -l < /var/log/wifi-watch.log)"
  tail -10 /var/log/wifi-watch.log | sed 's/^/    /'
else
  echo "  ⚠️ 不存在"
fi

echo ""
echo "=============================================================="
echo " 5. ⭐⭐⭐ 黑匣子 CSV 里 16:48~16:53 的记录（死前 3 分钟）"
echo "=============================================================="
python3 - <<'PY'
import csv, glob, datetime
fs = sorted(glob.glob("/var/log/pimon/pimon-*.csv"))
if not fs:
    print("  没有 CSV")
else:
    f = fs[-1]
    print(f"  文件: {f}")
    rows = list(csv.DictReader(open(f)))
    print(f"  总行数: {len(rows)}")
    sel = [r for r in rows if r.get("ts", "")[11:16] >= "16:48" and r.get("ts", "")[11:16] <= "16:53"]
    if not sel:
        sel = rows[-20:]
        print("  16:48-16:53 无记录，显示最后 20 行：")
    else:
        print(f"  16:48-16:53 共 {len(sel)} 行：")
    for r in sel:
        print(f"    {r.get('ts')}  uptime={r.get('uptime_s'):>5}  temp={r.get('temp_c'):>5}  "
              f"core_v={r.get('core_v'):>6}  load={r.get('load1'):>4}  mem={r.get('mem_used_mb'):>4}  "
              f"wlan={r.get('wlan_dbm'):>4}  throttled={r.get('throttled')}")
    # 值域
    try:
        temps = [float(r["temp_c"]) for r in rows if r.get("temp_c")]
        vols  = [float(r["core_v"]) for r in rows if r.get("core_v")]
        sgnl  = [int(r["wlan_dbm"]) for r in rows if r.get("wlan_dbm")]
        print()
        print(f"  全程 温度 {min(temps):.1f} ~ {max(temps):.1f} C")
        print(f"  全程 核心电压 {min(vols):.4f} ~ {max(vols):.4f} V")
        print(f"  全程 信号 {min(sgnl)} ~ {max(sgnl)} dBm")
        th = sorted({r.get("throttled","") for r in rows})
        print(f"  throttled 出现过的值: {th}")
    except Exception as e:
        print("  统计失败:", e)
PY

echo ""
echo "=============================================================="
echo " 6. 上一个 boot 覆盖了什么时间段（判断日志有没有覆盖到停机时刻）"
echo "=============================================================="
journalctl -b -1 -o short-iso --no-pager 2>/dev/null | head -1 | sed 's/^/    最早: /'
journalctl -b -1 -o short-iso --no-pager 2>/dev/null | tail -1 | sed 's/^/    最后: /'

echo ""
echo "=============================================================="
echo " 7. 服务现状（重启后有没有自动拉起）"
echo "=============================================================="
for s in rsyslog wifi-watchdog.service pimon.service wayvnc.service novnc.service; do
  printf "    %-24s %s\n" "$s" "$(systemctl is-active "$s" 2>/dev/null)"
done
export XDG_RUNTIME_DIR=/run/user/1000
printf "    %-24s %s\n" "demo.service(user)" "$(systemctl --user is-active demo.service 2>/dev/null)"
echo "  8090: $(ss -ltn 2>/dev/null | grep -c ':8090') 个监听"
echo ""
echo "=== 结束 ==="
