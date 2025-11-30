#!/usr/bin/env python3
"""
LLM Query Generator for John Scott NPC
Generates PostgreSQL queries dynamically using an LLM based on the NPC's profile and objectives
"""

import os
import json
import requests
import logging
from typing import Optional, Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class LLMQueryGenerator:
    """Generates PostgreSQL queries using LLM for realistic senior developer behavior"""
    
    def __init__(self):
        """Initialize LLM connection parameters from environment"""
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")
        self.openai_base_url = os.getenv("OPENAI_BASE_URL", "https://chat.ai.e-infra.cz/api/v1")
        self.llm_model = os.getenv("LLM_MODEL", "qwen3-coder")
        self.temperature = float(os.getenv("LLM_TEMPERATURE", "0.7"))
        
        # SSH connection details (hardcoded as requested)
        self.ssh_host = "172.30.0.10"
        self.ssh_user = "labuser"
        self.ssh_key_path = "/root/.ssh/id_rsa"
        
        # Database connection details
        self.db_host = "172.31.0.10"
        self.db_port = "5432"
        self.db_name = "labdb"
        self.db_user = "john_scott"
        self.db_password = "john_scott"
        
        # NPC Profile
        self.npc_profile = {
            "name": "John Scott",
            "role": "Senior Developer",
            "department": "Engineering",
            "description": "Experienced senior developer with deep expertise in database architecture and backend systems."
        }
        
        # Database schema for context
        self.db_schema = """
Database: labdb
Tables:
- employee (id, first_name, last_name, hire_date, gender, birth_date)
- department (id, dept_name)
- department_employee (employee_id, department_id, from_date, to_date)
- title (employee_id, title, from_date, to_date)
- salary (employee_id, amount, from_date, to_date)
        """
        
        logger.info(f"LLM Query Generator initialized with model: {self.llm_model}")
    
    def _call_llm(self, prompt: str) -> Optional[str]:
        """Call LLM API to generate content"""
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.openai_api_key}"
            }
            
            payload = {
                "model": self.llm_model,
                "messages": [
                    {"role": "system", "content": self._get_system_prompt()},
                    {"role": "user", "content": prompt}
                ],
                "temperature": self.temperature,
                "max_tokens": 500
            }
            
            url = f"{self.openai_base_url}/chat/completions"
            logger.debug(f"Calling LLM API: {url}")
            
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            content = result['choices'][0]['message']['content'].strip()
            
            logger.debug(f"LLM Response: {content}")
            return content
            
        except requests.exceptions.Timeout:
            logger.error("LLM API request timed out")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"LLM API request failed: {e}")
            return None
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            logger.error(f"Failed to parse LLM response: {e}")
            return None
    
    def _get_system_prompt(self) -> str:
        """Get the system prompt for the LLM"""
        return f"""You are a SQL query generator for a senior database developer named {self.npc_profile['name']}.

Your role: Generate realistic PostgreSQL queries that a {self.npc_profile['role']} would run during normal work activities.

Database Schema:
{self.db_schema}

CRITICAL RULES:
1. Return ONLY valid PostgreSQL SQL queries
2. Do NOT include explanations, comments, or markdown formatting
3. Use proper PostgreSQL syntax with double quotes for identifiers if needed
4. Use $$ for string literals to avoid escaping issues
5. Queries should be realistic for a senior developer's daily tasks
6. Include analytical queries, performance checks, data exploration
7. Each query should be on a single line or use standard SQL formatting

Example queries you might generate:
- SELECT current_database(), current_user, version();
- SELECT e.first_name, e.last_name, d.dept_name FROM employee e JOIN department_employee de ON e.id = de.employee_id JOIN department d ON de.department_id = d.id WHERE d.dept_name = $$Engineering$$ LIMIT 10;
- SELECT d.dept_name, COUNT(de.employee_id) as employee_count FROM department d JOIN department_employee de ON d.id = de.department_id GROUP BY d.dept_name;
- SELECT AVG(s.amount) as avg_salary FROM salary s WHERE s.to_date = $$9999-01-01$$;

Generate queries that show professional database work: joins, aggregations, analytics, data quality checks, etc."""
    
    def generate_query(self, task_description: str) -> Optional[str]:
        """Generate a PostgreSQL query based on task description"""
        logger.info(f"Generating query for task: {task_description}")
        
        prompt = f"""Generate a PostgreSQL query for the following task:
Task: {task_description}

Remember: Return ONLY the SQL query, no explanations or formatting."""
        
        query = self._call_llm(prompt)
        
        if query:
            # Clean up the query
            query = self._clean_query(query)
            logger.info(f"Generated query: {query[:100]}...")
            return query
        else:
            logger.warning("Failed to generate query, using fallback")
            return self._get_fallback_query(task_description)
    
    def _clean_query(self, query: str) -> str:
        """Clean up LLM-generated query"""
        # Remove markdown code blocks
        query = query.replace("```sql", "").replace("```", "")
        
        # Remove leading/trailing whitespace
        query = query.strip()
        
        # Remove multiple spaces
        import re
        query = re.sub(r'\s+', ' ', query)
        
        return query
    
    def _get_fallback_query(self, task_description: str) -> str:
        """Return a fallback query if LLM fails"""
        fallback_queries = [
            "SELECT current_database(), current_user, inet_server_addr(), inet_server_port();",
            "SELECT COUNT(*) as total_employees FROM employee;",
            "SELECT d.dept_name, COUNT(de.employee_id) as count FROM department d LEFT JOIN department_employee de ON d.id = de.department_id GROUP BY d.dept_name;",
            "SELECT e.first_name, e.last_name, e.hire_date FROM employee e ORDER BY e.hire_date DESC LIMIT 5;",
        ]
        
        import random
        return random.choice(fallback_queries)
    
    def generate_ssh_command(self, sql_query: str) -> str:
        """Generate complete SSH command with SQL query"""
        # Escape query for shell
        escaped_query = sql_query.replace('"', '\\"').replace('$', '\\$')
        
        ssh_command = (
            f'ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null '
            f'-i {self.ssh_key_path} {self.ssh_user}@{self.ssh_host} '
            f'\'PGPASSWORD="{self.db_password}" psql -h {self.db_host} -p {self.db_port} '
            f'-U {self.db_user} -d {self.db_name} -c "{escaped_query}" 2>&1\''
        )
        
        return ssh_command
    
    def generate_activity_sequence(self, num_queries: int = 5) -> list[Dict[str, Any]]:
        """Generate a sequence of database activities"""
        logger.info(f"Generating sequence of {num_queries} activities")
        
        tasks = [
            "Check database connection and version information",
            "List all departments with employee counts",
            "Find recently hired employees in Engineering department",
            "Calculate average salary by department",
            "Find senior-level employees and their salaries",
            "Check database performance statistics",
            "List employees with their current titles",
            "Find highest paid employees",
            "Count employees by gender in each department",
            "Find employees hired in the last year"
        ]
        
        import random
        selected_tasks = random.sample(tasks, min(num_queries, len(tasks)))
        
        activities = []
        
        # Initial connection message
        activities.append({
            "type": "echo",
            "command": f'ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i {self.ssh_key_path} {self.ssh_user}@{self.ssh_host} "echo \'[JOHN_SCOTT_LLM] Senior Developer starting LLM-powered work session at $(date)\'"',
            "delay_before": 5000,
            "delay_after": 10000
        })
        
        # Generate queries
        for task in selected_tasks:
            query = self.generate_query(task)
            if query:
                ssh_cmd = self.generate_ssh_command(query)
                activities.append({
                    "type": "query",
                    "task": task,
                    "sql": query,
                    "command": ssh_cmd,
                    "delay_before": 5000,
                    "delay_after": random.randint(20000, 35000)
                })
        
        # Final message
        activities.append({
            "type": "echo",
            "command": f'ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i {self.ssh_key_path} {self.ssh_user}@{self.ssh_host} "echo \'[JOHN_SCOTT_LLM] LLM-powered work session cycle completed at $(date)\'"',
            "delay_before": 5000,
            "delay_after": 60000
        })
        
        logger.info(f"Generated {len(activities)} activities")
        return activities
    
    def generate_timeline_json(self, output_file: str = "timeline_john_scott_llm.json"):
        """Generate complete GHOSTS timeline JSON file"""
        logger.info(f"Generating timeline JSON: {output_file}")
        
        activities = self.generate_activity_sequence()
        
        timeline_events = []
        for activity in activities:
            timeline_events.append({
                "Command": activity["command"],
                "CommandArgs": [],
                "DelayBefore": activity["delay_before"],
                "DelayAfter": activity["delay_after"]
            })
        
        timeline = {
            "Status": "Run",
            "TimeLineHandlers": [
                {
                    "HandlerType": "Bash",
                    "Initial": "",
                    "UtcTimeOn": "00:00:00",
                    "UtcTimeOff": "23:59:00",
                    "Loop": True,
                    "TimeLineEvents": timeline_events
                }
            ]
        }
        
        with open(output_file, 'w') as f:
            json.dump(timeline, f, indent=2)
        
        logger.info(f"Timeline generated successfully: {output_file}")
        return output_file


def main():
    """Main function for testing"""
    logger.info("=== LLM Query Generator Test ===")
    
    generator = LLMQueryGenerator()
    
    # Test single query generation
    logger.info("\n--- Testing Single Query Generation ---")
    query = generator.generate_query("Find all employees in the Engineering department")
    print(f"\nGenerated Query:\n{query}\n")
    
    # Test SSH command generation
    logger.info("\n--- Testing SSH Command Generation ---")
    ssh_cmd = generator.generate_ssh_command(query)
    print(f"\nSSH Command:\n{ssh_cmd}\n")
    
    # Test full timeline generation
    logger.info("\n--- Testing Timeline Generation ---")
    timeline_file = generator.generate_timeline_json()
    print(f"\nTimeline generated: {timeline_file}\n")


if __name__ == "__main__":
    main()
