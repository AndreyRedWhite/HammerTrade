from pathlib import Path

from scripts.configure_sandbox_fleet import update_env_file


def test_update_env_file_replaces_and_appends_without_touching_other_values(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SANDBOX_TOKEN=secret\nSANDBOX_ACCOUNT_ID_CARRY=old\n# KEEP=yes\n",
        encoding="utf-8",
    )

    backup = update_env_file(
        env_file,
        {
            "SANDBOX_ACCOUNT_ID_CARRY": "new",
            "SANDBOX_CARRY_ENABLED": "false",
        },
    )

    assert backup.read_text(encoding="utf-8").startswith("SANDBOX_TOKEN=secret")
    assert env_file.read_text(encoding="utf-8") == (
        "SANDBOX_TOKEN=secret\n"
        "SANDBOX_ACCOUNT_ID_CARRY=new\n"
        "# KEEP=yes\n\n"
        "SANDBOX_CARRY_ENABLED=false\n"
    )
