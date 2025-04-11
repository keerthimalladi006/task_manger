import os
import sqlite3
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
import json
import logging
import re
from json import JSONDecodeError

logging.basicConfig(level=logging.DEBUG)
load_dotenv()

class ScheduleGenerator:
    def __init__(self):
        self.api_key = os.getenv("HUGGINGFACE_API_KEY")
        if not self.api_key:
            raise ValueError("Missing Hugging Face API Key! Set it in a .env file.")
        
        self.model = "mistralai/Mistral-7B-Instruct-v0.3"
        self.api_url = f"https://api-inference.huggingface.co/models/{self.model}"
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
                WHERE status NOT IN ('completed', 'deleted') 
                ORDER BY deadline ASC, priority DESC
                LIMIT 10
            """).fetchall()
            
            completed_tasks = conn.execute("""
                SELECT id, title, deadline, priority, description, status 
                FROM tasks 
                WHERE status = 'completed'
                ORDER BY deadline DESC
                LIMIT 10
            """).fetchall()
            
            overdue_tasks = conn.execute("""
                SELECT id, title, deadline, priority, description, status 
                FROM tasks 
                WHERE deadline < ? AND status NOT IN ('completed', 'deleted')
                ORDER BY deadline ASC
            """, (today,)).fetchall()
            
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
        for task in tasks["pending"]:
            formatted.append(
                f"- {task['title']} (Due: {task['deadline']}, "
                f"Priority: {task['priority']}, "
                f"Desc: {task['description'] or 'None'}"
            )
        return "\n".join(formatted)
    
    def generate_prompt(self, task_list, overdue_analysis):
        """Generate a prompt that ensures all fields have meaningful values"""
        return f"""Generate a complete daily schedule in JSON format with ALL fields populated meaningfully.
    Use this exact structure with no empty/null values:
    {{
    "goal_setting": {{
        "daily_goal": "A specific achievable goal for today",
        "weekly_goal": "A measurable goal for this week",
        "long_term_goal": "Your overarching learning objective"
    }},
    "daily_schedule": [
        {{
        "time": "HH:MM AM/PM-HH:MM AM/PM",
        "activity": "A specific task to complete",
        "notes": "Helpful details or resources"
        }}
    ],
    "weekly_review": {{
        "went_well": "What worked well this week",
        "to_improve": "Areas needing improvement",
        "next_focus": "Priority for the coming week"
    }},
    "resources": {{
        "books": "Relevant book titles",
        "apps": "Useful applications",
        "materials": "Other helpful resources"
    }},
    "progress_tracker": [
    {{
      "date": "YYYY-MM-DD",
      "topic": "Specific task/subject",
      "status": true,
      "notes": "Progress details"
    }}
  ]
    }}
    Rules for progress_tracker:
    1. Include 2-3 recent items (mix completed/pending)
    2. Use actual dates from the past week
    3. Make notes specific ("Reviewed functions", "Practiced loops")
    4. Never use "None" or empty values
    5. Status should reflect real progress (true/false)
        Base this on:
        - Pending Tasks: {task_list}
        - Overdue Analysis: {overdue_analysis['reasons']}

    IMPORTANT RULES:
    1. NEVER use "None" or null values - provide actual content
    2. All time slots should be realistic (1-3 hour blocks)
    3. Include at least 2 daily schedule items
    4. Make all suggestions specific and actionable
    5. Return ONLY the JSON object with no additional text"""
    
    def generate_schedule(self):
        try:
            # Prepare the prompt and make the API request
            tasks = self.fetch_tasks()
            overdue_analysis = self.analyze_overdue_tasks(tasks["overdue"])
            task_list = self.format_task_list(tasks)
            prompt = self.generate_prompt(task_list, overdue_analysis)
            
            response = requests.post(
                self.api_url,
                headers=self.headers,
                json={
                    "inputs": prompt,
                    "parameters": {
                        "max_new_tokens": 600,
                        "temperature": 0.3,
                        "do_sample": False,
                        "return_full_text": False
                    }
                },
                timeout=30
            )

            if response.status_code == 200:
                try:
                    result = response.json()
                    
                    # Handle both list and dictionary responses
                    if isinstance(result, list):
                        if result and isinstance(result[0], dict):
                            generated_text = result[0].get('generated_text', '{}')
                        else:
                            raise ValueError("Unexpected list response format")
                    elif isinstance(result, dict):
                        generated_text = result.get('generated_text', '{}')
                    else:
                        raise ValueError(f"Unexpected response type: {type(result)}")
                    
                    schedule_data = self.clean_json_response(generated_text)
                    schedule_data = self.validate_schedule(schedule_data)
                    
                    return {
                        "error": False,
                        "message": "Schedule generated successfully",
                        "data": json.dumps(schedule_data, ensure_ascii=False)
                    }
                except Exception as e:
                    logging.error(f"API Processing Error: {str(e)}")
                    logging.debug(f"Raw API response: {response.text}")
                    return self._generate_fallback_schedule()
            else:
                logging.error(f"API Error: {response.status_code}")
                logging.debug(f"API Response: {response.text}")
                return self._generate_fallback_schedule()
            
        except Exception as e:
            logging.error(f"Generation Error: {str(e)}")
            return self._generate_fallback_schedule()
    
    def _generate_fallback_schedule(self):
        """Generate a fallback schedule if API fails"""
        today = datetime.now().strftime('%Y-%m-%d')
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        
        fallback_schedule = {
            "goal_setting": {
                "daily_goal": "Complete at least two pending tasks",
                "weekly_goal": "Finish 5 tasks this week",
                "long_term_goal": "Master Python fundamentals"
            },
            "daily_schedule": [
                {
                    "time": "9:00 AM-11:00 AM",
                    "activity": "Work on code task",
                    "notes": "Focus on debugging logic"
                },
                {
                    "time": "1:00 PM-3:00 PM",
                    "activity": "Review overdue tasks",
                    "notes": "Prioritize high-priority items"
                }
            ],
            "weekly_review": {
                "went_well": "Completed initial setup",
                "to_improve": "Better time management",
                "next_focus": "Focus on overdue tasks"
            },
            "resources": {
                "books": "Python Crash Course",
                "apps": "Notion, Todoist",
                "materials": "Online tutorials"
            },
            "progress_tracker": [
                {
                    "date": yesterday,
                    "topic": "Initial setup",
                    "status": True,
                    "notes": "Configured environment"
                },
                {
                    "date": today,
                    "topic": "Code review",
                    "status": False,
                    "notes": "Scheduled for today"
                }
            ]
        }
        return {
            "error": True,
            "message": "Using fallback schedule due to API failure",
            "data": json.dumps(fallback_schedule, ensure_ascii=False)
        }
    
    def clean_json_response(self, text):
        """Robust JSON extraction with improved error handling"""
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        
        patterns = [
            (r'```json(.*?)```', 1),
            (r'\{.*\}', 0),
            (r'^.*?(\{.*\}).*?$', 1)
        ]
        
        for pattern, group in patterns:
            try:
                match = re.search(pattern, text, re.DOTALL)
                if match:
                    content = match.group(group).strip()
                    return json.loads(content)
            except:
                continue
        
        try:
            start = text.find('{')
            end = text.rfind('}') + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except:
            pass
        
        raise ValueError("Could not extract valid JSON from response")
    
    def validate_schedule(self, schedule_data):
        if "progress_tracker" not in schedule_data or not schedule_data["progress_tracker"]:
            schedule_data["progress_tracker"] = [
                {
                    "date": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
                    "topic": "Initial setup",
                    "status": True,
                    "notes": "Configured development environment"
                },
                {
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "topic": "Core concepts review",
                    "status": False,
                    "notes": "Scheduled for today"
                }
            ]
        else:
            for entry in schedule_data["progress_tracker"]:
                entry["notes"] = entry.get("notes", "In progress").replace("None", "In progress")
                if "status" not in entry:
                    entry["status"] = False
        
        return schedule_data
