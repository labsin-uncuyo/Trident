#!/usr/bin/env python3
"""
Generate GHOSTS timeline.json from LLM-generated SQL queries
"""

import json
import sys
import os
import argparse
from typing import List, Dict
from llm_query_generator import LLMQueryGenerator


class TimelineGenerator:
    """Generates GHOSTS timeline from SQL queries"""
    
    def __init__(self, queries: List[str], delay_before: int = 5000, delay_after: int = 10000, role: str = "senior_developer_role"):
        self.queries = queries
        self.delay_before = delay_before
        self.delay_after = delay_after
        self.role = role
        
    def _escape_query_for_ssh(self, query: str) -> str:
        """Escape SQL query for SSH command execution"""
        # Remove semicolon if present
        query = query.rstrip(';').strip()
        
        # Escape single quotes by ending the string, adding escaped quote, and continuing
        query = query.replace("'", "'\"'\"'")
        
        # Handle dollar signs for PostgreSQL dollar quoting
        query = query.replace("$$", "\\$\\$")
        
        return query
    
    def _create_ssh_command(self, sql_query: str) -> str:
        """Create SSH command that executes SQL query on compromised machine"""
        escaped_query = self._escape_query_for_ssh(sql_query)
        
        # Build psql command
        psql_cmd = f'PGPASSWORD="john_scott" psql -h 172.31.0.10 -p 5432 -U john_scott -d labdb -c "{escaped_query}" 2>&1'
        
        # Wrap in SSH command
        ssh_cmd = (
            f"ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
            f"-i /root/.ssh/id_rsa labuser@172.30.0.10 '{psql_cmd}'"
        )
        
        return ssh_cmd
    
    def _create_timeline_event(self, sql_query: str, delay_before: int, delay_after: int) -> Dict:
        """Create a single timeline event"""
        return {
            "Command": self._create_ssh_command(sql_query),
            "CommandArgs": [],
            "DelayBefore": delay_before,
            "DelayAfter": delay_after
        }
    
    def generate_timeline(self, loop: bool = False) -> Dict:
        """Generate complete GHOSTS timeline"""
        
        events = []
        
        # Add intro message
        events.append({
            "Command": (
                'ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null '
                '-i /root/.ssh/id_rsa labuser@172.30.0.10 '
                f'"echo \'[JOHN_SCOTT] Senior Developer ({self.role}) starting LLM-driven work session at $(date)\'"\''
            ),
            "CommandArgs": [],
            "DelayBefore": 2000,
            "DelayAfter": 5000
        })
        
        # Add SQL query events
        for i, query in enumerate(self.queries):
            # Vary delays slightly for realism
            delay_before = self.delay_before + (i % 3) * 1000
            delay_after = self.delay_after + (i % 4) * 2000
            
            events.append(self._create_timeline_event(query, delay_before, delay_after))
        
        # Add closing message
        events.append({
            "Command": (
                'ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null '
                '-i /root/.ssh/id_rsa labuser@172.30.0.10 '
                '"echo \'[JOHN_SCOTT] LLM-driven work session completed at $(date)\'"'
            ),
            "CommandArgs": [],
            "DelayBefore": 3000,
            "DelayAfter": 10000
        })
        
        # Build complete timeline
        timeline = {
            "Status": "Run",
            "TimeLineHandlers": [
                {
                    "HandlerType": "Bash",
                    "Initial": "",
                    "UtcTimeOn": "00:00:00",
                    "UtcTimeOff": "23:59:00",
                    "Loop": loop,
                    "TimeLineEvents": events
                }
            ]
        }
        
        return timeline


def main():
    parser = argparse.ArgumentParser(description="Generate GHOSTS timeline from LLM queries")
    parser.add_argument("--num-queries", type=int, default=5, help="Number of queries to generate")
    parser.add_argument("--scenario", type=str, default="developer_routine",
                       choices=["developer_routine", "hr_audit", "performance_review", "exploratory"],
                       help="Scenario type for query generation")
    parser.add_argument("--role", type=str, default="senior_developer_role",
                       help="Database role (determines permissions and behavior)")
    parser.add_argument("--delay-before", type=int, default=5000, help="Delay before each command (ms)")
    parser.add_argument("--delay-after", type=int, default=10000, help="Delay after each command (ms)")
    parser.add_argument("--loop", action="store_true", help="Enable timeline looping")
    parser.add_argument("--output", type=str, default="/tmp/timeline_john_scott_llm.json",
                       help="Output timeline file")
    
    args = parser.parse_args()
    
    # Generate queries using LLM
    print(f"Generating {args.num_queries} queries with scenario: {args.scenario}, role: {args.role}...", file=sys.stderr)
    generator = LLMQueryGenerator(num_queries=args.num_queries, scenario=args.scenario, role=args.role)
    queries = generator.generate_queries()
    
    if not queries:
        print("✗ No queries generated", file=sys.stderr)
        sys.exit(1)
    
    print(f"✓ Generated {len(queries)} queries", file=sys.stderr)
    
    # Generate timeline
    print(f"Creating GHOSTS timeline...", file=sys.stderr)
    timeline_gen = TimelineGenerator(
        queries=queries,
        delay_before=args.delay_before,
        delay_after=args.delay_after,
        role=args.role
    )
    timeline = timeline_gen.generate_timeline(loop=args.loop)
    
    # Save timeline
    with open(args.output, 'w') as f:
        json.dump(timeline, f, indent=2)
    
    print(f"✓ Timeline saved to {args.output}", file=sys.stderr)
    print(f"  - Total events: {len(timeline['TimeLineHandlers'][0]['TimeLineEvents'])}", file=sys.stderr)
    print(f"  - Loop enabled: {timeline['TimeLineHandlers'][0]['Loop']}", file=sys.stderr)
    
    # Also output to stdout for verification
    print(json.dumps(timeline, indent=2))


if __name__ == "__main__":
    main()
