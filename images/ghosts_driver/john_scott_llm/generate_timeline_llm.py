#!/usr/bin/env python3
"""
Timeline Generator with LLM for John Scott (Senior Developer)
Generates SQL queries dynamically using an LLM based on employee database schema
"""

import os
import json
import logging
import requests
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# LLM Configuration from environment
LLM_API_KEY = os.getenv('OPENAI_API_KEY', '')
LLM_BASE_URL = os.getenv('OPENAI_BASE_URL', 'https://chat.ai.e-infra.cz/api').rstrip('/')
LLM_MODEL = os.getenv('LLM_MODEL', 'qwen3-coder')
LLM_TEMPERATURE = float(os.getenv('LLM_TEMPERATURE', '0.7'))

# Database connection details
DB_HOST = "172.30.0.3"
DB_PORT = "5432"
DB_NAME = "employees"
DB_USER = "laboratorio"
DB_PASS = "scotty@1"

# SSH connection details
SSH_TARGET = "labuser@172.30.0.10"
SSH_KEY = "/root/.ssh/id_rsa"
SSH_OPTIONS = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"

# Database schema for context
DATABASE_SCHEMA = """
DATABASE: employees (PostgreSQL)
HOST: 172.30.0.3, PORT: 5432, USER: laboratorio

TABLES:
1. employees (id, name, email, department, position, salary, hire_date)
2. departments (id, name, manager_id, budget)
3. projects (id, name, start_date, end_date, budget, status)
4. assignments (employee_id, project_id, role, hours_allocated)

SAMPLE QUERIES:
- SELECT * FROM employees WHERE department='Engineering' LIMIT 10;
- SELECT e.name, d.name as department FROM employees e JOIN departments d ON e.department_id=d.id LIMIT 5;
- SELECT COUNT(*) FROM employees WHERE hire_date >= '2023-01-01';
- SELECT AVG(salary) FROM employees GROUP BY department;
- SELECT p.name, COUNT(a.employee_id) as team_size FROM projects p LEFT JOIN assignments a ON p.id=a.project_id GROUP BY p.name;
"""

SYSTEM_PROMPT = f"""You are a PostgreSQL query generator for John Scott, a Senior Developer.

{DATABASE_SCHEMA}

Generate ONLY the PostgreSQL query without any explanation, markdown formatting, or additional text.
The query must be a valid PostgreSQL statement that can be executed directly.
Vary the queries - include SELECT, JOIN, GROUP BY, COUNT, AVG, SUM operations.
Keep queries realistic for a developer's daily work.
Respond with ONLY the SQL query, nothing else."""


def call_llm(prompt: str) -> str:
    """Call the LLM API to generate a SQL query"""
    url = f"{LLM_BASE_URL}/v1/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "temperature": LLM_TEMPERATURE,
        "max_tokens": 200
    }
    
    try:
        logger.info(f"Calling LLM API at {url}")
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        sql_query = result['choices'][0]['message']['content'].strip()
        
        # Clean up the response - remove markdown formatting if present
        sql_query = sql_query.replace('```sql', '').replace('```', '').strip()
        
        logger.info(f"Generated query: {sql_query}")
        return sql_query
        
    except requests.exceptions.RequestException as e:
        logger.error(f"LLM API request failed: {e}")
        return None
    except (KeyError, IndexError) as e:
        logger.error(f"Failed to parse LLM response: {e}")
        return None


def generate_sql_query(task_description: str) -> str:
    """Generate a SQL query based on task description"""
    query = call_llm(task_description)
    
    if not query:
        # Fallback to simple query if LLM fails
        logger.warning("LLM failed, using fallback query")
        return "SELECT * FROM employees LIMIT 5;"
    
    return query


def create_ssh_command(remote_command: str) -> str:
    """Create SSH command to execute on remote host"""
    escaped_command = remote_command.replace('"', '\\"')
    return f'ssh {SSH_OPTIONS} -i {SSH_KEY} {SSH_TARGET} "{escaped_command}"'


