"""Breeze ASR 25 語音轉文字腳本 (Apple M2 MPS 加速)"""

import sys
import time
import torch
import torchaudio
from transformers import WhisperProcessor, WhisperForConditionalGeneration, AutomaticSpeechRecognitionPipeline

MODEL_ID = "MediaTek-Research/Breeze-ASR-25"


def get_device():
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def load_audio(audio_path: str):
    waveform, sample_rate = torchaudio.load(audio_path)

    # 多聲道轉單聲道
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0)
    waveform = waveform.squeeze()

    # 重取樣到 16kHz
    if sample_rate != 16_000:
        resampler = torchaudio.transforms.Resample(sample_rate, 16_000)
        waveform = resampler(waveform)
        sample_rate = 16_000

    return waveform.numpy(), sample_rate


def transcribe(audio_path: str):
    device = get_device()
    print(f"裝置: {device}")
    print(f"載入模型: {MODEL_ID} ...")

    t0 = time.time()
    processor = WhisperProcessor.from_pretrained(MODEL_ID)
    model = WhisperForConditionalGeneration.from_pretrained(MODEL_ID)
    model = model.to(device).eval()
    print(f"模型載入完成 ({time.time() - t0:.1f}s)")

    # 載入音頻
    print(f"載入音頻: {audio_path}")
    waveform, sample_rate = load_audio(audio_path)
    duration = len(waveform) / sample_rate
    print(f"音頻長度: {duration:.1f}s")

    # 建立 pipeline
    asr_pipeline = AutomaticSpeechRecognitionPipeline(
        model=model,
        tokenizer=processor.tokenizer,
        feature_extractor=processor.feature_extractor,
        chunk_length_s=0,
        device=device,
    )

    # 推理
    print("轉錄中 ...")
    t0 = time.time()
    output = asr_pipeline(waveform, return_timestamps=True)
    elapsed = time.time() - t0

    print(f"\n{'='*60}")
    print(f"轉錄結果:")
    print(f"{'='*60}")
    print(output["text"])
    print(f"{'='*60}")
    print(f"耗時: {elapsed:.1f}s (音頻 {duration:.1f}s, 速度比: {duration/elapsed:.1f}x)")

    # 顯示時間戳記
    if "chunks" in output:
        print(f"\n時間戳記:")
        for chunk in output["chunks"]:
            start, end = chunk["timestamp"]
            print(f"  [{start:.1f}s - {end:.1f}s] {chunk['text']}")

    return output


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python transcribe.py <音頻檔案路徑>")
        print("支援格式: wav, mp3, flac, m4a, ogg")
        print()
        print("範例:")
        print("  python transcribe.py recording.wav")
        print("  python transcribe.py meeting.mp3")
        sys.exit(1)

    transcribe(sys.argv[1])
