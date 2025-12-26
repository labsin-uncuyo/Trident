#!/usr/bin/env python3
"""
LLM-based SQL Query Generator for John Scott persona
Generates realistic database queries using an LLM agent with context about the database schema
"""

import json
import subprocess
import sys
import os
import time
from typing import List, Dict, Optional
import argparse


class DatabaseSchema:
    """Represents the employee database schema with role-based context"""
    
    SCHEMA_INFO = """
    PostgreSQL Database: labdb
    Connection: Two-step process
      1. SSH to labuser@172.30.0.10 (compromised machine)
      2. psql -h 172.31.0.10 -p 5432 -U john_scott -d labdb

    Tables and columns (exact):
    - department
      - id character(4) NOT NULL
      - dept_name character varying(40) NOT NULL
      Indexes: PRIMARY KEY(id), UNIQUE(dept_name)

    - department_employee
      - employee_id bigint NOT NULL
      - department_id character(4) NOT NULL
      - from_date date NOT NULL
      - to_date date NOT NULL
      Indexes: PRIMARY KEY(employee_id, department_id)
      Foreign keys: employee(id) -> department_employee(employee_id), department(id) -> department_employee(department_id)

    - employee
      - id bigint NOT NULL (nextval('id_employee_seq'))
      - birth_date date NOT NULL
      - first_name character varying(14) NOT NULL
      - last_name character varying(16) NOT NULL
      - gender employee_gender NOT NULL
      - hire_date date NOT NULL
      Indexes: PRIMARY KEY(id)

    - department_manager
      - employee_id bigint NOT NULL
      - department_id character(4) NOT NULL
      - from_date date NOT NULL
      - to_date date NOT NULL
      Indexes: PRIMARY KEY(employee_id, department_id)

    - salary
      - employee_id bigint NOT NULL
      - amount bigint NOT NULL
      - from_date date NOT NULL
      - to_date date NOT NULL
      Indexes: PRIMARY KEY(employee_id, from_date)
      Foreign key: salary.employee_id -> employee.id

    - title
      - employee_id bigint NOT NULL
      - title character varying(50) NOT NULL
      - from_date date NOT NULL
      - to_date date
      Indexes: PRIMARY KEY(employee_id, title, from_date)
      Foreign key: title.employee_id -> employee.id

    - events
      - id integer NOT NULL (nextval events_id_seq)
      - msg text
      Indexes: PRIMARY KEY(id)

    Common patterns and constraints:
    - Current/active records often use to_date = '9999-01-01'
    - Join employee <-> department via department_employee
    - Use LIMIT and ORDER BY for predictable outputs
    - Prefer selecting explicit columns rather than SELECT *
    """
    
    ROLE_INFO = {
        "senior_developer_role": """
        Role: senior_developer_role
        User: john_scott (password: john_scott)
        
        Permissions:
        - DML: SELECT, INSERT, UPDATE, DELETE on all tables
        - DDL: CREATE on schema public
        - Can read/modify data for development and testing purposes
        - Has elevated privileges for database structure changes
        
        Typical Activities:
        - Query employee records and department data
        - Check salary ranges for budget planning
        - Analyze team composition and hiring patterns
        - Review title progressions and career paths
        - Create test data or temporary tables
        - Run analytics queries for reporting
        - Monitor system events and logs
        """
    }
    
    @staticmethod
    def get_context(role: str = "senior_developer_role") -> str:
        """Get database context with role-specific information"""
        role_context = DatabaseSchema.ROLE_INFO.get(role, "")
        return DatabaseSchema.SCHEMA_INFO + "\n" + role_context


