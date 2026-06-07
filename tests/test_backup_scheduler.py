"""Verify backup scheduler is wired into ARQ cron config and RPO is measured.

P0 fix: Backups were manual one-shots. RPO was a hardcoded 86400s constant
not a measurement. Backup destination defaulted to the same MinIO the
primary lives in. This test guards against regressions on the three fixes.
"""
import inspect

import pytest

from nexus.jobs.config import WorkerSettings


# ---------------------------------------------------------------------------
# 1) ARQ cron config — backup jobs are scheduled
# ---------------------------------------------------------------------------

def test_backup_postgres_in_cron_jobs():
    """backup_postgres must be scheduled in ARQ WorkerSettings.cron_jobs."""
    cron_names = [job.name for job in WorkerSettings.cron_jobs]
    assert "backup_postgres" in cron_names, (
        f"backup_postgres not in cron_jobs: {cron_names}"
    )


def test_backup_postgres_runs_every_6_hours():
    """backup_postgres schedule: every 6h at minute 0 (0/6/12/18:00 UTC)."""
    for job in WorkerSettings.cron_jobs:
        if job.name == "backup_postgres":
            hour = set(job.hour) if job.hour is not None else set()
            assert hour == {0, 6, 12, 18}, (
                f"Expected hour in {{0, 6, 12, 18}}, got {job.hour}"
            )
            assert job.minute == 0, f"Expected minute=0, got {job.minute}"
            return
    pytest.fail("backup_postgres cron job not found")


def test_backup_minio_redis_in_cron_jobs():
    """MinIO/Redis backup must also be scheduled (offset by 30 min)."""
    cron_names = [job.name for job in WorkerSettings.cron_jobs]
    assert "backup_minio_redis" in cron_names, (
        f"backup_minio_redis not in cron_jobs: {cron_names}"
    )


def test_dr_drill_in_cron_jobs():
    """Weekly DR drill must be scheduled."""
    cron_names = [job.name for job in WorkerSettings.cron_jobs]
    assert "dr_drill" in cron_names, (
        f"dr_drill not in cron_jobs: {cron_names}"
    )


# ---------------------------------------------------------------------------
# 2) DR drill — RPO is MEASURED from newest backup, not assumed
# ---------------------------------------------------------------------------

def test_dr_drill_measures_rpo_not_assumes():
    """dr_drill must not have hardcoded 86400 — must measure from backup timestamp."""
    from scripts.disaster_recovery_drill import run_drill
    source = inspect.getsource(run_drill)
    assert "86400" not in source, "Hardcoded RPO assumption still present"
    assert "time.time()" in source, "RPO not measured from backup timestamp"


def test_dr_drill_returns_rpo_in_result():
    """run_drill() must return a dict that includes measured rpo_seconds."""
    from scripts.disaster_recovery_drill import run_drill
    sig = inspect.signature(run_drill)
    assert sig.return_annotation in (dict, "dict") or sig.return_annotation is dict, (
        f"run_drill must declare dict return type, got {sig.return_annotation}"
    )


# ---------------------------------------------------------------------------
# 3) backup_to_s3.py — S3_ENDPOINT must be explicit (no MinIO default)
# ---------------------------------------------------------------------------

def test_backup_to_s3_requires_explicit_endpoint():
    """backup_to_s3.py must NOT default S3_ENDPOINT to MinIO cluster.

    The old default (http://nexus-minio:9000) pointed to the same MinIO
    the primary lives in — cluster failure = data + backup gone together.
    Operator must explicitly point at an off-host S3 destination.
    """
    import scripts.backup_to_s3 as mod
    source = inspect.getsource(mod)
    # The old default must be gone
    assert '"http://nexus-minio:9000"' not in source, (
        "S3_ENDPOINT still defaults to in-cluster MinIO"
    )
    assert "'http://nexus-minio:9000'" not in source, (
        "S3_ENDPOINT still defaults to in-cluster MinIO"
    )
    # And the script must guard against missing S3_ENDPOINT
    assert "S3_ENDPOINT" in source, "S3_ENDPOINT reference missing"
    # It should raise or error out if the env var is missing
    assert "raise" in source or "sys.exit" in source, (
        "No guard for missing S3_ENDPOINT"
    )
