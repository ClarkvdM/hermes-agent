"""TEMPORARY CI shim for the PR #106742 native proof (never merges).

Runs one leg of the native Windows/macOS proof through the canonical runner
(scripts/run_tests.sh) with captured output, so a wide log cannot wedge the
runner log pipeline. Writes every log into ``$W2E_ARTIFACT_DIR`` and prints ONE
``RESULT <os>/<leg>: exit=N passed=X failed=Y`` line (plus the failing node ids).

Legs:
  marked   files under the merge-touched dirs carrying a platforms() gate for
           this host, run with ``-m "platforms and not integration"`` (tests-os parity)
  touched  every test in the files the main merge / wave-2 lanes touched plus the
           native live suites (default addopts); on Windows also the footgun checker
"""
import os
from pathlib import Path
import re
import subprocess
import sys

DIRS = ("tests/gateway/", "tests/hermes_cli/", "tests/acp_adapter/", "tests/tui_gateway/", "tests/cron/")

TOUCHED = """
tests/acp_adapter/test_acp_image_staging_boundary.py
tests/agent/test_bot_chat_toolset_refresh.py
tests/agent/test_kanban_turn_recovery.py
tests/cron/test_context_from_response_extraction.py
tests/cron/test_cron_bot_chat_delivery.py
tests/cron/test_cron_delivery_redaction.py
tests/cron/test_cron_execution_identity.py
tests/cron/test_cron_script.py
tests/cron/test_cron_windows_venv_abi.py
tests/cron/test_unreachable_retry.py
tests/gateway/test_api_crash_recovery.py
tests/gateway/test_api_media_admission_bounds.py
tests/gateway/test_api_pending_daemon.py
tests/gateway/test_authority_events.py
tests/gateway/test_bot_receipt_corruption.py
tests/gateway/test_control_socket.py
tests/gateway/test_control_socket_pause.py
tests/gateway/test_control_socket_peer_security.py
tests/gateway/test_control_socket_windows_live.py
tests/gateway/test_gateway_api_token_exposure.py
tests/gateway/test_managed_worker_bypass.py
tests/gateway/test_managed_worker_env_boundary.py
tests/gateway/test_managed_worker_fencing.py
tests/gateway/test_managed_worker_images.py
tests/gateway/test_managed_worker_launch.py
tests/gateway/test_managed_worker_lineage.py
tests/gateway/test_managed_worker_profile_env.py
tests/gateway/test_managed_worker_retire.py
tests/gateway/test_managed_worker_stop_before_hello.py
tests/gateway/test_managed_worker_trampoline.py
tests/gateway/test_managed_worker_turn_author.py
tests/gateway/test_multiplex_hot_serve_live.py
tests/gateway/test_native_http_auth.py
tests/gateway/test_plugin_message_injection.py
tests/gateway/test_post_gateway_admission.py
tests/gateway/test_prompt_attachments.py
tests/gateway/test_proxy_mode.py
tests/gateway/test_runtime_bootstrap.py
tests/gateway/test_session_a2a.py
tests/gateway/test_session_bot_retry.py
tests/gateway/test_session_kanban.py
tests/gateway/test_session_kanban_turn_recovery.py
tests/gateway/test_session_local_reopen_on_turn.py
tests/gateway/test_session_mutation_compress_preview.py
tests/gateway/test_session_mutation_retirement.py
tests/gateway/test_session_mutation_rpc.py
tests/gateway/test_session_policy.py
tests/gateway/test_unified_gateway_native_live.py
tests/gateway/test_used_delete_restart.py
tests/gateway/test_webhook_replay_scope.py
tests/gateway/test_wine2e_ticket_bridge_tmp.py
tests/gateway/test_yolo_command.py
tests/hermes_cli/test_corelane_frozen_worker_skill_env.py
tests/hermes_cli/test_gateway_runtime_discovery.py
tests/hermes_cli/test_gateway_runtime_ensure.py
tests/hermes_cli/test_gateway_runtime_home_identity.py
tests/hermes_cli/test_kanban_db.py
tests/hermes_cli/test_kanban_worker_exit_decode.py
tests/hermes_cli/test_kanban_worker_exit_trailer.py
tests/hermes_cli/test_kanban_worker_image_extraction.py
tests/hermes_cli/test_kanban_worker_lifecycle_hooks.py
tests/hermes_cli/test_kanban_worker_pid_fingerprint.py
tests/hermes_cli/test_kanban_worker_session_source.py
tests/hermes_cli/test_kanban_worker_spawn_toolsets.py
tests/hermes_cli/test_kanban_worker_terminal_cwd.py
tests/hermes_cli/test_kanban_worker_terminal_scope.py
tests/hermes_cli/test_keyed_provider_credential_pool.py
tests/hermes_cli/test_main_merge_lifecycle.py
tests/hermes_cli/test_native_profile_scope_threads.py
tests/hermes_cli/test_pty_keepalive_ws.py
tests/hermes_cli/test_runtime_provider_resolution.py
tests/hermes_cli/test_safe_mode.py
tests/hermes_cli/test_sessions_export_retention.py
tests/hermes_cli/test_web_routers_status_health.py
tests/hermes_cli/test_web_server.py
tests/hermes_cli/test_web_server_sessions_compression.py
tests/hermes_cli/test_web_server_session_search.py
tests/hermes_state/test_target_advance_fence.py
tests/scripts/test_footgun_encoding_direction.py
tests/scripts/test_footgun_subprocess_encoding.py
tests/tools/test_bot_mode_dm_entry.py
tests/tools/test_subprocess_utf8_encoding.py
tests/tui_gateway/test_compute_host.py
tests/tui_gateway/test_entry_home_ownership.py
tests/tui_gateway/test_file_attachment_allocation.py
tests/tui_gateway/test_gateway_bootstrap_control_home.py
tests/tui_gateway/test_subprocess_encoding.py
tests/tui_gateway/test_tui_gateway_ws.py
""".split()