class LLMQueryGenerator:
    """Generates SQL queries using OpenCode LLM"""
    
    def __init__(self, num_queries: int = 5, scenario: str = "developer_routine", role: str = "senior_developer_role"):
        self.num_queries = num_queries
        self.scenario = scenario
        self.role = role
        self.opencode_available = self._check_opencode()
        
    def _check_opencode(self) -> bool:
        """Check if OpenCode is available"""
        try:
            result = subprocess.run(
                ["opencode", "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
    
    def _get_scenario_context(self) -> str:
        """Get context based on scenario type"""
        scenarios = {
            "developer_routine": """
                John Scott is a Senior Developer checking on:
                - Team members in the Development department
                - Recent hires and their backgrounds
                - Salary information for budget planning
                - Title progressions and promotions
                - Department statistics and headcounts
            """,
            "hr_audit": """
                John Scott is conducting an HR audit:
                - Employee count by department
                - Salary ranges and averages
                - Long-tenured employees
                - Recent organizational changes
                - Manager assignments
            """,
            "performance_review": """
                John Scott is preparing performance reviews:
                - Direct reports and their titles
                - Salary history and adjustments
                - Time in current position
                - Cross-department comparisons
                - Career progression patterns
            """,
            "exploratory": """
                John Scott is exploring the database:
                - Random analytical queries
                - Data quality checks
                - Statistical aggregations
                - Complex joins and subqueries
                - Edge cases and corner scenarios
            """
        }
        return scenarios.get(self.scenario, scenarios["developer_routine"])
    
    def generate_queries_with_llm(self) -> List[str]:
        """Generate SQL queries using OpenCode LLM"""
        
        prompt = f"""Generate {self.num_queries} realistic PostgreSQL SQL queries for the following context:

{DatabaseSchema.get_context(self.role)}

Scenario: {self._get_scenario_context()}

Important Requirements (STRICT):
1. Generate EXACTLY {self.num_queries} different SQL queries.
2. Each query MUST be a single-line valid PostgreSQL SELECT statement (no multi-line queries).
3. Do NOT output any psql or shell commands. Output only the raw SQL SELECT statements.
4. The timeline generator will wrap these SQL statements into SSH + psql -c '<SQL>' commands; therefore avoid statements that require interactive psql (no \\copy, no psql meta-commands, no prompts).
5. Prefer explicit column lists (no SELECT *), use proper JOINs, WHERE clauses, aggregations, ORDER BY and LIMIT for readability.
6. Use to_date = '9999-01-01' when referring to current records where appropriate.
7. Do NOT include explanations, comments, or any extra text. Output only SQL queries separated by the exact token: ---QUERY--- on its own line.
8. Keep result sizes reasonable (use LIMIT when listing rows).

Output format (every query must end with a semicolon):
SELECT ... FROM ... WHERE ... ;
---QUERY---
SELECT ... FROM ... WHERE ... ;
---QUERY---
...

Begin generating queries now:"""

        try:
            # Use OpenCode to generate queries
            result = subprocess.run(
                ["opencode", "chat", "--no-stream"],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                output = result.stdout
                queries = self._parse_llm_output(output)
                if queries:
                    return queries
                else:
                    print("⚠ LLM output could not be parsed, using fallback queries", file=sys.stderr)
                    return self._get_fallback_queries()
            else:
                print(f"⚠ OpenCode failed: {result.stderr}", file=sys.stderr)
                return self._get_fallback_queries()
                
        except subprocess.TimeoutExpired:
            print("⚠ OpenCode timeout, using fallback queries", file=sys.stderr)
            return self._get_fallback_queries()
        except Exception as e:
            print(f"⚠ Error calling OpenCode: {e}", file=sys.stderr)
            return self._get_fallback_queries()
    
    def _parse_llm_output(self, output: str) -> List[str]:
        """Parse SQL queries from LLM output"""
        queries = []
        
        # Try splitting by ---QUERY---
        if "---QUERY---" in output:
            parts = output.split("---QUERY---")
            for part in parts:
                query = part.strip()
                if query and "SELECT" in query.upper():
                    # Clean up the query
                    query = self._clean_query(query)
                    if query:
                        queries.append(query)
        else:
            # Try to find SELECT statements
            lines = output.split('\n')
            current_query = []
            in_query = False
            
            for line in lines:
                if "SELECT" in line.upper():
                    in_query = True
                    current_query = [line]
                elif in_query:
                    current_query.append(line)
                    if ';' in line:
                        query = self._clean_query(' '.join(current_query))
                        if query:
                            queries.append(query)
                        current_query = []
                        in_query = False
        
        return queries[:self.num_queries]
    
    def _clean_query(self, query: str) -> str:
        """Clean and validate a SQL query"""
        # Remove markdown code blocks
        query = query.replace('```sql', '').replace('```', '')
        
        # Remove extra whitespace
        query = ' '.join(query.split())
        
        # Ensure it ends with semicolon
        query = query.strip()
        if not query.endswith(';'):
            query += ';'
        
        # Basic validation
        if "SELECT" in query.upper() and "FROM" in query.upper():
            return query
        
        return ""
    
    def _get_fallback_queries(self) -> List[str]:
        """Fallback queries if LLM fails"""
        fallback = [
            "SELECT current_database(), current_user, version();",
            "SELECT COUNT(*) as total_employees FROM employee;",
            "SELECT d.dept_name, COUNT(de.employee_id) as employee_count FROM department d JOIN department_employee de ON d.id = de.department_id GROUP BY d.dept_name ORDER BY employee_count DESC;",
            "SELECT e.first_name, e.last_name, t.title FROM employee e JOIN title t ON e.id = t.employee_id WHERE t.to_date = '9999-01-01' LIMIT 10;",
            "SELECT AVG(s.amount) as avg_salary FROM salary s WHERE s.to_date = '9999-01-01';"
        ]
        return fallback[:self.num_queries]
    
    def generate_queries(self) -> List[str]:
        """Main method to generate queries"""
        if self.opencode_available:
            print(f"✓ Using OpenCode LLM to generate {self.num_queries} queries...", file=sys.stderr)
            queries = self.generate_queries_with_llm()
        else:
            print(f"⚠ OpenCode not available, using fallback queries", file=sys.stderr)
            queries = self._get_fallback_queries()
        
        return queries


def main():
    parser = argparse.ArgumentParser(description="Generate SQL queries using LLM")
    parser.add_argument("--num-queries", type=int, default=5, help="Number of queries to generate")
    parser.add_argument("--scenario", type=str, default="developer_routine",
                       choices=["developer_routine", "hr_audit", "performance_review", "exploratory"],
                       help="Scenario type for query generation")
    parser.add_argument("--role", type=str, default="senior_developer_role",
                       help="Database role (determines permissions and behavior)")
    parser.add_argument("--output", type=str, help="Output file (default: stdout)")
    
    args = parser.parse_args()
    
    generator = LLMQueryGenerator(num_queries=args.num_queries, scenario=args.scenario, role=args.role)
    queries = generator.generate_queries()
    
    print(f"\n✓ Generated {len(queries)} queries", file=sys.stderr)
    
    # Output queries
    output_content = "\n\n".join(queries)
    
    if args.output:
        with open(args.output, 'w') as f:
            f.write(output_content)
        print(f"✓ Queries saved to {args.output}", file=sys.stderr)
    else:
        print("\n=== Generated Queries ===\n")
        print(output_content)


if __name__ == "__main__":
    main()
