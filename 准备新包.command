#!/bin/zsh
# Local-only launcher; does not inspect keys, install software, or call Lark/API.
task_root="${0:A:h}"
task_python="${IMAGE_FACTORY_PYTHON:-python3}"
if [[ -f "$task_root/private/python.local" ]]; then
  task_python="$(<"$task_root/private/python.local")"
elif [[ -x "$task_root/.venv/bin/python" ]]; then
  task_python="$task_root/.venv/bin/python"
fi
if ! command -v "$task_python" >/dev/null; then
  print '本机已有Python运行环境未找到。请检查环境；本入口不会自动安装。'
else
  "$task_python" "$task_root/scripts/prepare_p0.py" --interactive
fi
print '准备结束。成功生成的文件路径已显示在上方；错误时没有可用新包。'
read 'task_done?按回车关闭。'
