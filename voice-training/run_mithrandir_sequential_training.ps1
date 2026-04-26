param(
    [string]$PythonExe = "C:\Python312\python.exe",
    [string]$VoiceId = "Wqq9Rb5pNi1joOGwk9ni",
    [string]$Model = "eleven_multilingual_v2",
    [string]$ApiKey = "",
    [int]$Stage1Epochs = 70,
    [int]$Stage2Epochs = 45,
    [switch]$Resume,
    [switch]$SkipStage1,
    [switch]$SkipStage2
)

$ErrorActionPreference = 'Stop'

$HERE = $PSScriptRoot
$Repo = Join-Path $HERE "styletts2_repo"
$TemplateConfig = Join-Path $HERE "finetune_elevenlabs.yml"
$LogDir = Join-Path $HERE "logs\mithrandir_elevenlabs"
$RunDir = Join-Path $HERE "runs\sequential_training"
$RunLog = Join-Path $RunDir "run.log"
$StatePath = Join-Path $RunDir "state.json"

$Stage1Corpus = Join-Path $HERE "corpora\quality_pronunciation.txt"
$Stage2Corpus = Join-Path $HERE "corpora\emotional_contours.txt"
$Stage1Data = Join-Path $HERE "elevenlabs_data_stage1"
$Stage2Data = Join-Path $HERE "elevenlabs_data_stage2"
$Stage1Cfg = Join-Path $RunDir "finetune_stage1.yml"
$Stage2Cfg = Join-Path $RunDir "finetune_stage2.yml"

New-Item -ItemType Directory -Force -Path $RunDir | Out-Null

function Write-Log([string]$Message) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $Message"
    Write-Host $line
    Add-Content -Path $RunLog -Value $line
}

function Save-State([string]$Stage, [string]$Status, [string]$Detail = "") {
    $obj = [ordered]@{
        timestamp = (Get-Date -Format "s")
        stage = $Stage
        status = $Status
        detail = $Detail
    }
    $json = $obj | ConvertTo-Json -Depth 5
    Set-Content -Path $StatePath -Value $json -Encoding UTF8
}

