"""Offline passage-recall baseline; synthetic fixtures, no network or LLM calls."""
import json
from app.research_depth import select_passages


def benchmark():
    results = []
    for topic, quote in [
        ('widget cost', 'Synthetic widget cost was 10 USD in 2024.'),
        ('sensor accuracy', 'Synthetic sensor accuracy was 42 percent in 2024.'),
        ('trial sample limitations', 'Synthetic trial sample included 30 participants; limitations were one laboratory.'),
        ('battery capacity', 'Synthetic battery capacity was 12 units in 2024.')]:
        for distance in (12000, 90000):
            content = ('Unrelated background material. ' * (distance // 25)) + quote
            selected = select_passages(content, topic, 5000, numerical=True)
            results.append({'topic': topic, 'offset': content.index(quote), 'prefix_baseline_found': quote in content[:5000],
                            'ranked_passages_found': quote in selected, 'context_characters': len(selected)})
    return {'kind': 'synthetic document passage recall; not real-world factual accuracy', 'cases': results,
            'baseline_hits': sum(case['prefix_baseline_found'] for case in results),
            'ranked_hits': sum(case['ranked_passages_found'] for case in results), 'total': len(results)}

if __name__ == '__main__':
    print(json.dumps(benchmark(), indent=2))
