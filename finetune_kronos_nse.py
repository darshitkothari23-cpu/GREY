"""
Fine-tune Kronos-small on the local NIFTY candle CSV.

This script prepares GREY's `nifty_candles.csv` for the official Kronos
`finetune_csv` pipeline, runs a laptop-friendly training pass, and copies the
best model into `kronos_nse_finetuned`.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd


INPUT_CSV = Path("nifty_candles.csv")
KRONOS_REPO = Path("Kronos")
TRAINING_CSV = Path("nifty_candles_for_kronos.csv")
CONFIG_PATH = KRONOS_REPO / "finetune_csv" / "configs" / "config_grey_nifty.yaml"
MODEL_DIR = Path("models") / "Kronos-small"
TOKENIZER_DIR = Path("models") / "Kronos-Tokenizer-base"
WORK_DIR = Path("kronos_nse_finetuned_work")
FINAL_DIR = Path("kronos_nse_finetuned")


def main() -> None:
    """Prepare data, run Kronos fine-tuning, and save the local model folder."""
    try:
        print("Step 1: Checking required files and folders...")
        check_inputs()

        print("Step 2: Preparing NIFTY candles for Kronos CSV training...")
        row_count = prepare_training_csv()
        print(f"Step 2 done: Prepared {row_count} rows at {TRAINING_CSV}")

        print("Step 3: Making sure Hugging Face model files are available locally...")
        ensure_huggingface_snapshots()

        print("Step 4: Writing a laptop-friendly Kronos fine-tuning config...")
        write_config(row_count)
        print(f"Step 4 done: Wrote {CONFIG_PATH}")

        print("Step 5: Running official Kronos finetune_csv sequential trainer...")
        run_kronos_trainer()

        print("Step 6: Copying the best fine-tuned model into GREY's model folder...")
        copy_final_model()
        print(f"Training complete. Final model folder: {FINAL_DIR}")
    except Exception as exc:
        print(f"Kronos fine-tuning failed safely: {exc}")
        print("Check that the Kronos repo is cloned and dependencies are installed.")
        raise SystemExit(1) from exc


def check_inputs() -> None:
    """Stop early with a helpful message if the input files are missing."""
    if not INPUT_CSV.exists():
        raise FileNotFoundError("nifty_candles.csv is missing. Run fetch_nse_data.py first.")
    if not (KRONOS_REPO / "finetune_csv" / "train_sequential.py").exists():
        raise FileNotFoundError(
            "Kronos/finetune_csv/train_sequential.py is missing. "
            "Clone https://github.com/shiyu-coder/Kronos first."
        )


def prepare_training_csv() -> int:
    """Convert GREY candle columns into the CSV shape expected by Kronos."""
    df = pd.read_csv(INPUT_CSV)

    # Kronos uses the column name `timestamps`.
    if "timestamp" in df.columns:
        df = df.rename(columns={"timestamp": "timestamps"})
    if "timestamps" not in df.columns:
        raise ValueError("CSV must contain timestamp or timestamps column.")

    # Kronos expects an amount column; NIFTY spot data may not provide one.
    if "amount" not in df.columns:
        df["amount"] = 0.0

    # Keep the training file simple and explicit.
    required = ["timestamps", "open", "high", "low", "close", "volume", "amount"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"Missing required candle columns: {missing}")

    df = df[required].copy()
    df["timestamps"] = pd.to_datetime(df["timestamps"], errors="coerce")
    for column in ["open", "high", "low", "close", "volume", "amount"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["timestamps", "open", "high", "low", "close"])
    if len(df) < 120:
        raise ValueError("Need at least 120 candles for a useful fine-tuning pass.")

    df.to_csv(TRAINING_CSV, index=False)
    return len(df)


def ensure_huggingface_snapshots() -> None:
    """Download Kronos-small and tokenizer snapshots if they are not already local."""
    if MODEL_DIR.exists() and TOKENIZER_DIR.exists():
        print("Model snapshots already exist. Skipping download.")
        return

    # huggingface_hub is installed in the setup commands below.
    from huggingface_hub import snapshot_download

    MODEL_DIR.parent.mkdir(parents=True, exist_ok=True)
    if not MODEL_DIR.exists():
        print("Downloading NeoQuasar/Kronos-small...")
        snapshot_download(
            repo_id="NeoQuasar/Kronos-small",
            local_dir=str(MODEL_DIR),
            local_dir_use_symlinks=False,
        )
    if not TOKENIZER_DIR.exists():
        print("Downloading NeoQuasar/Kronos-Tokenizer-base...")
        snapshot_download(
            repo_id="NeoQuasar/Kronos-Tokenizer-base",
            local_dir=str(TOKENIZER_DIR),
            local_dir_use_symlinks=False,
        )


def write_config(row_count: int) -> None:
    """Write the Kronos finetune_csv YAML config using relative paths."""
    # Keep the lookback smaller than 512 so a 512-row file still creates samples.
    lookback_window = max(64, min(256, row_count // 2))
    predict_window = 5
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    config_text = f"""
data:
  data_path: "../../{TRAINING_CSV.as_posix()}"
  lookback_window: {lookback_window}
  predict_window: {predict_window}
  max_context: 512
  clip: 5.0
  train_ratio: 0.85
  val_ratio: 0.15
  test_ratio: 0.0

