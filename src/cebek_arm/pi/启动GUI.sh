#!/bin/bash
# 双击启动图形界面。如果闪退，下面的窗口会留住错误信息。
cd "$(dirname "$0")" || exit 1
echo "工作目录：$(pwd)"
echo "启动 Cebek 机械臂控制台…"
echo
python3 cebek.py gui
rc=$?
echo
if [ $rc -ne 0 ]; then
  echo "退出码 $rc —— 有错误，上面的信息请截图保存。"
  read -r -p "按回车关闭窗口…" _
fi
