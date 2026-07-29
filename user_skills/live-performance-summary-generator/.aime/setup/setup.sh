#!/bin/bash
# Live Performance Summary Generator — environment setup
set -e
echo "[setup] AIME SDK 环境准备"
pip3 install byted-aime-sdk -i https://bytedpypi.byted.org/simple

echo "[setup] 安装 openpyxl（用于解析导出的 xlsx 副本，识别表头行 / 末行 / benchmark 命中）"
pip3 install --quiet openpyxl
