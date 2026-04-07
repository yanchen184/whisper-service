#!/bin/bash
# Whisper 語音轉文字 — 一鍵腳本
# 用法: ./run.sh <影片或音頻> [--srt|--txt|--csv|--json] [--medium|--large]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT_DIR="$SCRIPT_DIR/output"
MODEL_DIR="$SCRIPT_DIR/models"

# 預設值
MODEL="$MODEL_DIR/ggml-large-v2.bin"
OUTPUT_FORMAT=""
LANG="zh"

# 解析參數
INPUT_FILE=""
for arg in "$@"; do
    case "$arg" in
        --srt)    OUTPUT_FORMAT="-osrt" ;;
        --txt)    OUTPUT_FORMAT="-otxt" ;;
        --csv)    OUTPUT_FORMAT="-ocsv" ;;
        --json)   OUTPUT_FORMAT="-ojf" ;;
        --medium) MODEL="$MODEL_DIR/ggml-medium.bin" ;;
        --large)  MODEL="$MODEL_DIR/ggml-large-v2.bin" ;;
        --en)     LANG="en" ;;
        --auto)   LANG="auto" ;;
        *)        INPUT_FILE="$arg" ;;
    esac
done

if [ -z "$INPUT_FILE" ]; then
    echo "用法: ./run.sh <影片或音頻檔案> [選項]"
    echo ""
    echo "選項:"
    echo "  --srt      輸出 SRT 字幕檔"
    echo "  --txt      輸出純文字檔"
    echo "  --csv      輸出 CSV"
    echo "  --json     輸出 JSON"
    echo "  --medium   使用 medium 模型（較快）"
    echo "  --large    使用 large-v2 模型（預設，較準）"
    echo "  --en       英文模式"
    echo "  --auto     自動偵測語言"
    echo ""
    echo "範例:"
    echo "  ./run.sh ~/Desktop/lecture.mov"
    echo "  ./run.sh ~/Desktop/lecture.mov --srt --medium"
    echo "  ./run.sh recording.wav --txt"
    exit 1
fi

if [ ! -f "$INPUT_FILE" ]; then
    echo "錯誤: 找不到檔案 $INPUT_FILE"
    exit 1
fi

if [ ! -f "$MODEL" ]; then
    echo "錯誤: 找不到模型 $MODEL"
    echo "請先下載模型到 $MODEL_DIR/"
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

# 取得檔名（不含副檔名）
BASENAME=$(basename "$INPUT_FILE")
NAME="${BASENAME%.*}"
WAV_FILE="$OUTPUT_DIR/${NAME}.wav"

# 判斷是否需要轉換音頻
EXT="${INPUT_FILE##*.}"
AUDIO_EXTS="wav"

if [ "$EXT" = "wav" ]; then
    # 檢查是否已經是 16kHz mono
    SAMPLE_RATE=$(ffprobe -v error -select_streams a:0 -show_entries stream=sample_rate -of default=noprint_wrappers=1:nokey=1 "$INPUT_FILE" 2>/dev/null || echo "0")
    CHANNELS=$(ffprobe -v error -select_streams a:0 -show_entries stream=channels -of default=noprint_wrappers=1:nokey=1 "$INPUT_FILE" 2>/dev/null || echo "0")
    if [ "$SAMPLE_RATE" = "16000" ] && [ "$CHANNELS" = "1" ]; then
        WAV_FILE="$INPUT_FILE"
        echo "音頻格式正確，跳過轉換"
    else
        echo "轉換音頻格式 → 16kHz mono WAV ..."
        ffmpeg -i "$INPUT_FILE" -vn -ar 16000 -ac 1 -c:a pcm_s16le "$WAV_FILE" -y -loglevel error
    fi
else
    echo "抽取音軌 → 16kHz mono WAV ..."
    ffmpeg -i "$INPUT_FILE" -vn -ar 16000 -ac 1 -c:a pcm_s16le "$WAV_FILE" -y -loglevel error
fi

# 取得音頻長度
DURATION=$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$WAV_FILE" | cut -d. -f1)
echo "音頻長度: ${DURATION}s"
echo "模型: $(basename "$MODEL")"
echo "語言: $LANG"
echo ""

# 執行轉錄
echo "轉錄中 ..."
START_TIME=$(date +%s)

whisper-cli \
    -m "$MODEL" \
    -f "$WAV_FILE" \
    -l "$LANG" \
    -t 8 \
    $OUTPUT_FORMAT \
    -of "$OUTPUT_DIR/$NAME" \
    2>&1 | grep -E "^\[|whisper_print_timings:.*total"

END_TIME=$(date +%s)
ELAPSED=$((END_TIME - START_TIME))

echo ""
echo "完成！耗時: ${ELAPSED}s（音頻 ${DURATION}s）"

if [ -n "$OUTPUT_FORMAT" ]; then
    echo "輸出檔案: $OUTPUT_DIR/$NAME.*"
    ls -lh "$OUTPUT_DIR/$NAME".* 2>/dev/null
fi
