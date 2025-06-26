# Taskly Pro

Taskly Pro is a smart, student-focused task management system designed to help you organize daily study goals, track task progress, manage team projects, and stay consistent using streaks and motivational rewards.

## Description

Built by students, for students — Taskly Pro simplifies your academic workload with AI-powered planning, clear task visibility, and group collaboration tools. Whether working solo or in a team, it helps improve productivity and reduce last-minute stress.

## Features

- AI-powered study planner using Cohere API
- Daily scheduling of tasks with in-progress, completed, and deleted views
- Progress tracking with streaks and leaderboard
- Team-based task assignment and file uploads
- Responsive UI with a clean dashboard
- Simple user authentication system (register, login, profile)

## Languages & Technologies Used

- Frontend: HTML, TailwindCSS, JavaScript (basic interactivity)
- Backend: Python (Flask framework)
- Templating: Jinja2
- Database: SQLite
- AI API: Cohere (for study plan generation)
- Environment: Virtualenv
- Others: JSON (for streak data)

## Project Structure

taskmanager/
├── static/
│   └── css/
│       ├── five.css
│       ├── schedule.css
│       └── tailwind.config.js
│
├── templates/
│   ├── base.html
│   ├── base_auth.html
│   ├── base_nav.html
│   ├── index.html
│   ├── login.html
│   ├── register.html
│   ├── profile.html
│   ├── tasks.html
│   ├── task_item.html
│   ├── completed.html
│   ├── deleted.html
│   ├── inprogress.html
│   ├── schedule.html
│   ├── study_plan.html
│   ├── leaderboard.html
│   ├── teams.html
│   └── todo.html
│
├── index.py              # Main Flask entry point
├── schedule.py           # Task scheduling logic
├── study_plan.py         # AI planner logic
├── utils.py              # Utility/helper functions
├── streak.json           # Streak data
├── .env                  # Cohere API key (not committed)
├── .gitignore
├── LICENSE
├── README.md
└── requirements.txt

## How to Run the Project

Follow the steps below to run Taskly Pro locally.

### 1. Clone the Repository

git clone https://github.com/yourusername/taskly-pro.git
cd taskly-pro

### 2. Create a Virtual Environment

python -m venv venv

### 3. Activate the Virtual Environment

On Windows:
venv\Scripts\activate

On macOS/Linux:
source venv/bin/activate

### 4. Install Dependencies

pip install -r requirements.txt

### 5. Set Up the API Key

1. Go to https://cohere.com and sign up for a free API key.
2. Create a .env file in the project root.
3. Add the following line:

COHERE_API_KEY=your_api_key_here

Make sure this key is loaded in your code using os.environ.get() or the dotenv module.

### 6. Run the Application

python index.py

Open your browser and go to: http://127.0.0.1:5000

## License

This project is licensed under the MIT License. See the LICENSE file for details.

## Authors

- Keerthi – Backend development, authentication, collaboration features
- Varshitha – Frontend design, AI planner integration, dashboard, streaks, rewards
