import json
from pathlib import Path


class TestTemplates:
    TEMPLATES_DIR = Path("nexus/templates")

    def test_all_templates_valid_json(self):
        """所有模板文件是有效 JSON."""
        for f in self.TEMPLATES_DIR.glob("*.json"):
            with open(f) as fp:
                data = json.load(fp)
            assert "name" in data
            assert "version" in data
            assert "type" in data

    def test_code_reviewer_template(self):
        """Code Reviewer 模板结构正确."""
        with open(self.TEMPLATES_DIR / "code_reviewer_v2.json") as f:
            tmpl = json.load(f)
        assert tmpl["type"] == "agent"
        assert "agent" in tmpl
        assert "workflow" in tmpl
        assert len(tmpl["workflow"]["nodes"]) == 5

    def test_data_analyst_template(self):
        """Data Analyst 模板结构正确."""
        with open(self.TEMPLATES_DIR / "data-analyst.json") as f:
            tmpl = json.load(f)
        assert tmpl["type"] == "agent"
        assert "read_file" in tmpl["agent"]["tools"]

    def test_customer_service_template(self):
        """Customer Service 模板结构正确."""
        with open(self.TEMPLATES_DIR / "customer_service.json") as f:
            tmpl = json.load(f)
        assert tmpl["type"] == "crew"
        assert "crew" in tmpl
        assert len(tmpl["crew"]["agents"]) == 4
        assert tmpl["crew"]["mode"] == "hierarchical"

    def test_list_templates(self):
        """list_templates 返回非空列表."""
        from nexus.templates import list_templates
        templates = list_templates()
        assert len(templates) >= 3

    def test_get_template(self):
        """get_template 返回正确的模板."""
        from nexus.templates import get_template
        tmpl = get_template("data-analyst")
        assert tmpl is not None
        assert tmpl["name"] == "data-analyst"

        missing = get_template("nonexistent")
        assert missing is None
