#!/bin/bash
# skill-heatmap-generator — environment setup
set -e
echo "[setup] AIME SDK 环境准备"
pip3 install byted-aime-sdk -i https://bytedpypi.byted.org/simple

# 本技能仅依赖 Python 标准库（json/re/subprocess/pathlib 等）+ 内置 lark MCP 包装器。
# 暂不需要额外公网依赖。
