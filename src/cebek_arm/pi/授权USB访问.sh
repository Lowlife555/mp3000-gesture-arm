#!/bin/bash
# 授权树莓派用户态访问 Cebek 机械臂（1267:0000）
# 只需要跑一次；要输一次密码。

set -e

RULE=/etc/udev/rules.d/99-cebek-arm.rules

echo "==> 当前设备权限："
lsusb -d 1267:0000 || echo "    （现在没插机械臂，不影响，规则可以先生效）"
echo

echo "==> 写入 udev 规则到 $RULE"
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="1267", ATTR{idProduct}=="0000", MODE="0666"' \
  | sudo tee "$RULE"

echo
echo "==> 重新加载 udev 规则"
sudo udevadm control --reload-rules
sudo udevadm trigger

echo
echo "==> 完成。请把机械臂 USB 拔下再插上，然后跑："
echo "      python3 ~/Desktop/CebekArm/cebek.py info"
