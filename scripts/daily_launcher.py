#!/usr/bin/env python3
"""
launchd 的入口壳——只做一件事：调起 daily.sh。

## 为什么需要这一层（别删）

`~/Desktop` 受 macOS TCC 保护，而 **TCC 是按可执行文件逐个授权的**。
LaunchAgent 直接跑 `/bin/bash` 会被拦，读不到 Desktop 下的脚本，**退出码 126**。
实测：com.scholaroutflow.daily 第一次注册后就是这么失败的（runs=1, exit 126），
而同机的 com.mediaflock.tick 用 `media-flock/.venv/bin/python` 跑了 13 次、退出码 0。

所以 plist 指向那个**已被授权的 python**，由它 spawn bash——
子进程按 responsible process 规则继承授权。这样不用站长再授权一次。

## 脆弱点（写在这里，免得日后莫名其妙失效）

依赖 `media-flock/.venv/bin/python` 的 TCC 授权。那个 venv 若被重建或删除，
授权可能连带失效，本任务会重新变成 126。下面的自检会把这种情况**明确报出来**，
而不是静默失败——「没报错」不等于「在工作」。
"""

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "daily.sh")
LOG = os.path.join(ROOT, "data", "daily.log")


def log(msg):
    line = f"[{time.strftime('%F %T')}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass          # 连日志都写不了的话，下面的自检会把原因报出来


def main():
    # 自检：能不能真的读到项目目录。TCC 拦截时这里就会失败，
    # 而不是让 daily.sh 跑一半莫名其妙地空转。
    try:
        os.listdir(ROOT)
    except PermissionError:
        log(f"⛔ TCC 拦截：读不了 {ROOT}。"
            "本任务依赖 media-flock/.venv/bin/python 的 TCC 授权，"
            "该 venv 若被重建/删除，授权会连带失效。"
            "解法见 memory env-launchd-tcc-desktop-trap：给专用 .app 授权，"
            "且其主可执行文件必须是真 Mach-O 二进制，不能是 shell 脚本。")
        return 126

    if not os.path.exists(SCRIPT):
        log(f"⛔ 找不到 {SCRIPT}")
        return 127

    r = subprocess.run(["/bin/bash", SCRIPT], cwd=ROOT)
    if r.returncode != 0:
        log(f"daily.sh 退出码 {r.returncode}")
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
