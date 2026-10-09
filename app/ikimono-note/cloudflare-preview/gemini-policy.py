"""Generate JS data from the existing authoritative Python constants/assets."""
import ast
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent


def literals(filename):
    values = {}
    for node in ast.parse((APP / filename).read_text()).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                values[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    return values


def build():
    vision = literals('vision.py')
    quality = literals('image_quality.py')
    messages = {}
    tree = ast.parse((APP / 'image_quality.py').read_text())
    judge = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'judge_measured')
    for node in ast.walk(judge):
        if isinstance(node, ast.Dict) and len(node.keys) == 3:
            fields = {ast.literal_eval(key): (quality[value.id] if isinstance(value, ast.Name) else ast.literal_eval(value))
                      for key, value in zip(node.keys, node.values)}
            if set(fields) == {'level', 'reason', 'message'}:
                messages[fields['reason'] + ':' + fields['level']] = fields
    data = {
        'prompt': vision['PROMPT'], 'review': vision['GEMINI_REVIEW'],
        'schema': vision['GEMINI_RESPONSE_SCHEMA'],
        'models': [item['id'] for item in literals('config_store.py')['MODELS']['gemini']],
        'quality': {key: value for key, value in quality.items() if key.startswith('MIN_')},
        'messages': messages,
        'protected': json.loads((APP / 'data/protected_species.json').read_text()),
        'taxonomy_url': vision['INATURALIST_URL'], 'taxonomy_agent': vision['INATURALIST_USER_AGENT'],
        'no_japanese_name': vision['NO_JAPANESE_NAME'],
    }
    assignments = {node.targets[0].id: node.value for node in ast.parse((APP / 'vision.py').read_text()).body
                   if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)}
    data['max_output_tokens'] = int(ast.literal_eval(assignments['GEMINI_MAX_OUTPUT_TOKENS'].args[0].args[1]))
    data['thinking_level'] = ast.literal_eval(assignments['GEMINI_THINKING_LEVEL'].args[1])
    (HERE / '_gemini_policy.mjs').write_text('export default ' + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n')


if __name__ == '__main__':
    build()