function Invoke-Checked([string]$Stage, [string]$Command, [string[]]$CmdParams, [string]$WorkingDir) {
    Write-Log "[$Stage] RUN: $Command $($CmdParams -join ' ')"
    Push-Location $WorkingDir
    try {
        & $Command @CmdParams
        if ($LASTEXITCODE -ne 0) {
            throw "command exited with code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}

function Get-LatestCheckpoint([string]$Path) {
    if (-not (Test-Path $Path)) { return $null }
    $ckpt = Get-ChildItem -Path $Path -Filter "epoch_2nd_*.pth" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($null -eq $ckpt) { return $null }
    return $ckpt.FullName
}

function Build-Config(
    [string]$TemplatePath,
    [string]$OutputPath,
    [string]$TrainList,
    [string]$ValList,
    [string]$CheckpointPath,
    [int]$Epochs,
    [double]$LR,
    [double]$BertLR,
    [double]$FtLR
) {
    if (-not (Test-Path $TemplatePath)) {
        throw "Template config not found: $TemplatePath"
    }

    $trainRel = "../" + [System.IO.Path]::GetRelativePath($Repo, $TrainList).Replace('\\', '/')
    $valRel = "../" + [System.IO.Path]::GetRelativePath($Repo, $ValList).Replace('\\', '/')
    $ckptRel = "../" + [System.IO.Path]::GetRelativePath($Repo, $CheckpointPath).Replace('\\', '/')

    $dq = [char]34
    $lines = Get-Content -Path $TemplatePath
    $out = New-Object System.Collections.Generic.List[string]

    foreach ($line in $lines) {
        $trim = $line.TrimStart()

        if ($trim.StartsWith('epochs:')) {
            $out.Add("epochs: $Epochs")
            continue
        }
        if ($trim.StartsWith('pretrained_model:')) {
            $out.Add("pretrained_model: $dq$ckptRel$dq")
            continue
        }
        if ($trim.StartsWith('train_data:')) {
            $out.Add("  train_data: $dq$trainRel$dq")
            continue
        }
        if ($trim.StartsWith('val_data:')) {
            $out.Add("  val_data: $dq$valRel$dq")
            continue
        }
        if ($trim.StartsWith('lr:')) {
            $out.Add("  lr: $LR")
            continue
        }
        if ($trim.StartsWith('bert_lr:')) {
            $out.Add("  bert_lr: $BertLR")
            continue
        }
        if ($trim.StartsWith('ft_lr:')) {
            $out.Add("  ft_lr: $FtLR")
            continue
        }

        $out.Add($line)
    }

    Set-Content -Path $OutputPath -Value $out -Encoding UTF8
}

try {
    Write-Log "=== Mithrandir sequential training start ==="
    Save-State "bootstrap" "running" "validating prerequisites"

    if (-not (Test-Path $PythonExe)) { throw "Python not found: $PythonExe" }
    if (-not (Test-Path $Repo)) { throw "StyleTTS2 repo not found: $Repo" }
    if (-not (Test-Path $TemplateConfig)) { throw "Template config not found: $TemplateConfig" }
    if (-not (Test-Path $Stage1Corpus)) { throw "Missing corpus: $Stage1Corpus" }
    if (-not (Test-Path $Stage2Corpus)) { throw "Missing corpus: $Stage2Corpus" }

    if (-not $ApiKey) {
        $ApiKey = $env:ELEVENLABS_API_KEY
    }
    if (-not $ApiKey) {
        throw "ELEVENLABS API key missing. Pass -ApiKey or set ELEVENLABS_API_KEY."
    }

    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

    $baseCheckpoint = Get-LatestCheckpoint $LogDir
    if (-not $baseCheckpoint) {
        $baseCheckpoint = Join-Path $HERE "pretrained\StyleTTS2-LibriTTS\epochs_2nd_00020.pth"
    }
    if (-not (Test-Path $baseCheckpoint)) {
        throw "No valid base checkpoint found. Expected latest in logs or pretrained default."
    }

    if (-not $SkipStage1) {
        Save-State "stage1_dataset" "running" "generating quality+pronunciation dataset"
        Write-Log "Stage 1A: Generating quality+pronunciation dataset"
        $stage1Args = @(
            (Join-Path $HERE "generate_elevenlabs_dataset.py"),
            "--api-key", $ApiKey,
            "--voice-id", $VoiceId,
            "--model", $Model,
            "--out-dir", $Stage1Data,
            "--sentences-file", $Stage1Corpus,
            "--stability", "0.72",
            "--similarity", "0.92",
            "--style", "0.18",
            "--val-fraction", "0.08"
        )
        if ($Resume) { $stage1Args += "--resume" }
        Invoke-Checked "stage1_dataset" $PythonExe $stage1Args $HERE

        Save-State "stage1_train" "running" "training clarity/pronunciation phase"
        Write-Log "Stage 1B: Training quality+pronunciation phase"
        $stage1TrainList = Join-Path $Stage1Data "train_list.txt"
        $stage1ValList = Join-Path $Stage1Data "val_list.txt"
        if (-not (Test-Path $stage1TrainList) -or -not (Test-Path $stage1ValList)) {
            throw "Stage 1 filelists missing after dataset generation"
        }

        Build-Config -TemplatePath $TemplateConfig -OutputPath $Stage1Cfg `
            -TrainList $stage1TrainList -ValList $stage1ValList `
            -CheckpointPath $baseCheckpoint -Epochs $Stage1Epochs `
            -LR 8.0e-6 -BertLR 8.0e-7 -FtLR 8.0e-6

        $trainArgs1 = @("train_finetune_accelerate.py", "--config_path", $Stage1Cfg)
        Invoke-Checked "stage1_train" $PythonExe $trainArgs1 $Repo
    }

    $stage1Checkpoint = Get-LatestCheckpoint $LogDir
    if (-not $stage1Checkpoint) {
        throw "No checkpoint found after Stage 1"
    }
    Write-Log "Stage 1 checkpoint: $stage1Checkpoint"

    if (-not $SkipStage2) {
        Save-State "stage2_dataset" "running" "generating emotional contour dataset"
        Write-Log "Stage 2A: Generating emotional contour dataset"
        $stage2Args = @(
            (Join-Path $HERE "generate_elevenlabs_dataset.py"),
            "--api-key", $ApiKey,
            "--voice-id", $VoiceId,
            "--model", $Model,
            "--out-dir", $Stage2Data,
            "--sentences-file", $Stage2Corpus,
            "--stability", "0.45",
            "--similarity", "0.88",
            "--style", "0.74",
            "--val-fraction", "0.10"
        )
        if ($Resume) { $stage2Args += "--resume" }
        Invoke-Checked "stage2_dataset" $PythonExe $stage2Args $HERE

        Save-State "stage2_train" "running" "training emotional contour phase"
        Write-Log "Stage 2B: Training emotional contour phase"
        $stage2TrainList = Join-Path $Stage2Data "train_list.txt"
        $stage2ValList = Join-Path $Stage2Data "val_list.txt"
        if (-not (Test-Path $stage2TrainList) -or -not (Test-Path $stage2ValList)) {
            throw "Stage 2 filelists missing after dataset generation"
        }

        Build-Config -TemplatePath $TemplateConfig -OutputPath $Stage2Cfg `
            -TrainList $stage2TrainList -ValList $stage2ValList `
            -CheckpointPath $stage1Checkpoint -Epochs $Stage2Epochs `
            -LR 5.0e-6 -BertLR 5.0e-7 -FtLR 5.0e-6

        $trainArgs2 = @("train_finetune_accelerate.py", "--config_path", $Stage2Cfg)
        Invoke-Checked "stage2_train" $PythonExe $trainArgs2 $Repo
    }

    $finalCheckpoint = Get-LatestCheckpoint $LogDir
    if (-not $finalCheckpoint) {
        throw "Training finished but no final checkpoint was detected"
    }

    Save-State "complete" "ok" $finalCheckpoint
    Write-Log "=== Pipeline complete. Final checkpoint: $finalCheckpoint ==="
}
catch {
    Save-State "failed" "error" $_.Exception.Message
    Write-Log "FATAL: $($_.Exception.Message)"
    Write-Log "Pipeline aborted. Check logs: $RunLog"
    exit 1
}
