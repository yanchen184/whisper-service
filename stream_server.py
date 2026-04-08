"""Whisper 即時轉錄 WebSocket Server

啟動方式：python stream_server.py
前端連線：ws://localhost:8765

協議：
  → {"action": "start", "language": "zh"}  開始辨識
  → {"action": "stop"}                      停止辨識
  ← {"type": "status", "message": "..."}   狀態通知
  ← {"type": "transcript", "text": "..."}  轉錄文字
"""

import asyncio
import json
import os
import re
import signal
import sys

import websockets

WHISPER_STREAM = "/opt/homebrew/bin/whisper-stream"
MODEL_PATH = os.environ.get(
    "WHISPER_MODEL_PATH",
    os.path.join(os.path.dirname(__file__), "models", "ggml-small.bin"),
)
PORT = int(os.environ.get("STREAM_PORT", "8765"))

active_client = None
active_process = None


async def read_stdout(process, websocket):
    """持續讀取 whisper-stream 的 stdout 並推送到前端"""
    try:
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").strip()
            # whisper-stream 輸出格式可能帶時間戳 [00:00:00.000 --> 00:00:03.000]
            # 去掉時間戳只保留文字
            text = re.sub(r"\[[\d:.]+\s*-->\s*[\d:.]+\]\s*", "", text)
            if text and not text.startswith(("init:", "whisper_", "ggml_", "load_")):
                await websocket.send(json.dumps({"type": "transcript", "text": text}))
    except (websockets.ConnectionClosed, asyncio.CancelledError):
        pass


async def read_stderr(process):
    """讀取 stderr（log），偵測模型載入完成"""
    try:
        while True:
            line = await process.stderr.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if text:
                print(f"[whisper-stream] {text}", file=sys.stderr)
    except asyncio.CancelledError:
        pass


async def handler(websocket):
    global active_client, active_process

    # 同一時間只允許一個 client（麥克風是共享資源）
    if active_client is not None:
        await websocket.send(json.dumps({
            "type": "error",
            "message": "已有其他使用者正在使用，請稍後再試",
        }))
        await websocket.close()
        return

    active_client = websocket
    stdout_task = None
    stderr_task = None

    try:
        async for message in websocket:
            data = json.loads(message)

            if data["action"] == "start":
                # 如果已有 process 在跑，先停止
                if active_process is not None:
                    active_process.terminate()
                    await active_process.wait()

                lang = data.get("language", "zh")
                await websocket.send(json.dumps({
                    "type": "status",
                    "message": "loading",
                }))

                active_process = await asyncio.create_subprocess_exec(
                    WHISPER_STREAM,
                    "-m", MODEL_PATH,
                    "-l", lang,
                    "--step", "3000",
                    "--length", "10000",
                    "--keep", "200",
                    "--keep-context",
                    "-t", "4",
                    "-c", "-1",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                stdout_task = asyncio.create_task(read_stdout(active_process, websocket))
                stderr_task = asyncio.create_task(read_stderr(active_process))

                await websocket.send(json.dumps({
                    "type": "status",
                    "message": "started",
                }))

            elif data["action"] == "stop":
                if active_process is not None:
                    active_process.terminate()
                    await active_process.wait()
                    active_process = None
                if stdout_task:
                    stdout_task.cancel()
                if stderr_task:
                    stderr_task.cancel()
                await websocket.send(json.dumps({
                    "type": "status",
                    "message": "stopped",
                }))

    except websockets.ConnectionClosed:
        pass
    finally:
        if active_process is not None:
            active_process.terminate()
            try:
                await asyncio.wait_for(active_process.wait(), timeout=5)
            except asyncio.TimeoutError:
                active_process.kill()
            active_process = None
        if stdout_task:
            stdout_task.cancel()
        if stderr_task:
            stderr_task.cancel()
        active_client = None


async def main():
    print(f"Whisper Stream Server running on ws://localhost:{PORT}")
    print(f"Model: {MODEL_PATH}")
    print(f"Press Ctrl+C to stop")
    async with websockets.serve(handler, "localhost", PORT):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
