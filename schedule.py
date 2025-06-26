import os
import sqlite3
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
import json
import logging
import re

logging.basicConfig(level=logging.DEBUG)
load_dotenv()

class ScheduleGenerator:
    def __init__(self, user_id):
        self.user_id = user_id
        self.api_key = os.getenv("COHERE_API_KEY")
        if not self.api_key:
            raise ValueError("Missing Cohere API Key! Set it in a .env file.")

        self.api_url = "https://api.cohere.ai/v1/chat"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    def get_db_connection(self):
        conn = sqlite3.connect('tasks.db')
        conn.row_factory = sqlite3.Row
        return conn

    def fetch_tasks(self):
        conn = self.get_db_connection()
        try:
            today = datetime.now().date().strftime('%Y-%m-%d')

            pending_tasks = conn.execute("""
                SELECT id, title, deadline, priority, description, status 
                FROM tasks 
                WHERE user_id = ? AND status NOT IN ('completed', 'deleted') 
                ORDER BY deadline ASC, priority DESC
                LIMIT 10
            """, (self.user_id,)).fetchall()

            completed_tasks = conn.execute("""
                SELECT id, title, deadline, priority, description, status 
                FROM tasks 
                WHERE user_id = ? AND status = 'completed'
                ORDER BY deadline DESC
                LIMIT 10
            """, (self.user_id,)).fetchall()

            overdue_tasks = conn.execute("""
                SELECT id, title, deadline, priority, description, status 
                FROM tasks 
                WHERE user_id = ? AND deadline < ? AND status NOT IN ('completed', 'deleted')
                ORDER BY deadline ASC
            """, (self.user_id, today)).fetchall()

            return {
                "pending": pending_tasks,
                "completed": completed_tasks,
                "overdue": overdue_tasks
            }
        finally:
            conn.close()

    def analyze_overdue_tasks(self, overdue_tasks):
        reasons = []
        suggestions = []
        if overdue_tasks:
            for task in overdue_tasks:
                reasons.append(f"- {task['title']} (Due: {task['deadline']}, Priority: {task['priority']})")
            suggestions.extend([
                "Break large tasks into smaller subtasks with deadlines",
                "Use timeboxing (25-50 minute focused sessions)",
                "Schedule buffer time between tasks"
            ])
        else:
            reasons.append("No overdue tasks - good time management!")
        return {"reasons": reasons, "suggestions": suggestions}

    def format_task_list(self, tasks):
        formatted = []
        for task in tasks["pending"] + tasks["completed"]:
            formatted.append(
                f"- {task['title']} (Due: {task['deadline']}, Priority: {task['priority']}, Desc: {task['description'] or 'None'})"
            )
        return "\n".join(formatted)

    def generate_prompt(self, task_list, overdue_analysis):
        return f"""
Generate a study schedule in the following strict JSON format only:

{{
  "goal_setting": {{
    "daily_goal": "...",
    "weekly_goal": "...",
    "long_term_goal": "..."
  }},
  "daily_schedule": [
    {{"time": "...", "activity": "...", "notes": "..."}},
    {{"time": "...", "activity": "...", "notes": "..."}}
  ],
  "weekly_review": {{
    "went_well": "...",
    "to_improve": ["..."],
    "next_focus": ["..."]
  }},
  "resources": {{
    "books": "...",
    "apps": "...",
    "materials": "..."
  }},
  "progress_tracker": [
    {{"date": "YYYY-MM-DD", "topic": "...", "status": true, "notes": "..."}},
    {{"date": "YYYY-MM-DD", "topic": "...", "status": false, "notes": "..."}}
  ]
}}

User's Tasks:
{task_list}

Overdue Tasks:
{overdue_analysis['reasons']}
Only return valid JSON.
"""

    def generate_schedule(self):
        try:
            tasks = self.fetch_tasks()

            if not tasks["pending"] and not tasks["overdue"] and not tasks["completed"]:
                return {
                    "error": True,
                    "message": "No tasks available.",
                    "data": None
                }

            overdue_analysis = self.analyze_overdue_tasks(tasks["overdue"])
            task_list = self.format_task_list(tasks)
            prompt = self.generate_prompt(task_list, overdue_analysis)

            response = requests.post(
                self.api_url,
                headers=self.headers,
                json={
                    "message": prompt,
                    "chat_history": [],
                    "temperature": 0.4,
                    "stream": False
                },
                timeout=30
            )

            if response.status_code == 200:
                try:
                    result = response.json()
                    generated_text = result.get("text", "")
                    schedule_data = self.clean_json_response(generated_text)
                    schedule_data = self.validate_schedule(schedule_data)
                    return {
                        "error": False,
                        "message": "Schedule generated.",
                        "data": json.dumps(schedule_data, ensure_ascii=False)
                    }
                except Exception as e:
                    logging.error(f"Cohere processing error: {e}")
                    return {"error": True, "message": "Invalid response format.", "data": None}
            else:
                logging.error(f"Cohere API Error: {response.status_code}")
                return {"error": True, "message": f"API error {response.status_code}", "data": None}

        except Exception as e:
            logging.error(f"Cohere API exception: {str(e)}")
            return {"error": True, "message": "Schedule generation failed.", "data": None}

    def clean_json_response(self, text):
        try:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except Exception as e:
            logging.error("JSON clean-up failed: " + str(e))
            raise ValueError("Could not extract valid JSON from model output.")

    def validate_schedule(self, schedule_data):
        def clean(s):
            return s.strip().replace("\n", " ").replace("\"", "") if isinstance(s, str) else s

        for key in ["goal_setting", "resources"]:
            if key in schedule_data:
                for sub in schedule_data[key]:
                    schedule_data[key][sub] = clean(schedule_data[key][sub])

        for field in ["to_improve", "next_focus"]:
            if field in schedule_data.get("weekly_review", {}):
                val = schedule_data["weekly_review"][field]
                if isinstance(val, str):
                    schedule_data["weekly_review"][field] = [clean(val)]
                elif isinstance(val, list):
                    schedule_data["weekly_review"][field] = [clean(x) for x in val]

        for entry in schedule_data.get("daily_schedule", []):
            entry["time"] = clean(entry.get("time", ""))
            entry["activity"] = clean(entry.get("activity", ""))
            entry["notes"] = clean(entry.get("notes", ""))

        for entry in schedule_data.get("progress_tracker", []):
            entry["topic"] = clean(entry.get("topic", ""))
            entry["notes"] = clean(entry.get("notes", ""))
            entry["status"] = entry.get("status", False)

        return schedule_data
