param(
    [ValidateSet("Add", "Remove")]
    [string]$Action = "Add",
    [string]$ModelRoot = "E:\Project\ComfyUI\models",
    [string]$StateRoot = "E:\StoryRailModelProviders"
)

$ErrorActionPreference = "Stop"
$RecordPath = Join-Path $StateRoot "managed-h3-defender-exclusions.json"
$AllowedPaths = @(
    (Join-Path $ModelRoot "diffusion_models\minimax-h3\DasiwaMinimaxH3_dasiwaHybridV2_int8.safetensors"),
    (Join-Path $ModelRoot "diffusion_models\minimax-h3\DasiwaMinimaxH3_dasiwaHybridTurboV2_int8.safetensors"),
    (Join-Path $ModelRoot "text_encoders\qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"),
    (Join-Path $ModelRoot "vae\minimax-h3\minimax_h3_video_vae_fp16.safetensors"),
    (Join-Path $ModelRoot "vae\minimax-h3\minimax_h3_audio_vae_fp32.safetensors"),
    (Join-Path $ModelRoot "latent_upscale_models\minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors")
)
# Weights no longer used by the fixed graph: only revoked if this script added them earlier.
$RetiredPaths = @(
    (Join-Path $ModelRoot "diffusion_models\minimax-h3\minimax_h3_fl2va_pruned_int8_convrot.safetensors"),
    (Join-Path $ModelRoot "diffusion_models\minimax-h3\diffusion_models\minimax_h3_ref2va_pruned_fp8_scaled.safetensors")
)
$AllowedByKey = @{}
foreach ($Path in $AllowedPaths) {
    $AllowedByKey[$Path.ToLowerInvariant()] = $Path
}
$RetiredByKey = @{}
foreach ($Path in $RetiredPaths) {
    $RetiredByKey[$Path.ToLowerInvariant()] = $Path
}

if ($Action -eq "Add") {
    foreach ($Path in $AllowedPaths) {
        if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
            throw "H3 Defender exclusion preflight failed; missing fixed weight: $Path"
        }
    }
    New-Item -ItemType Directory -Path $StateRoot -Force | Out-Null
    $PreviouslyManaged = @()
    if (Test-Path -LiteralPath $RecordPath -PathType Leaf) {
        $Recorded = @(Get-Content -LiteralPath $RecordPath -Raw | ConvertFrom-Json)
        $PreviouslyManaged = @(
            $Recorded | Where-Object { $_ -is [string] -and $AllowedByKey.ContainsKey($_.ToLowerInvariant()) }
        )
        $Retired = @(
            $Recorded | Where-Object { $_ -is [string] -and $RetiredByKey.ContainsKey($_.ToLowerInvariant()) }
        )
        if ($Retired.Count -gt 0) {
            Remove-MpPreference -ExclusionPath $Retired
        }
    }
    $Current = @((Get-MpPreference).ExclusionPath)
    $CurrentByKey = @{}
    foreach ($Path in $Current) {
        if ($Path) { $CurrentByKey[$Path.ToLowerInvariant()] = $true }
    }
    $Added = @($AllowedPaths | Where-Object { -not $CurrentByKey.ContainsKey($_.ToLowerInvariant()) })
    if ($Added.Count -gt 0) {
        Add-MpPreference -ExclusionPath $Added
    }
    $Managed = @($PreviouslyManaged + $Added | Sort-Object -Unique)
    [System.IO.File]::WriteAllText(
        $RecordPath,
        (ConvertTo-Json -InputObject @($Managed)),
        [System.Text.UTF8Encoding]::new($false)
    )
    Write-Output "Configured $($AllowedPaths.Count) exact H3 weight exclusions; added $($Added.Count)."
    return
}

if (-not (Test-Path -LiteralPath $RecordPath -PathType Leaf)) {
    Write-Output "No StoryRail-managed H3 Defender exclusions were recorded."
    return
}
$Managed = @(
    Get-Content -LiteralPath $RecordPath -Raw |
        ConvertFrom-Json |
        Where-Object {
            $_ -is [string] -and (
                $AllowedByKey.ContainsKey($_.ToLowerInvariant()) -or
                $RetiredByKey.ContainsKey($_.ToLowerInvariant())
            )
        }
)
if ($Managed.Count -gt 0) {
    Remove-MpPreference -ExclusionPath $Managed
}
Remove-Item -LiteralPath $RecordPath -Force
Write-Output "Removed $($Managed.Count) StoryRail-managed H3 weight exclusions."