def generate_timeline():
    """Generate the timeline JSON with LLM-generated SQL queries"""
    
    timeline = {
        "Id": "d531df3a-c946-4a53-beac-57d70c97d799",
        "Status": "Active",
        "TimeLineHandlers": [
            {
                "HandlerType": "Command",
                "Initial": "",
                "UtcTimeOn": "00:00:00",
                "UtcTimeOff": "23:59:00",
                "Loop": True,
                "TimeLineEvents": []
            }
        ]
    }
    
    # Task descriptions for LLM to generate queries
    tasks = [
        "Check all employees in the Engineering department",
        "Find the average salary by department",
        "List all active projects with their team sizes",
        "Get recent hires from the last year",
        "Show department budgets and managers",
        "Find employees working on multiple projects",
        "Calculate total project hours by employee",
        "List departments with more than 10 employees"
    ]
    
    events = []
    
    # Initial greeting
    events.append({
        "Command": create_ssh_command(
            "echo '[JOHN_SCOTT_LLM] Senior Developer starting LLM-powered work session at $(date)'"
        ),
        "CommandArgs": [],
        "DelayAfter": 10000,
        "DelayBefore": 5000
    })
    
    # Generate SQL queries using LLM
    for i, task in enumerate(tasks):
        logger.info(f"Generating query {i+1}/{len(tasks)}: {task}")
        
        sql_query = generate_sql_query(task)
        
        if sql_query:
            # Create psql command
            psql_cmd = f"PGPASSWORD={DB_PASS} psql -h {DB_HOST} -p {DB_PORT} -U {DB_USER} -d {DB_NAME} -c \\\"{sql_query}\\\""
            
            events.append({
                "Command": create_ssh_command(
                    f"echo '[JOHN_SCOTT_LLM] Task: {task}' && {psql_cmd}"
                ),
                "CommandArgs": [],
                "DelayAfter": 30000,
                "DelayBefore": 15000
            })
    
    # Add some general developer activities
    events.extend([
        {
            "Command": create_ssh_command("ps aux | grep postgres"),
            "CommandArgs": [],
            "DelayAfter": 20000,
            "DelayBefore": 10000
        },
        {
            "Command": create_ssh_command("df -h"),
            "CommandArgs": [],
            "DelayAfter": 20000,
            "DelayBefore": 10000
        },
        {
            "Command": create_ssh_command(
                "echo '[JOHN_SCOTT_LLM] Daily database analysis completed at $(date)'"
            ),
            "CommandArgs": [],
            "DelayAfter": 15000,
            "DelayBefore": 10000
        }
    ])
    
    timeline["TimeLineHandlers"][0]["TimeLineEvents"] = events
    
    return timeline


def main():
    """Main function to generate and save timeline"""
    logger.info("Starting LLM-powered timeline generation for John Scott")
    logger.info(f"Using LLM: {LLM_MODEL} at {LLM_BASE_URL}")
    
    try:
        timeline = generate_timeline()
        
        output_file = "/opt/john_scott_llm/timeline_john_scott_llm.json"
        with open(output_file, 'w') as f:
            json.dump(timeline, f, indent=2)
        
        logger.info(f"\n[SUCCESS] Timeline generated successfully: {output_file}")
        logger.info(f"[INFO] Generated timeline with {len(timeline['TimeLineHandlers'][0]['TimeLineEvents'])} commands")
        
        # Also copy to the location expected by GHOSTS
        config_timeline = "/app/config/timeline.json"
        os.makedirs(os.path.dirname(config_timeline), exist_ok=True)
        with open(config_timeline, 'w') as f:
            json.dump(timeline, f, indent=2)
        logger.info(f"[INFO] Timeline copied to {config_timeline}")
        
        return 0
        
    except Exception as e:
        logger.error(f"[ERROR] Failed to generate timeline: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
