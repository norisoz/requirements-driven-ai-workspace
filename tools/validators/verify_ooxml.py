#!/usr/bin/env python3
"""Verify structural integrity of OOXML files (.pptx, .docx, .xlsx) using Python stdlib only.

Checks:
1. ZIP archive integrity (ZipFile.testzip)
2. Well-formed XML syntax for all .xml and .rels entries
3. Existence of all internal relationship targets in *.rels
4. PowerPoint (.pptx) specific structural invariants:
   - notesMaster relationship in ppt/_rels/presentation.xml.rels must match
     notesMasterIdLst in ppt/presentation.xml
   - Slide size (p:sldSz) must not retain type="screen4x3" on 16:9 widescreen dimensions
     and should not have near-standard EMU rounding drift (e.g. 12191695 vs 12192000)
"""
import argparse
import json
import posixpath
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

WIDESCREEN_16_9_CX = 12192000  # 13.333... inches (exact EMU)
WIDESCREEN_16_9_CY = 6858000   # 7.5 inches (exact EMU)


def _resolve_target(rels_path: str, target: str) -> str:
    """Resolve a relationship Target path relative to its owning part."""
    if target.startswith('/'):
        return target.lstrip('/')
    # For _rels/.rels -> base dir is ''
    # For ppt/_rels/presentation.xml.rels -> base dir is 'ppt'
    rels_dir = posixpath.dirname(rels_path)
    if rels_dir.endswith('/_rels'):
        part_dir = rels_dir[:-6]
    elif rels_dir == '_rels':
        part_dir = ''
    else:
        part_dir = rels_dir
    combined = posixpath.join(part_dir, target) if part_dir else target
    return posixpath.normpath(combined)


def verify_ooxml(file_path: Path) -> dict[str, Any]:
    findings: list[dict[str, str]] = []

    def add(code: str, message: str, severity: str = 'ERROR') -> None:
        findings.append({'code': code, 'severity': severity, 'message': message})

    if not file_path.exists():
        add('FILE_NOT_FOUND', f'File does not exist: {file_path}')
        return {'file': str(file_path), 'valid': False, 'findings': findings}

    try:
        zf = zipfile.ZipFile(file_path, 'r')
    except zipfile.BadZipFile as exc:
        add('INVALID_ZIP', f'Not a valid ZIP/OOXML archive: {exc}')
        return {'file': str(file_path), 'valid': False, 'findings': findings}

    with zf:
        # 1. ZIP integrity
        bad_member = zf.testzip()
        if bad_member is not None:
            add('CORRUPT_ZIP_ENTRY', f'Corrupt ZIP entry detected: {bad_member}')

        names = set(zf.namelist())
        parsed_xml: dict[str, ET.Element] = {}

        # 2. Parse all .xml and .rels files
        for name in sorted(names):
            if not (name.endswith('.xml') or name.endswith('.rels')):
                continue
            try:
                raw = zf.read(name)
                parsed_xml[name] = ET.fromstring(raw)
            except Exception as exc:
                add('INVALID_XML', f'{name}: XML parse error ({exc})')

        # 3. Validate all internal relationship targets
        for name, root in parsed_xml.items():
            if not name.endswith('.rels'):
                continue
            for rel in root:
                if not rel.tag.endswith('Relationship'):
                    continue
                if rel.attrib.get('TargetMode') == 'External':
                    continue
                target = rel.attrib.get('Target', '')
                if not target or target.startswith('#'):
                    continue
                resolved = _resolve_target(name, target)
                if resolved not in names:
                    add(
                        'BROKEN_RELATIONSHIP',
                        f'{name} references missing target "{target}" (resolved: "{resolved}")',
                    )

        # 4. PPTX-specific checks
        is_pptx = file_path.suffix.lower() == '.pptx' or 'ppt/presentation.xml' in names
        if is_pptx:
            pres_xml = parsed_xml.get('ppt/presentation.xml')
            pres_rels = parsed_xml.get('ppt/_rels/presentation.xml.rels')

            if pres_xml is None:
                add('MISSING_PRESENTATION_XML', 'ppt/presentation.xml is missing or invalid')
            if pres_rels is not None and pres_xml is not None:
                has_notes_master_rel = any(
                    'notesMaster' in (rel.attrib.get('Type', '') + rel.attrib.get('Target', ''))
                    for rel in pres_rels
                    if rel.tag.endswith('Relationship')
                )
                has_notes_master_lst = any(
                    el.tag.endswith('notesMasterIdLst') for el in pres_xml.iter()
                )
                if has_notes_master_rel and not has_notes_master_lst:
                    add(
                        'PPTX_NOTES_MASTER_MISMATCH',
                        'ppt/_rels/presentation.xml.rels references notesMaster, but ppt/presentation.xml lacks notesMasterIdLst',
                    )
                if has_notes_master_lst and not has_notes_master_rel:
                    add(
                        'PPTX_NOTES_MASTER_MISMATCH',
                        'ppt/presentation.xml declares notesMasterIdLst, but ppt/_rels/presentation.xml.rels lacks notesMaster relationship',
                    )

            if pres_xml is not None:
                for el in pres_xml.iter():
                    if not el.tag.endswith('sldSz'):
                        continue
                    cx_str = el.attrib.get('cx')
                    cy_str = el.attrib.get('cy')
                    sz_type = el.attrib.get('type')
                    if cx_str and cy_str and cx_str.isdigit() and cy_str.isdigit():
                        cx = int(cx_str)
                        cy = int(cy_str)
                        ratio = cx / cy if cy else 0.0
                        # Detect stale screen4x3 attribute on widescreen (~16:9) dimensions
                        if sz_type == 'screen4x3' and ratio > 1.55:
                            add(
                                'PPTX_STALE_SLIDE_SIZE_TYPE',
                                f'p:sldSz has widescreen dimensions (cx={cx}, cy={cy}) but retains stale type="screen4x3"',
                            )
                        # Detect near-16:9 EMU rounding drift (e.g., 12191695 vs 12192000)
                        if 0 < abs(cx - WIDESCREEN_16_9_CX) <= 5000:
                            add(
                                'PPTX_SLIDE_SIZE_EMU_DRIFT',
                                f'p:sldSz cx={cx} has rounding drift from standard 16:9 EMU ({WIDESCREEN_16_9_CX})',
                            )
                        if 0 < abs(cy - WIDESCREEN_16_9_CY) <= 5000:
                            add(
                                'PPTX_SLIDE_SIZE_EMU_DRIFT',
                                f'p:sldSz cy={cy} has rounding drift from standard 16:9 EMU ({WIDESCREEN_16_9_CY})',
                            )

    error_count = sum(1 for f in findings if f.get('severity') == 'ERROR')
    return {
        'file': str(file_path),
        'valid': error_count == 0,
        'error_count': error_count,
        'findings': findings,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Verify structural integrity of OOXML (.pptx/.docx/.xlsx) files')
    parser.add_argument('--file', required=True, type=Path, help='Path to .pptx / .docx / .xlsx file')
    args = parser.parse_args()
    result = verify_ooxml(args.file)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result['valid']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
