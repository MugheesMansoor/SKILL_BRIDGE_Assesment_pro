"""Local KB loader + version-aware TF-IDF retriever."""
import re
from pathlib import Path
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

KB_DIR = Path(__file__).resolve().parents[1] / "kb"


def _meta(text, key):
    m = re.search(rf"^{key}: (.+)$", text, re.M)
    return m.group(1).strip() if m else ""


class KB:
    def __init__(self, kb_dir=KB_DIR):
        self.chunks = []
        for p in sorted(Path(kb_dir).glob("KB-*.md")):
            text = p.read_text(encoding="utf-8")
            did, ver, status = _meta(text, "Document ID"), _meta(text, "Version"), _meta(text, "Status")
            for part in re.split(r"\n(?=## )", text):
                head = part.strip().splitlines()[0] if part.strip() else ""
                self.chunks.append({"id": did, "version": ver, "status": status, "section": head,
                                    "cite": f"{did} {ver}", "superseded": status.upper().startswith("SUPERSEDED"),
                                    "text": part.strip()})
        self.vec = TfidfVectorizer(stop_words="english")
        self.mat = self.vec.fit_transform([f'{c["section"]} {c["text"]}' for c in self.chunks])

    def retrieve(self, query, mode="decision", k=4):
        """mode='decision' drops SUPERSEDED docs; mode='explain' keeps them (labelled)."""
        sims = cosine_similarity(self.vec.transform([query]), self.mat)[0]
        ranked = sorted(zip(sims, self.chunks), key=lambda x: -x[0])
        out = [dict(c, score=float(s)) for s, c in ranked
               if s > 0 and (mode == "explain" or not c["superseded"])]
        return out[:k]
