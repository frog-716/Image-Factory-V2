#!/bin/zsh
set -e
cd "${0:A:h}"
if [[ -n "$IMAGE_FACTORY_PYTHON" ]]; then
  task_python="$IMAGE_FACTORY_PYTHON"
elif [[ -f private/python.local ]]; then
  task_python="$(cat private/python.local)"
elif [[ -x .venv/bin/python ]]; then
  task_python=.venv/bin/python
else
  task_python=python3
fi
"$task_python" scripts/connect_feishu.py interactive
read '?按回车关闭。'
