# ── Blob Lifecycle Management ─────────────────────────────────────────────────
# Auto-deletes old blobs in the outputs and delta containers.
# Configured via output_blob_retention_days and delta_blob_retention_days variables.

resource "azurerm_storage_management_policy" "main" {
  storage_account_id = azurerm_storage_account.main.id

  # ── Rule 1: delete generated .docx files from outputs/ ─────────────────────
  # Optimized resumes are ephemeral: the user downloads once and they have no
  # further value.  30-day default gives ample download window.

  rule {
    name    = "delete-old-outputs"
    enabled = true

    filters {
      blob_types   = ["blockBlob"]
      prefix_match = ["outputs/"]
    }

    actions {
      base_blob {
        delete_after_days_since_modification_greater_than = var.output_blob_retention_days
      }
    }
  }

  # ── Rule 2: safety-net cleanup for Delta Lake data partitions ───────────────
  # Targets only the Hive-style partition directories (year=...) inside each
  # Delta table.  The _delta_log/ directories are intentionally excluded by
  # using the partition-prefix pattern — deleting the commit log would corrupt
  # the table and must never happen.
  #
  # Primary cleanup path: delta/writer.py vacuum_old_matches() runs in-process
  # and removes files that the Delta protocol has already superseded.  This rule
  # is a last-resort backstop for partitions that vacuum missed (e.g. if the
  # app was never run against a very old partition).
  #
  # NOTE: if you add a new Delta table to the delta container, add its
  # year= prefix here so old partitions are included in the safety net.

  rule {
    name    = "delete-old-delta-partitions"
    enabled = true

    filters {
      blob_types = ["blockBlob"]
      prefix_match = [
        "delta/daily_usage/year=",
        "delta/job_matches/year=",
      ]
    }

    actions {
      base_blob {
        delete_after_days_since_modification_greater_than = var.delta_blob_retention_days
      }
    }
  }

  # ── Not covered (future work) ───────────────────────────────────────────────
  # uploads/  — raw uploaded resumes; adding a short-retention rule (e.g. 7 days)
  #             is safe once the pipeline no longer reads from the blob path after
  #             the job completes.  Skipped here until the app migrates file
  #             storage from local disk to Blob (see application backlog).
}
