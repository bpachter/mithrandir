@echo off
REM ============================================================
REM train.bat — Launch StyleTTS2 fine-tuning for Mithrandir voice
REM Run after setup_styletts2.bat and prepare_training_data.py
REM ============================================================

set HERE=%~dp0
set VENV_PYTHON=%HERE%..\.venv\Scripts\python.exe
set REPO=%HERE%styletts2_repo

echo.
echo === Mithrandir Voice Training ===
echo Starting StyleTTS2 fine-tuning...
echo Logs → %HERE%logs\mithrandir_voice\
echo Checkpoints → %HERE%logs\mithrandir_voice\
echo.
echo Training will run for ~100 epochs (~6-10 hours on RTX 4090).
echo You can interrupt with Ctrl+C and resume by setting a checkpoint
echo in finetune_config.yml under "pretrained_model".
echo.

REM Run from repo directory so relative imports work
cd /d "%REPO%"
%VENV_PYTHON% train_finetune_accelerate.py --config "%HERE%finetune_config.yml"

echo.
echo Training complete.
echo Run export_mithrandir_voice.py to package the model for Mithrandir.
pause