training:
  tokenizer_epochs: 1
  basemodel_epochs: 1
  batch_size: 2
  log_interval: 10
  num_workers: 0
  seed: 42
  tokenizer_learning_rate: 0.0002
  predictor_learning_rate: 0.000001
  adam_beta1: 0.9
  adam_beta2: 0.95
  adam_weight_decay: 0.1
  accumulation_steps: 1

model_paths:
  pretrained_tokenizer: "../../{TOKENIZER_DIR.as_posix()}"
  pretrained_predictor: "../../{MODEL_DIR.as_posix()}"
  exp_name: "nifty_15m"
  base_path: "../../{WORK_DIR.as_posix()}"
  base_save_path: "../../{(WORK_DIR / 'nifty_15m').as_posix()}"
  finetuned_tokenizer: "../../{TOKENIZER_DIR.as_posix()}"
  tokenizer_save_name: "tokenizer"
  basemodel_save_name: "basemodel"

experiment:
  name: "grey_kronos_nifty_finetune"
  description: "GREY laptop-friendly Kronos fine-tune on NIFTY 15-minute candles"
  use_comet: false
  train_tokenizer: false
  train_basemodel: true
  skip_existing: false
  pre_trained_tokenizer: true
  pre_trained_predictor: true

device:
  use_cuda: true
  device_id: 0

distributed:
  use_ddp: false
  backend: "gloo"
""".strip()

    CONFIG_PATH.write_text(config_text + "\n", encoding="utf-8")


def run_kronos_trainer() -> None:
    """Run Kronos' official CSV fine-tuning script with this Python interpreter."""
    command = [
        sys.executable,
        "train_sequential.py",
        "--config",
        "configs/config_grey_nifty.yaml",
        "--skip-tokenizer",
    ]
    result = subprocess.run(command, check=False, cwd=KRONOS_REPO / "finetune_csv")
    if result.returncode != 0:
        raise RuntimeError(f"Kronos trainer exited with code {result.returncode}")


def copy_final_model() -> None:
    """Copy the trained predictor and tokenizer into GREY's expected model folder."""
    trained_model = WORK_DIR / "nifty_15m" / "basemodel" / "best_model"
    if not trained_model.exists():
        raise FileNotFoundError(f"Fine-tuned model not found: {trained_model}")

    if FINAL_DIR.exists():
        shutil.rmtree(FINAL_DIR)
    (FINAL_DIR / "model").parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(trained_model, FINAL_DIR / "model")
    shutil.copytree(TOKENIZER_DIR, FINAL_DIR / "tokenizer")


if __name__ == "__main__":
    main()