def _bounded(cmd, log: Path, timeout: int, env=None) -> tuple[int, str]:
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=30)
        proc.kill()
        out, _ = proc.communicate(timeout=60)
        out += f"\nSHIM: timed out after {timeout}s\n".encode()
    text = out.decode("utf-8", "replace")
    log.write_text(text, encoding="utf-8")
    return proc.returncode if proc.returncode is not None else -1, text


def _say(text: str) -> None:
    sys.stdout.buffer.write((text + "\n").encode("utf-8", "replace"))
    sys.stdout.flush()


def main() -> int:
    host = "windows" if os.name == "nt" else ("macos" if sys.platform == "darwin" else "linux")
    leg = os.environ["W2E_LEG"]
    label = f"{os.environ.get('W2E_JOB', host)}/{leg}"
    logs = Path(os.environ.get("W2E_ARTIFACT_DIR", "w2e-logs"))
    logs.mkdir(parents=True, exist_ok=True)
    bash = "bash"
    if leg == "marked":
        listed = subprocess.run([sys.executable, "scripts/ci/list_os_marked_tests.py", host],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        files = [f.strip() for f in listed.stdout.splitlines() if f.strip().startswith(DIRS)]
        selector = ["-m", "platforms and not integration"]
    else:
        files = [f for f in TOUCHED if Path(f).is_file()]
        selector = []
    missing = [f for f in (TOUCHED if leg == "touched" else []) if not Path(f).is_file()]
    listing = logs / f"files-{leg}.txt"
    listing.write_text("\n".join(files) + "\n", encoding="utf-8")
    _say(f"SHIM {label}: {len(files)} files ({len(missing)} touched files absent on this tree)")
    cmd = [bash, "scripts/run_tests.sh", "--files-from", str(listing), "--", *selector, "-rfE", "--tb=short"]
    rc, text = _bounded(cmd, logs / f"pytest-{leg}.log", 3300)
    summary = re.findall(r"=== Summary: (\d+) files, (\d+) tests passed, (\d+) failed[^\n]*", text)
    passed = int(summary[-1][1]) if summary else 0
    failed = int(summary[-1][2]) if summary else 0
    failing = sorted(set(re.findall(r"^(?:\s*[║|]\s*)?(?:FAILED|ERROR) (tests/\S+)", text, re.M)))
    flaky = re.search(r"=== ⚠ \d+ FLAKY file.*?(?:\n\n|\Z)", text, re.S)
    crashed = re.findall(r"^\s*--- (tests/\S+) ---", text, re.M)
    extra = ""
    if leg == "touched" and host == "windows":
        frc, ftext = _bounded([sys.executable, "scripts/check-windows-footguns.py", "--all"], logs / "footguns.log", 600)
        _say(f"RESULT {os.environ.get('W2E_JOB', host)}/footguns: exit={frc}")
        _say(ftext[-3000:])
        extra = f" footguns_exit={frc}"
        rc = rc or frc
    _say(text[-8000:])
    _say(f"FAILING NODES ({len(failing)}):\n" + "\n".join(failing))
    _say("FAILED FILES:\n" + "\n".join(crashed))
    if flaky:
        _say(flaky.group(0)[:4000])
    _say(f"RESULT {label}: exit={rc} passed={passed} failed={failed}{extra}"
         f" summary={summary[-1][0] + ' files' if summary else 'MISSING'}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
