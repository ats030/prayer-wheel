"""Aggregate experiment measurements; never retain source text or credentials."""
import threading


class MaterialMetrics:
    def __init__(self, timeline):
        self.lock = threading.Lock()
        self.counts = {}
        fetch = timeline.fetch_sources
        batches = timeline.material_batches

        def measured_fetch(*args, **kwargs):
            sources = fetch(*args, **kwargs)
            passages = [p for s in sources for p in s.get("passages", [])]
            with self.lock:
                self.counts.update(sources_fetched=len(sources), passages_fetched=len(passages),
                    dated_passages_fetched=sum(bool(timeline.DATE_PATTERN.search(
                        p.get("text", "") + " " + p.get("date_heading", ""))) for p in passages))
            return sources

        def measured_batches(*args, **kwargs):
            for batch in batches(*args, **kwargs):
                with self.lock:
                    self.counts["batches_total"] = self.counts.get("batches_total", 0) + 1
                    self.counts["passage_appearances_in_batches"] = self.counts.get(
                        "passage_appearances_in_batches", 0) + sum(len(s.get("passages", [])) for s in batch)
                yield batch

        timeline.fetch_sources = measured_fetch
        timeline.material_batches = measured_batches

    def summary(self):
        with self.lock:
            return dict(self.counts)
