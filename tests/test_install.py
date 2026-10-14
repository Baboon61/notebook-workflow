"""Global discovery installation in an isolated user directory."""

import importlib.util
from pathlib import Path
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

import pytest
import yaml


BUNDLE = Path(__file__).resolve().parents[1]


def installer():
    spec = importlib.util.spec_from_file_location("workflow_installer", BUNDLE / "install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_installer_links_canonical_skill_and_agents_idempotently(tmp_path):
    module = installer()
    user = tmp_path / "user"
    codex = tmp_path / "custom-codex"
    result = module.install(user, codex, skip_environment=True)
    again = module.install(user, codex, skip_environment=True)
    assert again == result
    for path in result["links"]:
        assert Path(path).is_symlink()
        assert Path(path).exists()
    skill = user / ".agents/skills/notebook-refactor"
    assert (skill / "SKILL.md").exists()
    assert (skill / "references/workflow.md").exists()
    assert (skill / "scripts/workflow.py").exists()
    assert not (codex / "config.toml").exists()


def test_installer_preflights_conflicting_user_files(tmp_path):
    module = installer()
    user = tmp_path / "user"
    codex = user / ".codex"
    conflict = codex / "agents/notebook-refactorer.toml"
    conflict.parent.mkdir(parents=True)
    conflict.write_text("User-owned agent")
    with pytest.raises(ValueError, match="something else"):
        module.install(user, codex, skip_environment=True)
    assert conflict.read_text() == "User-owned agent"
    assert not (user / ".agents/skills/notebook-refactor").exists()


def test_agent_files_follow_current_codex_schema():
    for path in (BUNDLE / "agents").glob("*.toml"):
        agent = tomllib.loads(path.read_text())
        assert all(agent.get(key) for key in ("name", "description", "developer_instructions"))
        assert "instructions" not in agent
        assert "model" not in agent and "model_reasoning_effort" not in agent


def test_skill_metadata_and_reference_links():
    skill = BUNDLE / "skills/notebook-refactor"
    frontmatter = yaml.safe_load((skill / "SKILL.md").read_text().split("---", 2)[1])
    assert frontmatter["name"] == "notebook-refactor"
    interface = yaml.safe_load((skill / "agents/openai.yaml").read_text())
    assert "$notebook-refactor" in interface["interface"]["default_prompt"]
    assert interface["policy"]["allow_implicit_invocation"] is True
