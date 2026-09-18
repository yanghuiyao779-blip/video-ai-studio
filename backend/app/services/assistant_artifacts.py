"""Validate display artifacts; never render model-provided HTML or SVG."""
from app.services.assistant_tools import parse_json_object


def structured_artifact(kind: str, content: str, evidence: list[dict]):
    if kind not in {"mindmap", "timeline"}:
        return content, None
    data = parse_json_object(content)
    if kind == "mindmap":
        counter = [0]
        def node(value, depth=0):
            counter[0] += 1
            if depth > 4 or counter[0] > 60 or not isinstance(value, dict):
                raise ValueError("Mind map depth/node limit exceeded")
            title = value.get("title")
            if not isinstance(title, str) or not title.strip() or len(title) > 240:
                raise ValueError("Invalid mind map title")
            children = value.get("children", [])
            if not isinstance(children, list) or len(children) > 12:
                raise ValueError("Invalid mind map children")
            return {"title": title.strip(), "children": [node(child, depth + 1) for child in children]}
        tree = node(data)
        def render(value, level=0):
            return "  " * level + "- " + value["title"] + "\n" + "".join(render(child, level+1) for child in value["children"])
        return render(tree), tree
    sources = {e["id"]: e for e in evidence if e.get("job_id") and "start_seconds" in e}
    values = data.get("chapters")
    if not isinstance(values, list) or not 1 <= len(values) <= 60:
        raise ValueError("Invalid timeline chapters")
    chapters = []
    for value in values:
        if not isinstance(value, dict) or value.get("source_id") not in sources:
            raise ValueError("Timeline references an unknown source")
        source = sources[value["source_id"]]
        title, summary = value.get("title"), value.get("summary", "")
        if not isinstance(title, str) or not 1 <= len(title) <= 240 or not isinstance(summary, str) or len(summary) > 2000:
            raise ValueError("Invalid timeline text")
        chapters.append({"title": title, "summary": summary, "source_id": source["id"],
            "job_id": source["job_id"], "start_seconds": source["start_seconds"], "end_seconds": source["end_seconds"]})
    chapters.sort(key=lambda x: (x["job_id"], x["start_seconds"]))
    text = "\n\n".join(f"### {int(c['start_seconds'])//60:02d}:{int(c['start_seconds'])%60:02d} {c['title']} [{c['source_id']}]\n{c['summary']}" for c in chapters)
    return text, {"chapters": chapters}
