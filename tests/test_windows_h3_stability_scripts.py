from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "default_model_providers_implement" / "windows"


class WindowsH3StabilityScriptTests(unittest.TestCase):
    def test_runtime_caps_only_h3_worker_cpu_threads(self) -> None:
        run_server = (WINDOWS / "run_server.ps1").read_text(encoding="utf-8")
        self.assertIn('$env:STORYRAIL_H3_CPU_THREADS = "4"', run_server)

    def test_windows_scripts_are_ascii_only(self) -> None:
        """PowerShell 5.1 会把无 BOM 的 .ps1 当 ANSI 读；非 ASCII 注释会直接破坏语法。"""

        for script in sorted(WINDOWS.glob("*.ps1")):
            raw = script.read_bytes()
            offenders = sorted({byte for byte in raw if byte > 0x7F})
            self.assertEqual(offenders, [], f"{script.name} 含非 ASCII 字节 {offenders}")

    def test_stop_services_preempts_failure_restart_and_verifies_shutdown(self) -> None:
        """真机验收发现：先停任务再杀进程会被失败重启策略立刻拉起，且孤儿 python 仍占端口。"""

        script = (WINDOWS / "stop_services.ps1").read_text(encoding="utf-8")
        # 结束进程之后必须再停一次任务，压掉已排队的失败重启。
        self.assertEqual(script.count("Stop-StoryRailTasks"), 3)
        # pid 文件可能缺失或过期，必须再按固定命令行精确匹配孤儿进程。
        self.assertIn("default_model_providers_implement.server", script)
        self.assertIn("Stop-OrphanedServer", script)
        # 退出前必须确认进程与端口都释放，否则直接失败而不是静默留下 GPU 服务。
        self.assertIn("Get-NetTCPConnection -State Listen -LocalPort $ListenPort", script)
        self.assertIn("is still running", script)

    def test_defender_exclusions_are_exact_weights_and_reversible(self) -> None:
        script = (WINDOWS / "configure_h3_defender_exclusions.ps1").read_text(encoding="utf-8")
        allowed = script[script.index("$AllowedPaths") : script.index("$RetiredPaths")]
        retired = script[script.index("$RetiredPaths") : script.index("$AllowedByKey")]
        self.assertEqual(allowed.count('.safetensors")'), 6)
        self.assertIn("DasiwaMinimaxH3_dasiwaHybridTurboV2_int8", allowed)
        self.assertIn("minimax_h3_latent_upscaler_3d_conv_v1_fp16", allowed)
        # Old weights are only revoked when this script added them, never re-added.
        self.assertEqual(retired.count('.safetensors")'), 2)
        self.assertIn("Remove-MpPreference -ExclusionPath $Retired", script)
        self.assertIn("Add-MpPreference -ExclusionPath $Added", script)
        self.assertIn("Remove-MpPreference -ExclusionPath $Managed", script)
        self.assertIn("$AllowedByKey.ContainsKey", script)
        self.assertNotIn("Add-MpPreference -ExclusionPath $ModelRoot", script)


if __name__ == "__main__":
    unittest.main()
