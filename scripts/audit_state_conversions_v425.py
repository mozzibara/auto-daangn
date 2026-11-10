# -*- coding: utf-8 -*-
"""v4.25 repository-wide offline audit of direct JSON-LD -> SOLD mappings.

v4.26 requires ZERO direct OutOfStock/SoldOut-to-marketplace-SOLD mappings.
It also enforces canonical-only source, detail, and control decision paths.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DIRECT_MAPPING = re.compile(
    r"""(?:OutOfStock[\s\S]{0,160}SoldOut|SoldOut[\s\S]{0,160}OutOfStock)[\s\S]{0,180}['"]SOLD['"]"""
)



def source_paths(root):
    """Scan production Python and embedded browser JS, never caches or test fixtures."""
    return sorted(p for p in root.rglob('*.py') if not any(
        bit in {'.git', '.venv', 'venv', '__pycache__', 'tests'} for bit in
        p.relative_to(root).parts))


def find_direct_mappings(root):
    results = {}
    for path in source_paths(root):
        # Skip only this auditor's own illustrative regex/allowlist literals;
        # production files are scanned, including their embedded browser JS.
        if path.relative_to(root).as_posix() == 'scripts/audit_state_conversions_v425.py':
            continue
        content = path.read_text(encoding='utf-8')
        matches = list(DIRECT_MAPPING.finditer(content))
        if matches:
            results[path.relative_to(root).as_posix()] = [
                content.count('\n', 0, m.start()) + 1 for m in matches]
    return results


def audit_repository(root=ROOT):
    root = Path(root)
    found = find_direct_mappings(root)
    violations = [path + ': FORBIDDEN_STOCK_TO_TRANSACTION_CONVERSION'
                  for path in sorted(found)]
    consumer = root/'daangn_state_consumers_v4_25.py'
    code = consumer.read_text(encoding='utf-8') if consumer.is_file() else ''
    if ('from daangn_listing_state_v4_24 import clean_record' not in code
        or re.search(r'import daangn_(?:sale_sources_v4_21|state_controls_v4_23)', code)):
        violations.append('CANONICAL_CONSUMER_DEPENDENCY_INVALID')
    required={
        'daangn_detail_crosscheck_v4_20.py':(
            'from daangn_state_consumers_v4_25 import consume',
            'entry[\'detail_verdict\']=classify_detail(observed,identity,entry[\'v424_state_model\'])'),
        'daangn_sale_sources_v4_21.py':(
            'from daangn_state_consumers_v4_25 import',
            'return source_comparison(canonical_record)',
            'options.state_model_v424=True'),
        'daangn_state_controls_v4_23.py':(
            'from daangn_state_consumers_v4_25 import',
            'return control_comparison(canonical_record)',
            'options.state_model_v424=True'),
    }
    for path, markers in required.items():
        source=(root/path).read_text(encoding='utf-8') if (root/path).is_file() else ''
        for marker in markers:
            if marker not in source:
                violations.append(path + ': MISSING_CANONICAL_ONLY_WIRING')
    detail=(root/'daangn_detail_crosscheck_v4_20.py').read_text(encoding='utf-8')
    sources=(root/'daangn_sale_sources_v4_21.py').read_text(encoding='utf-8')
    controls=(root/'daangn_state_controls_v4_23.py').read_text(encoding='utf-8')
    if re.search(r"""saleClaims\.push\(\{type:['"](?:SOLD|AVAILABLE|RESERVED)['"],source:['"]MATCHED_PRODUCT_JSONLD""", detail):
        violations.append('v4.20: JSONLD_MARKETPLACE_STATUS_MAPPING_PRESENT')
    if 'result.jsonld.state=' in sources or 'values.push(\'SOLD\')' in sources:
        violations.append('v4.21: COARSE_JSONLD_STATUS_MAPPING_PRESENT')
    if "jsonld_state in ('AVAILABLE','SOLD','RESERVED')" in controls:
        violations.append('v4.23: LEGACY_COARSE_FALLBACK_PRESENT')
    return {
        'status': 'PASS' if not violations else 'FAIL',
        'production_python_files_scanned': len(source_paths(root)),
        'direct_stock_to_sold_sites': found,
        'expected_direct_conversion_sites': 0,
        'violations': sorted(violations),
        'canonical_status_is_independent_of_jsonld': not violations,
        'strict_listing_approved_count': 0,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, default=ROOT)
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    result = audit_repository(args.root)
    text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
    print(text)
    return 0 if result['status'] == 'PASS' else 2


if __name__ == '__main__':
    raise SystemExit(main())
