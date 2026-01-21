#!/usr/bin/env python3
"""
Script to enlarge employees_data_modified.sql while maintaining referential integrity.
Duplicates employees along with all their related records (salary, title, department_employee).
This ensures foreign key constraints are satisfied.
"""

import re
import sys
from pathlib import Path
from collections import defaultdict

def parse_sql_file(input_file: str):
    """
    Parse PostgreSQL dump file and extract COPY sections with data.
    Returns dictionary with table names as keys and data as values.
    """
    print(f"Reading input file: {input_file}")
    input_path = Path(input_file)
    print(f"Input size: {input_path.stat().st_size / 1024 / 1024:.1f} MB")

    with open(input_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    print(f"Total lines: {len(lines)}")

    # Find COPY sections
    copy_sections = {}
    in_copy = False
    current_table = None
    current_data = []

    for i, line in enumerate(lines):
        # Start of COPY section
        if re.match(r'^COPY \w+.*FROM stdin;', line):
            # Save previous section if exists
            if current_table:
                copy_sections[current_table] = {
                    'header': current_header,
                    'data': list(current_data)
                }

            # Extract table name
            match = re.match(r'^COPY (\w+)', line)
            if match:
                current_table = match.group(1)
                current_header = line
                current_data = []
                in_copy = True

        # End of COPY section
        elif in_copy and line.strip() == '\\.':
            # Save current section
            if current_table:
                copy_sections[current_table] = {
                    'header': current_header,
                    'data': list(current_data)
                }
            current_table = None
            current_data = []
            in_copy = False

        # Data line
        elif in_copy:
            current_data.append(line)

    print(f"Found {len(copy_sections)} COPY sections")
    for table, section in copy_sections.items():
        data_rows = [l for l in section['data'] if l.strip() and l.strip() != '\\.']
        print(f"  {table}: {len(data_rows)} data rows")

    # Also get everything before the first COPY (header)
    first_copy_idx = None
    for i, line in enumerate(lines):
        if re.match(r'^COPY \w+.*FROM stdin;', line):
            first_copy_idx = i
            break

    header_lines = lines[:first_copy_idx] if first_copy_idx else []

    return header_lines, copy_sections, lines

def build_employee_lookup(salary_data, title_data, dept_emp_data):
    """
    Build lookup dictionaries mapping employee_id to their related records.
    """
    # employee_id -> list of (salary_record, original_id)
    salary_by_emp = defaultdict(list)
    for record in salary_data:
        parts = record.rstrip('\n').split('\t')
        if len(parts) >= 1 and parts[0].isdigit():
            emp_id = parts[0]
            salary_by_emp[emp_id].append(record)

    # employee_id -> list of title records
    title_by_emp = defaultdict(list)
    for record in title_data:
        parts = record.rstrip('\n').split('\t')
        if len(parts) >= 1 and parts[0].isdigit():
            emp_id = parts[0]
            title_by_emp[emp_id].append(record)

    # employee_id -> list of department_employee records
    dept_emp_by_emp = defaultdict(list)
    for record in dept_emp_data:
        parts = record.rstrip('\n').split('\t')
        if len(parts) >= 1 and parts[0].isdigit():
            emp_id = parts[0]
            dept_emp_by_emp[emp_id].append(record)

    return salary_by_emp, title_by_emp, dept_emp_by_emp

def duplicate_with_integrity(header_lines, copy_sections, output_file: str, multiplier: int = 25):
    """
    Duplicate database while maintaining referential integrity.
    For each employee, duplicate all their related records with new IDs.
    """
    output_path = Path(output_file)

    print(f"\nGenerating {multiplier}x enlarged file with referential integrity...")

    # Process header lines - don't add IF NOT EXISTS for PG11 compatibility
    # Instead, we'll drop tables first if they exist
    processed_header = []
    for line in header_lines:
        # Comment out problematic ALTER TABLE statements
        if 'ALTER TABLE' in line and 'SET DEFAULT' in line:
            if 'nextval' in line:
                line = '-- ' + line  # Comment out
        elif 'ALTER TABLE ONLY' in line and 'SET DEFAULT' in line:
            # Skip default value settings
            continue
        processed_header.append(line)

    # Accumulate all data for each table (single COPY block per table)
    accumulated_data = {
        'department': [],
        'department_employee': [],
        'department_manager': [],
        'employee': [],
        'salary': [],
        'title': []
    }

    # Add original data
    for table in ['department', 'department_employee', 'department_manager', 'employee', 'salary', 'title']:
        if table in copy_sections:
            accumulated_data[table] = [l for l in copy_sections[table]['data'] if l.strip() and l.strip() != '\\.']

    # Build lookups for related records
    print("\nBuilding employee record lookups...")
    salary_data = accumulated_data['salary'][:]
    title_data = accumulated_data['title'][:]
    dept_emp_data = accumulated_data['department_employee'][:]

    salary_by_emp, title_by_emp, dept_emp_by_emp = build_employee_lookup(
        salary_data, title_data, dept_emp_data
    )

    print(f"  Employees with salary: {len(salary_by_emp)}")
    print(f"  Employees with titles: {len(title_by_emp)}")
    print(f"  Employees with dept assignments: {len(dept_emp_by_emp)}")

    # Generate new employee IDs starting from 500000
    next_emp_id = 500000

    # Accumulate duplicated data
    print("\nGenerating duplicated records...")
    all_new_emp_mappings = {}  # old_id -> [new_ids]

    for batch_num in range(multiplier - 1):
        print(f"  Batch {batch_num + 1}/{multiplier - 1}...")

        employee_data = [l for l in copy_sections['employee']['data'] if l.strip() and l.strip() != '\\.']
        new_emp_ids_this_batch = {}

        for emp_record in employee_data:
            parts = emp_record.rstrip('\n').split('\t')
            if not parts or not parts[0].isdigit():
                continue

            old_emp_id = parts[0]
            new_emp_id = str(next_emp_id)
            next_emp_id += 1

            # Store mapping
            new_emp_ids_this_batch[old_emp_id] = new_emp_id
            if old_emp_id not in all_new_emp_mappings:
                all_new_emp_mappings[old_emp_id] = []
            all_new_emp_mappings[old_emp_id].append(new_emp_id)

            # Write employee record with new ID
            parts[0] = new_emp_id
            accumulated_data['employee'].append('\t'.join(parts) + '\n')

            # Add salary records
            if old_emp_id in salary_by_emp:
                for salary_record in salary_by_emp[old_emp_id]:
                    parts_sal = salary_record.rstrip('\n').split('\t')
                    parts_sal[0] = new_emp_id
                    accumulated_data['salary'].append('\t'.join(parts_sal) + '\n')

            # Add title records
            if old_emp_id in title_by_emp:
                for title_record in title_by_emp[old_emp_id]:
                    parts_title = title_record.rstrip('\n').split('\t')
                    parts_title[0] = new_emp_id
                    accumulated_data['title'].append('\t'.join(parts_title) + '\n')

            # Add department_employee records
            if old_emp_id in dept_emp_by_emp:
                for dept_emp_record in dept_emp_by_emp[old_emp_id]:
                    parts_de = dept_emp_record.rstrip('\n').split('\t')
                    parts_de[0] = new_emp_id
                    accumulated_data['department_employee'].append('\t'.join(parts_de) + '\n')

        if (batch_num + 1) % 5 == 0:
            print(f"    Completed {batch_num + 1}/{multiplier - 1} batches")

    # Write all data to file (single COPY block per table)
    with open(output_path, 'w', encoding='utf-8') as f:
        # Write header with IF NOT EXISTS clauses
        for line in processed_header:
            f.write(line)

        # Write all accumulated data
        print("\nWriting data to file...")
        for table in ['department', 'department_employee', 'department_manager', 'employee', 'salary', 'title']:
            if accumulated_data[table]:
                section = copy_sections[table]
                f.write(section['header'])
                for line in accumulated_data[table]:
                    f.write(line)
                f.write('\\.\n')
                print(f"  {table}: {len(accumulated_data[table])} rows")

    output_size = output_path.stat().st_size
    print(f"\nDone!")
    print(f"Output size: {output_size / 1024 / 1024:.1f} MB")

    return output_size

if __name__ == '__main__':
    # File paths
    INPUT_FILE = '/home/diego/Trident/images/server/employees_data_modified.sql'
    OUTPUT_FILE = '/home/diego/Trident/images/server/employees_data_large.sql'
    BACKUP_FILE = '/home/diego/Trident/images/server/employees_data_modified.sql.backup'

    # Create backup if not exists
    import shutil
    if not Path(BACKUP_FILE).exists():
        print(f"Creating backup: {BACKUP_FILE}")
        shutil.copy2(INPUT_FILE, BACKUP_FILE)

    # Parse the input file
    header_lines, copy_sections, all_lines = parse_sql_file(INPUT_FILE)

    # Generate enlarged database with referential integrity
    try:
        input_size = Path(INPUT_FILE).stat().st_size
        output_size = duplicate_with_integrity(header_lines, copy_sections, OUTPUT_FILE, multiplier=25)

        actual_multiplier = output_size / input_size
        print(f"\nInput size:  {input_size / 1024 / 1024:.1f} MB")
        print(f"Output size: {output_size / 1024 / 1024:.1f} MB")
        print(f"Actual multiplier: {actual_multiplier:.1f}x")
        print(f"\n✅ Successfully created enlarged database: {OUTPUT_FILE}")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
